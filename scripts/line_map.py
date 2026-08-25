#!/usr/bin/env python3
"""LINE のトーク履歴から「地図」を作る。

本文はディスクに残さず、1日ぶんの (日付・ルーム・件数・文字数) だけを一覧化する。
どの日が濃いかをタイトル代わりに眺めて、line_extract.py で本文を取る日を選ぶための下ごしらえ。

使い方:
    python3 scripts/line_map.py [パス...]
      パス … トーク履歴の .txt（省略時は line-archive/*.txt を全部）
      --owner 名前 … 自分の表示名（既定: 下井田　陸）

出力:
    line-archive/talk_map.tsv  … 1行=1日ぶんの要約（日付順）
    標準出力に件数・期間・濃い日の上位などのサマリ
"""
import sys
import glob
from collections import Counter, defaultdict

from line_parse import parse

OWNER = "下井田　陸"
OUT = "line-archive/talk_map.tsv"


def main():
    args = sys.argv[1:]
    owner = OWNER
    if "--owner" in args:
        i = args.index("--owner")
        owner = args[i + 1]
        del args[i : i + 2]

    paths = args or sorted(glob.glob("line-archive/*.txt"))
    if not paths:
        sys.exit("トーク履歴が見つかりません: line-archive/*.txt")

    # (日付, ルーム) -> 集計
    days = defaultdict(lambda: {"n": 0, "mine": 0, "chars": 0, "longest": 0, "attach": 0})
    rooms = []
    total = 0

    for path in paths:
        room, messages = parse(path)
        rooms.append((room, len(messages)))
        total += len(messages)
        for msg in messages:
            d = days[(msg.date, room)]
            d["n"] += 1
            if msg.speaker == owner:
                d["mine"] += 1
            if msg.is_attachment:
                d["attach"] += 1
            else:
                d["chars"] += len(msg.body)
                d["longest"] = max(d["longest"], len(msg.body))

    rows = sorted(days.items(), key=lambda kv: (kv[0][0] or "", kv[0][1]))

    with open(OUT, "w", encoding="utf-8") as w:
        w.write("date\troom\tmessages\tmine\tchars\tlongest\tattachments\n")
        for (date, room), d in rows:
            w.write(
                f"{date}\t{room}\t{d['n']}\t{d['mine']}\t{d['chars']}\t{d['longest']}\t{d['attach']}\n"
            )

    # サマリ
    dates = [date for (date, _room), _d in rows if date]
    print(f"トークルーム: {len(rooms)} 件")
    for room, n in rooms:
        print(f"  {room}: {n:,} メッセージ")
    print(f"総メッセージ数: {total:,}")
    print(f"期間: {dates[0]} 〜 {dates[-1]}（{len(rows):,} 日）" if dates else "期間: 不明")

    by_year = Counter()
    for (date, _room), d in rows:
        if date:
            by_year[date[:4]] += d["n"]
    print("年ごとのメッセージ数:")
    for y in sorted(by_year):
        print(f"  {y}: {by_year[y]:,}")

    print("\n文字数が多い日（上位10日）:")
    for (date, room), d in sorted(rows, key=lambda kv: -kv[1]["chars"])[:10]:
        print(f"  {date} {room}  {d['chars']:,}字 / {d['n']}件 / 最長{d['longest']}字")

    print(f"\n一覧を書き出しました: {OUT}")


if __name__ == "__main__":
    main()
