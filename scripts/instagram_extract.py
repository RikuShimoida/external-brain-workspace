#!/usr/bin/env python3
"""Instagram の「自分の言葉」から、濃いものだけ本文を抽出する。

2種類を Markdown 化する:
  1. 長いキャプション・コメント・質問箱回答（閾値以上の1件を書き出す）
     → ストーリー/投稿の長文キャプションが Podcast ネタの本命。
  2. 濃い DM 会話（その日の最長メッセージが閾値以上の (日付, スレッド) の全やりとり）
     → 相談・思考整理が出るのは長文が数件ある日。LINE / Messenger と同じ考え方。

プライバシー: DM の相手の実名は成果物に出さない。出力ファイル名・見出しには
スレッド ID を使い、相手の発言は "相手" 名義で書く（本文の文脈は残す）。

使い方:
    python3 scripts/instagram_extract.py [閾値] [--dry-run] [--kind story|post|comment|dm|question]
      閾値      … 本文の文字数の下限（キャプション系）／その日の最長メッセージの下限（DM）。既定 120
      --dry-run … 書き出さず対象だけ表示
      --kind    … 種別で絞る

出力:
    instagram-archive/deep/captions_<kind>.md      … キャプション系をまとめて
    instagram-archive/deep/dm_YYYY-MM-DD_スレッドID.md … DM は日×スレッドごと
"""
import os
import re
import sys
import datetime as dt
from collections import defaultdict

from instagram_parse import parse_captions, parse_comments, parse_questions, parse_dms

OUTDIR = "instagram-archive/deep"
THRESHOLD = 120


def safe_name(s):
    """ファイル名に使える形に均す。"""
    s = re.sub(r"[^\w぀-ヿ一-鿿 ー-]", "", s)
    return s.strip().replace(" ", "_")[:40] or "無題"


def _date_str(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%Y/%m/%d") if ts else ""


def main():
    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    if dry:
        argv.remove("--dry-run")
    kind_filter = None
    if "--kind" in argv:
        i = argv.index("--kind")
        kind_filter = argv[i + 1]
        del argv[i : i + 2]
    nums = [a for a in argv if not a.startswith("--")]
    threshold = int(nums[0]) if nums else THRESHOLD

    # --- キャプション系（story/post/comment/question）: 1件が閾値以上なら拾う ---
    singles = parse_captions() + parse_comments() + parse_questions()
    if kind_filter:
        singles = [it for it in singles if it.kind == kind_filter]
    picked_singles = [it for it in singles if len(it.body) >= threshold]
    picked_singles.sort(key=lambda it: (it.kind, it.ts))

    # --- DM: (日付, スレッド) 単位で、その日の最長発言が閾値以上なら全やりとりを拾う ---
    dm_days = defaultdict(list)
    if not kind_filter or kind_filter == "dm":
        for it in parse_dms():
            dm_days[(_date_str(it.ts), it.room)].append(it)
    picked_dm = []
    for (date, room), its in dm_days.items():
        longest = max((len(x.body) for x in its), default=0)
        if longest >= threshold:
            picked_dm.append((date, room, longest, sorted(its, key=lambda x: x.ts)))
    picked_dm.sort(key=lambda x: (x[0], x[1]))

    print(f"閾値 {threshold} 字以上:")
    print(f"  キャプション系: {len(picked_singles)} 件")
    print(f"  DM 会話: {len(picked_dm)} 日×スレッド")

    if dry:
        for it in picked_singles[:30]:
            print(f"  {it.kind:<8} {_date_str(it.ts):<10} {len(it.body):>4}字  {it.body[:40]}")
        for date, room, longest, its in picked_dm[:30]:
            print(f"  dm       {date:<10} {room[:24]:<24} {len(its):>3}件 最長{longest}字")
        return

    os.makedirs(OUTDIR, exist_ok=True)

    # キャプション系は種別ごとに1ファイルへまとめる
    by_kind = defaultdict(list)
    for it in picked_singles:
        by_kind[it.kind].append(it)
    for kind, its in by_kind.items():
        fname = f"{OUTDIR}/captions_{kind}.md"
        with open(fname, "w", encoding="utf-8") as w:
            w.write(f"# Instagram {kind}（{threshold}字以上・{len(its)}件）\n\n")
            for it in its:
                w.write(f"## {_date_str(it.ts)}\n\n{it.body}\n\n---\n\n")

    # DM は日×スレッドごとに1ファイル
    for date, room, longest, its in picked_dm:
        fname = f"{OUTDIR}/dm_{date.replace('/', '-')}_{safe_name(room)}.md"
        with open(fname, "w", encoding="utf-8") as w:
            w.write(f"# DM {room} {date}\n\n")
            w.write(f"- メッセージ数: {len(its)}\n- 最長: {longest} 字\n\n---\n\n")
            for it in its:
                t = dt.datetime.fromtimestamp(it.ts).strftime("%H:%M") if it.ts else "--:--"
                w.write(f"**{t} {it.sender}:**\n\n{it.body}\n\n")

    print(f"キャプション系 {len(by_kind)} ファイル / DM {len(picked_dm)} ファイルを {OUTDIR}/ に書き出しました。")


if __name__ == "__main__":
    main()
