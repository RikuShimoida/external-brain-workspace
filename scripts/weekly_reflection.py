#!/usr/bin/env python3
"""「今日やること - YYYY年M月D日」ノートの5つの振り返り欄を、1週間分まとめて集計する。

週末（日曜など）に、その週7枚分の「今日やること」ノートを見て、次の5見出しの
配下項目を横断で集める。Evernote には一切触らない純ロジック（daily-reflection と
同じ思想）。本体（スキル側）が get_note で退避した JSON を渡してくる想定。

拾う5見出し（ノートにより前後の語がぶれるので **部分一致** で探す）:
  1. 今日、運が良かったこと
  2. 今日、運が悪かったこと
  3. 今日、うまくいったこと
  4. 今日、失敗したプロセス
  5. 今日、失敗した結果

各見出しの「配下」＝ その見出しから次の <hr>（または次の見出し）までの範囲。
範囲内の <li>...</li> をタグ除去して可視テキスト化し、空要素は捨てる。

集計方針（オーナー確定）:
  - 重複はまとめず全件並べる（同じ文言が複数日に出ても各日ぶん残す）。
  - 各項目の先頭に必ず日付を付ける（例: `9/5　項目テキスト`）。
    日付はノートの title からパースする。
    「今日やること - 2026年9月5日」形式 と 「@2026-09-06」形式 の両対応。

出力: 週次レポートを ENML 断片（create_note の content に渡せる本文）として stdout に出す。

使い方:
    python3 scripts/weekly_reflection.py <ノートJSON...> [--week-monday YYYY-MM-DD]

各 JSON は {title, content(ENML), created, ...} 形式。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import re
import sys
from pathlib import Path

# 拾う5見出し。key は集計・表示に使うラベル、value は部分一致で探す語。
SECTIONS = [
    ("luck_good", "今日、運が良かったこと", "運が良かった"),
    ("luck_bad", "今日、運が悪かったこと", "運が悪かった"),
    ("went_well", "今日、うまくいったこと", "うまくいった"),
    ("fail_process", "今日、失敗したプロセス", "失敗プロセス"),
    ("fail_result", "今日、失敗した結果", "失敗結果"),
]

# 見出しタグ（この内側テキストに見出し語が含まれるかで判定する）。
# 実ノートの見出しは必ず <h2>/<h3>。配下は <li><div>...</div></li> 構造なので、
# div/b/span まで見出し候補にすると、見出し直後の <li> 内 <div> を「次の見出し」と
# 誤検出して配下範囲が潰れ、項目が1つも拾えなくなる。見出しは h1〜h6 に限定する。
HEADING_RE = re.compile(r"<(h[1-6])\b[^>]*>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
LI_RE = re.compile(r"<li\b[^>]*>(.*?)</li>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
HR_RE = re.compile(r"<hr\b[^>]*/?>", re.IGNORECASE)


def strip_tags(fragment: str) -> str:
    """HTML 断片からタグを剥がし、実体参照を戻して可視テキストにする。"""
    text = TAG_RE.sub("", fragment)
    text = html.unescape(text)
    # 全角/半角スペース・改行を1個の半角スペースへ寄せる
    text = re.sub(r"[\s　]+", " ", text)
    return text.strip()


def parse_date_from_title(title: str) -> _dt.date | None:
    """ノートのタイトルから日付を得る。2形式に対応。

    - 「今日やること - 2026年9月5日」など「YYYY年M月D日」形式
    - 「@2026-09-06」など「YYYY-MM-DD」形式
    """
    if not title:
        return None
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", title)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        try:
            return _dt.date(y, mo, d)
        except ValueError:
            return None
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", title)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        try:
            return _dt.date(y, mo, d)
        except ValueError:
            return None
    return None


def _label_date(d: _dt.date | None) -> str:
    """項目先頭に付ける日付ラベル（例: 9/5）。日付不明なら空。"""
    if d is None:
        return "?"
    return f"{d.month}/{d.day}"


def _find_heading_spans(enml: str):
    """ENML 内の「見出し候補」を (開始位置, 終了位置, 可視テキスト) で列挙する。"""
    spans = []
    for m in HEADING_RE.finditer(enml):
        text = strip_tags(m.group(2))
        if text:
            spans.append((m.start(), m.end(), text))
    return spans


def extract_section_items(enml: str, needle: str, all_headings) -> list[str]:
    """見出し語 needle を部分一致で含む見出しの「配下」から <li> テキストを集める。

    配下 = その見出しの終わりから、次の <hr> または次の見出しまで。
    """
    # needle を含む最初の見出しを探す
    target = None
    for start, end, text in all_headings:
        if needle in text:
            target = (start, end, text)
            break
    if target is None:
        return []

    _, sec_end, _ = target

    # 配下の終端 = 見出しの後で最初に来る <hr> か 次の見出し のうち早い方
    hr_m = HR_RE.search(enml, sec_end)
    hr_pos = hr_m.start() if hr_m else len(enml)

    next_heading_pos = len(enml)
    for start, _e, _t in all_headings:
        if start >= sec_end and start < next_heading_pos:
            next_heading_pos = start

    section_end = min(hr_pos, next_heading_pos)
    body = enml[sec_end:section_end]

    items = []
    for m in LI_RE.finditer(body):
        text = strip_tags(m.group(1))
        if text:
            items.append(text)
    return items


def load_note(path: Path) -> dict:
    """ノート JSON を読む。get_note の退避形式（{title, content, ...}）を想定。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: JSON はオブジェクトである必要があります")
    return data


