#!/usr/bin/env python3
"""LINE のトーク履歴から「濃い日」だけ本文を抽出する。

その日いちばん長いメッセージが閾値を超える日だけを Markdown 化する。
長文が数件ある日は仕組みの設計や相談で、短文が大量に飛び交う日は雑談。
文字数の合計ではなく「最長メッセージ」で見ると、前者だけを拾える。

抜き出すのはその日のやりとり全部。長文だけ切り出すと前後の文脈が消えるため。

使い方:
    python3 scripts/line_extract.py [閾値] [--dry-run] [--room 名前]
      閾値      … その日の最長メッセージの文字数の下限（既定 300）
      --dry-run … 書き出さず対象日だけ表示
      --room    … ルーム名で絞る（部分一致）

出力:
    line-archive/deep/YYYY-MM-DD_ルーム名.md
"""
import os
import re
import sys
import glob
from collections import defaultdict

from line_parse import parse

OUTDIR = "line-archive/deep"
THRESHOLD = 300


def safe_name(s):
    """ファイル名に使える形に均す。"""
    s = re.sub(r"[^\w぀-ヿ一-鿿 ー-]", "", s)
    return s.strip().replace(" ", "_")[:40] or "無題"


def main():
    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    room_filter = None
    if "--room" in argv:
        i = argv.index("--room")
        room_filter = argv[i + 1]
        del argv[i : i + 2]
    nums = [a for a in argv if not a.startswith("--")]
    threshold = int(nums[0]) if nums else THRESHOLD

    paths = sorted(glob.glob("line-archive/*.txt"))
    if not paths:
        sys.exit("トーク履歴が見つかりません: line-archive/*.txt")

    # (日付, ルーム) -> その日のメッセージ
    days = defaultdict(list)
    for path in paths:
        room, messages = parse(path)
        if room_filter and room_filter not in room:
            continue
        for msg in messages:
            days[(msg.date, room)].append(msg)

    picked = []
    for (date, room), msgs in days.items():
        longest = max((len(m.body) for m in msgs if not m.is_attachment), default=0)
        if longest >= threshold:
            picked.append((date, room, longest, msgs))
    picked.sort(key=lambda x: (x[0], x[1]))

    total_chars = sum(sum(len(m.body) for m in p[3]) for p in picked)
    print(f"最長 {threshold} 字以上の日: {len(picked)} 日（本文計 {total_chars:,} 字）")

    if dry:
        for date, room, longest, msgs in picked:
            print(f"  {date}  {room[:20]:<20}  {len(msgs):>3}件  最長{longest:>5}字")
        return

    os.makedirs(OUTDIR, exist_ok=True)
    for date, room, longest, msgs in picked:
        fname = f"{OUTDIR}/{date.replace('/', '-')}_{safe_name(room)}.md"
        with open(fname, "w", encoding="utf-8") as w:
            w.write(f"# {room} {date}\n\n")
            w.write(f"- メッセージ数: {len(msgs)}\n- 最長: {longest} 字\n\n---\n\n")
            for m in msgs:
                w.write(f"**{m.time} {m.speaker}:**\n\n{m.body}\n\n")
    print(f"{len(picked)} 件を {OUTDIR}/ に書き出しました。")


if __name__ == "__main__":
    main()
