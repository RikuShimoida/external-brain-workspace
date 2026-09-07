#!/usr/bin/env python3
"""Facebook Messenger のトーク履歴から「地図」を作る。

本文はディスクに残さず、1日ぶんの (日付・スレッド・件数・文字数) だけを一覧化する。
どの日が濃いかをタイトル代わりに眺めて、messenger_extract.py で本文を取る日を選ぶための
下ごしらえ。LINE の line_map.py と同じ考え方・同じ列。

プライバシー: 地図の room 列にはスレッドのフォルダ ID（<ローマ字名>_<数字>）を入れ、
相手の実名は書かない。実名の対応が要るときだけ --titles で標準出力に出す。

使い方:
    python3 scripts/messenger_map.py [パス...]
      パス … message_1.json（省略時は messenger-archive 配下の inbox / message_requests を全部）
      --owner 名前 … 自分の表示名（既定: Riku Shimoida）
      --titles     … スレッドID → タイトルの対応も標準出力に出す

出力:
    messenger-archive/talk_map.tsv  … 1行=1日ぶんの要約（日付順）
    標準出力に件数・期間・濃い日の上位などのサマリ
"""
import sys
import glob
import datetime as dt
from collections import Counter, defaultdict

from messenger_parse import parse, thread_id

OWNER = "Riku Shimoida"
OUT = "messenger-archive/talk_map.tsv"
# inbox と message_requests の両方を母集団にする（archived / filtered があれば足す）
GLOBS = [
    "messenger-archive/_raw/your_facebook_activity/messages/inbox/*/message_*.json",
    "messenger-archive/_raw/your_facebook_activity/messages/message_requests/*/message_*.json",
    "messenger-archive/_raw/your_facebook_activity/messages/archived_threads/*/message_*.json",
    "messenger-archive/_raw/your_facebook_activity/messages/filtered_threads/*/message_*.json",
]


def _date_str(ts_ms):
    """timestamp_ms を "YYYY/MM/DD" に。ローカル時刻で見る。"""
    if not ts_ms:
        return ""
    return dt.datetime.fromtimestamp(ts_ms / 1000).strftime("%Y/%m/%d")


def main():
    args = sys.argv[1:]
    owner = OWNER
    show_titles = False
    if "--owner" in args:
        i = args.index("--owner")
        owner = args[i + 1]
        del args[i : i + 2]
    if "--titles" in args:
        show_titles = True
        args.remove("--titles")

    paths = args
    if not paths:
        for g in GLOBS:
            paths.extend(glob.glob(g))
        paths = sorted(paths)
    if not paths:
        sys.exit("メッセージが見つかりません: messenger-archive を展開しましたか？")

    # (日付, スレッドID) -> 集計
    days = defaultdict(lambda: {"n": 0, "mine": 0, "chars": 0, "longest": 0, "attach": 0})
    threads = []  # (スレッドID, タイトル, 件数)
    total = 0

    for path in paths:
        title, messages = parse(path)
        tid = thread_id(path)
        threads.append((tid, title, len(messages)))
        total += len(messages)
        for msg in messages:
            d = days[(_date_str(msg.ts_ms), tid)]
            d["n"] += 1
            if msg.sender == owner:
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
    print(f"スレッド: {len(threads)} 件")
    print(f"総メッセージ数: {total:,}")
    print(f"期間: {dates[0]} 〜 {dates[-1]}（{len(rows):,} 日）" if dates else "期間: 不明")

    by_year = Counter()
    for (date, _room), d in rows:
        if date:
            by_year[date[:4]] += d["n"]
    print("年ごとのメッセージ数:")
    for y in sorted(by_year):
        print(f"  {y}: {by_year[y]:,}")

    print("\nメッセージ数が多いスレッド（上位10）:")
    for tid, title, n in sorted(threads, key=lambda t: -t[2])[:10]:
        print(f"  {n:>5,} 件  {tid}")

    print("\n文字数が多い日（上位10日）:")
    for (date, room), d in sorted(rows, key=lambda kv: -kv[1]["chars"])[:10]:
        print(f"  {date} {room}  {d['chars']:,}字 / {d['n']}件 / 最長{d['longest']}字")

    if show_titles:
        print("\nスレッドID → タイトル（実名を含むので取り扱い注意）:")
        for tid, title, n in sorted(threads, key=lambda t: -t[2]):
            print(f"  {tid}\t{title}")

    print(f"\n一覧を書き出しました: {OUT}")


if __name__ == "__main__":
    main()