def collect(paths: list[Path]) -> tuple[dict, list[_dt.date]]:
    """各ノートから5見出しの項目を抽出。ラベル別に (date, text) を集める。

    戻り値: (results, dates)
      results[label] = [(date, text), ...]（日付昇順、同日内はノート内の並び順）
      dates = 見つかったノートの日付一覧
    """
    per_note = []  # (date, {label: [text,...]})
    for path in paths:
        note = load_note(path)
        title = note.get("title", "") or ""
        enml = note.get("content", "") or note.get("enml", "") or ""
        date = parse_date_from_title(title)
        if date is None:
            # フォールバック: created（ミリ秒 or ISO）から日付を得る
            date = _date_from_created(note.get("created"))
        headings = _find_heading_spans(enml)
        section_items = {}
        for label, heading, _short in SECTIONS:
            section_items[label] = extract_section_items(enml, heading, headings)
        per_note.append((date, section_items))

    # 日付昇順に並べる（日付不明は末尾）
    per_note.sort(key=lambda x: (x[0] is None, x[0] or _dt.date.max))

    results = {label: [] for label, _h, _s in SECTIONS}
    dates = []
    for date, section_items in per_note:
        if date is not None:
            dates.append(date)
        for label, _h, _s in SECTIONS:
            for text in section_items[label]:
                results[label].append((date, text))
    return results, dates


def _date_from_created(created) -> _dt.date | None:
    if created is None:
        return None
    # Evernote の created は epoch ミリ秒のことが多い
    if isinstance(created, (int, float)):
        try:
            return _dt.datetime.fromtimestamp(created / 1000, tz=_dt.timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(created, str):
        m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", created)
        if m:
            try:
                return _dt.date(*(int(x) for x in m.groups()))
            except ValueError:
                return None
    return None


def _monday_of(d: _dt.date) -> _dt.date:
    return d - _dt.timedelta(days=d.weekday())


def build_report(results: dict, week_monday: _dt.date | None) -> str:
    """集計結果を ENML 断片に組み立てる（create_note の content に渡せる形）。"""
    esc = lambda s: html.escape(s, quote=False)

    # サマリー件数
    counts = {label: len(results[label]) for label, _h, _s in SECTIONS}
    summary_parts = [
        f"運が良かった: {counts['luck_good']}件",
        f"運が悪かった: {counts['luck_bad']}件",
        f"うまくいった: {counts['went_well']}件",
        f"失敗プロセス: {counts['fail_process']}件",
        f"失敗結果: {counts['fail_result']}件",
    ]

    lines = []
    if week_monday is not None:
        week_end = week_monday + _dt.timedelta(days=6)
        header = (
            f"{week_monday.year}年{week_monday.month}月{week_monday.day}日"
            f"〜{week_end.month}月{week_end.day}日 の週次振り返り"
        )
        lines.append(f"<div><b>{esc(header)}</b></div>")
    lines.append(f"<div><b>週合計サマリー</b></div>")
    lines.append(f"<div>{esc(' / '.join(summary_parts))}</div>")
    lines.append("<br/>")

    # 見出し名（表示用）
    display = {
        "luck_good": "今日、運が良かったこと",
        "luck_bad": "今日、運が悪かったこと",
        "went_well": "今日、うまくいったこと",
        "fail_process": "今日、失敗したプロセス",
        "fail_result": "今日、失敗した結果",
    }

    for label, _h, _s in SECTIONS:
        items = results[label]
        lines.append(f"<div><b>{esc(display[label])}（計{len(items)}件）</b></div>")
        if items:
            lines.append("<ul>")
            for date, text in items:
                prefix = _label_date(date)
                lines.append(f"<li>{esc(prefix)}　{esc(text)}</li>")
            lines.append("</ul>")
        else:
            lines.append("<div>（なし）</div>")
        lines.append("<br/>")

    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="週次の振り返り集計（Evernote 非依存）")
    parser.add_argument("notes", nargs="+", help="ノート JSON ファイル（1週間分）")
    parser.add_argument(
        "--week-monday",
        help="週の月曜日付（YYYY-MM-DD）。無ければノート日付から推定",
    )
    args = parser.parse_args(argv)

    paths = [Path(p) for p in args.notes]
    missing = [p for p in paths if not p.exists()]
    if missing:
        for p in missing:
            print(f"ファイルが見つかりません: {p}", file=sys.stderr)
        return 1

    results, dates = collect(paths)

    week_monday = None
    if args.week_monday:
        try:
            week_monday = _dt.date.fromisoformat(args.week_monday)
        except ValueError:
            print(f"--week-monday の形式が不正です: {args.week_monday}", file=sys.stderr)
            return 1
    elif dates:
        week_monday = _monday_of(min(dates))

    report = build_report(results, week_monday)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
