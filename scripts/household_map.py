#!/usr/bin/env python3
"""家計（MF ME）の CSV から「地図」と月次サマリを作る。

household-archive/*.csv（計算対象=1 の明細）を年月ごとに集計し、2つを書き出す:

  household-archive/household_map.tsv
      … 月ごと1行の推移索引（収入・支出・収支・支出件数・大項目トップ3）。
        複数月の CSV を置けば自動で全月が1本に並ぶ（毎回フル上書き）。

  household-archive/summary_YYYY-MM.md
      … その月の収支サマリと大項目別・中項目別の内訳（金額・件数）。

プライバシー: 個別明細（店名・口座名・日付つきの1取引）は出さない。
大項目 / 中項目の集計までに留める。家計は freee（事業）とはレンズが別。

使い方:
    python3 scripts/household_map.py
      --root パス   … リポジトリのルート（既定: カレント）
      --dry-run     … 書き込まず標準出力に出す

出力:
    上記2種のファイル（--dry-run 時は household_map.tsv の内容を標準出力に）
    stderr に件数・対象月などのサマリ
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

from household_parse import Entry, parse_all

MAP_REL = "household-archive/household_map.tsv"
SUMMARY_REL_FMT = "household-archive/summary_{month}.md"

MAP_COLUMNS = ["month", "収入", "支出", "収支", "支出件数", "大項目トップ3"]


def _by_month(entries: list[Entry]) -> dict[str, list[Entry]]:
    buckets: dict[str, list[Entry]] = defaultdict(list)
    for e in entries:
        if e.month:
            buckets[e.month].append(e)
    return buckets


def _expense_by_major(entries: list[Entry]) -> list[tuple[str, int, int]]:
    """支出を大項目ごとに (大項目, 金額合計, 件数) で集計し、金額降順で返す。"""
    amt: dict[str, int] = defaultdict(int)
    cnt: dict[str, int] = defaultdict(int)
    for e in entries:
        if e.is_expense:
            amt[e.major] += -e.amount
            cnt[e.major] += 1
    rows = [(major, amt[major], cnt[major]) for major in amt]
    rows.sort(key=lambda r: -r[1])
    return rows


def _expense_by_minor(entries: list[Entry], major: str) -> list[tuple[str, int, int]]:
    """ある大項目の中で、中項目ごとに (中項目, 金額合計, 件数) を金額降順で返す。"""
    amt: dict[str, int] = defaultdict(int)
    cnt: dict[str, int] = defaultdict(int)
    for e in entries:
        if e.is_expense and e.major == major:
            amt[e.minor] += -e.amount
            cnt[e.minor] += 1
    rows = [(minor, amt[minor], cnt[minor]) for minor in amt]
    rows.sort(key=lambda r: -r[1])
    return rows


def _map_row(month: str, entries: list[Entry]) -> list[str]:
    income = sum(e.amount for e in entries if e.is_income)
    expense = sum(-e.amount for e in entries if e.is_expense)
    expense_cnt = sum(1 for e in entries if e.is_expense)
    top3 = _expense_by_major(entries)[:3]
    top3_str = " / ".join(f"{major}:{amt:,}" for major, amt, _ in top3)
    return [
        month,
        str(income),
        str(expense),
        str(income - expense),
        str(expense_cnt),
        top3_str,
    ]


def build_map(entries: list[Entry]) -> str:
    buckets = _by_month(entries)
    body = "\t".join(MAP_COLUMNS) + "\n"
    for month in sorted(buckets):
        body += "\t".join(_map_row(month, buckets[month])) + "\n"
    return body


def build_summary(month: str, entries: list[Entry]) -> str:
    income = sum(e.amount for e in entries if e.is_income)
    expense = sum(-e.amount for e in entries if e.is_expense)
    income_cnt = sum(1 for e in entries if e.is_income)
    expense_cnt = sum(1 for e in entries if e.is_expense)

    lines: list[str] = []
    lines.append(f"# 家計サマリ {month}")
    lines.append("")
    lines.append("MF ME（マネーフォワード ME）の「収入・支出詳細」CSV から、")
    lines.append("計算対象=1 の明細だけを集計したもの。個別の取引・店名・口座名は載せない。")
    lines.append("")
    lines.append("## 収支")
    lines.append("")
    lines.append("| 区分 | 金額（円） | 件数 |")
    lines.append("|---|--:|--:|")
    lines.append(f"| 収入 | {income:,} | {income_cnt} |")
    lines.append(f"| 支出 | {expense:,} | {expense_cnt} |")
    lines.append(f"| 収支 | {income - expense:,} | — |")
    lines.append("")
    lines.append("## 支出の大項目別内訳（金額降順）")
    lines.append("")
    lines.append("| 大項目 | 金額（円） | 件数 |")
    lines.append("|---|--:|--:|")
    majors = _expense_by_major(entries)
    for major, amt, cnt in majors:
        lines.append(f"| {major or '（空欄）'} | {amt:,} | {cnt} |")
    lines.append("")
    lines.append("## 支出の中項目別内訳（大項目ごと・金額降順）")
    lines.append("")
    for major, _, _ in majors:
        lines.append(f"### {major or '（空欄）'}")
        lines.append("")
        lines.append("| 中項目 | 金額（円） | 件数 |")
        lines.append("|---|--:|--:|")
        for minor, amt, cnt in _expense_by_minor(entries, major):
            lines.append(f"| {minor or '（空欄）'} | {amt:,} | {cnt} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."),
                    help="リポジトリのルート（既定: カレント）")
    ap.add_argument("--dry-run", action="store_true",
                    help="書き込まず標準出力に出す")
    args = ap.parse_args()

    root: Path = args.root
    entries = parse_all(root)
    if not entries:
        print(f"データが見つかりません: {root}/household-archive に CSV を置きましたか？",
              file=sys.stderr)
        return 1

    map_body = build_map(entries)
    buckets = _by_month(entries)
    months = sorted(buckets)

    if args.dry_run:
        sys.stdout.write(map_body)
    else:
        map_out = root / MAP_REL
        map_out.parent.mkdir(parents=True, exist_ok=True)
        map_out.write_text(map_body, encoding="utf-8")
        for month in months:
            summary_out = root / SUMMARY_REL_FMT.format(month=month)
            summary_out.write_text(build_summary(month, buckets[month]),
                                   encoding="utf-8")

    # --- サマリ（stderr） ---
    income = sum(e.amount for e in entries if e.is_income)
    expense = sum(-e.amount for e in entries if e.is_expense)
    print(f"明細（計算対象=1）: {len(entries):,} 件", file=sys.stderr)
    print(f"対象月: {', '.join(months)}", file=sys.stderr)
    print(f"収入合計: {income:,} 円 / 支出合計: {expense:,} 円 / "
          f"収支: {income - expense:,} 円", file=sys.stderr)
    if not args.dry_run:
        print(f"\n→ {root / MAP_REL} に {len(months)} か月分を書き出しました",
              file=sys.stderr)
        print(f"→ 月次サマリ {len(months)} 件を household-archive/summary_*.md に書き出しました",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
