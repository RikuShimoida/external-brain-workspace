#!/usr/bin/env python3
"""Instagram の「自分の言葉」から「地図」を作る。

本文はディスクに残さず、1件ぶんの (日付・種別・スレッド・要約・文字数) だけを一覧化する。
どのキャプション・会話が濃いかを眺めて、instagram_extract.py で本文を取る対象を選ぶための
下ごしらえ。LINE / Messenger の *_map.py と同じ考え方。

Instagram はデータ種別が複数（ストーリー/投稿のキャプション・コメント・DM・質問箱回答）
あるため、talk_map.tsv に **kind 列** を持たせて1本に束ねる。

プライバシー: DM の room 列にはスレッドのフォルダ ID（<ローマ字名>_<数字>）を入れ、
相手の実名は書かない（Messenger と同じ方針）。地図に本文は書かず要約（先頭 60 字）のみ。

使い方:
    python3 scripts/instagram_map.py
      --owner 名前 … 自分の表示名（既定: Riku Shimoida）

出力:
    instagram-archive/talk_map.tsv  … 1行=1件の要約（日付順）
    標準出力に件数・期間・種別ごとの内訳などのサマリ
"""
import sys
import datetime as dt
from collections import Counter

from instagram_parse import parse_all, OWNER

OUT = "instagram-archive/talk_map.tsv"


def _date_str(ts):
    """UNIX 秒を "YYYY/MM/DD" に。ローカル時刻で見る。"""
    if not ts:
        return ""
    return dt.datetime.fromtimestamp(ts).strftime("%Y/%m/%d")


def _summary(body, limit=60):
    """地図用の1行要約。改行をつぶして先頭 limit 字。"""
    s = " ".join(body.split())
    return s[:limit]


def main():
    args = sys.argv[1:]
    owner = OWNER
    if "--owner" in args:
        i = args.index("--owner")
        owner = args[i + 1]
        del args[i : i + 2]

    items = parse_all(owner)
    if not items:
        sys.exit("データが見つかりません: instagram-archive を展開しましたか？")

    # 日付順（無い日付は末尾）に並べる
    items.sort(key=lambda it: (it.ts == 0, it.ts))

    with open(OUT, "w", encoding="utf-8") as w:
        w.write("date\tkind\troom\tsender\tchars\tsummary\n")
        for it in items:
            w.write(
                f"{_date_str(it.ts)}\t{it.kind}\t{it.room}\t{it.sender}\t"
                f"{len(it.body)}\t{_summary(it.body)}\n"
            )

    # --- サマリ ---
    by_kind = Counter(it.kind for it in items)
    dates = [it.ts for it in items if it.ts]
    print(f"総件数: {len(items):,}")
    print("種別ごとの内訳:")
    labels = {
        "story": "ストーリーのキャプション",
        "post": "投稿のキャプション",
        "comment": "自分のコメント",
        "dm": "DM（自分＋相手）",
        "question": "質問箱・投票の回答",
    }
    for k, n in by_kind.most_common():
        print(f"  {labels.get(k, k)}: {n:,}")

    # DM のうち自分の発言だけの数（他は全部自分）
    dm_mine = sum(1 for it in items if it.kind == "dm" and it.sender == owner)
    dm_total = by_kind.get("dm", 0)
    if dm_total:
        print(f"  （うち DM の自分の発言: {dm_mine:,} / {dm_total:,}）")

    if dates:
        lo = dt.datetime.fromtimestamp(min(dates)).date()
        hi = dt.datetime.fromtimestamp(max(dates)).date()
        print(f"期間: {lo} 〜 {hi}")

    by_year = Counter(_date_str(it.ts)[:4] for it in items if it.ts)
    print("年ごとの件数:")
    for y in sorted(by_year):
        print(f"  {y}: {by_year[y]:,}")

    print("\n長いキャプション・発言（上位10件・本文は出さず要約のみ）:")
    for it in sorted(items, key=lambda x: -len(x.body))[:10]:
        print(f"  {_date_str(it.ts):<10} {it.kind:<8} {len(it.body):>5}字  {_summary(it.body, 40)}")

    print(f"\n一覧を書き出しました: {OUT}")


if __name__ == "__main__":
    main()
