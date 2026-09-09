#!/usr/bin/env python3
"""意味判定（A-1b）の結果を verdicts.tsv に追記マージする小スクリプト。

隔離サブエージェント search-query-screener が「捨てる検索語＋理由」の JSON を
返す。その JSON をこのスクリプトが受けて verdicts.tsv に書く。**捨てる語を本体
エージェントの会話コンテキストに載せないための隔離の要**（センシティブ語が本体を
経由しないよう、screener → ファイル → このスクリプト、で完結させる）。

verdicts.tsv の列: query<TAB>verdict(drop/keep)<TAB>reason<TAB>judged_at
同じ query が既にあれば、新しい判定で上書きする（keep→drop の訂正なども効く）。

候補づくり（screener に渡す TSV を作る）:
    python3 scripts/google_activity_screen.py --candidates [--min 2]
      → google-activity-archive/.cache/query_candidates.tsv を作る。
        2回以上検索し（--min）、機械式NG を通過した語だけ（＝意味判定に回す母集団）。
        列: idx<TAB>query<TAB>count。screener にはこの idx 範囲を渡す。

判定の取り込み（screener の返した JSON を verdicts へ）:
    python3 scripts/google_activity_screen.py --from <path.json>
      JSON 形式: [{"query":"...", "verdict":"drop"|"keep", "reason":"..."}, ...]
      query は候補 TSV の語と完全一致させる（screener が原文どおり返す前提）。
"""
import os
import sys
import json
import datetime as dt

from google_activity_parse import (
    parse, aggregate, load_ng_patterns, VERDICTS_PATH,
)

CANDIDATES = "google-activity-archive/.cache/query_candidates.tsv"
DEFAULT_MIN = 2


def build_candidates(min_count=DEFAULT_MIN):
    """意味判定に回す候補 TSV を作る。

    parse() は既に機械式NG と既存 verdicts の drop を除外している。残った語のうち
    min_count 回以上のものを候補にする（1回きりのノイズは意味判定に回さない）。
    """
    queries, stats = parse()
    agg = aggregate(queries)
    rows = [(t, a["count"]) for t, a in agg.items() if a["count"] >= min_count]
    rows.sort(key=lambda r: (-r[1], r[0]))
    os.makedirs(os.path.dirname(CANDIDATES), exist_ok=True)
    with open(CANDIDATES, "w", encoding="utf-8") as w:
        w.write("idx\tquery\tcount\n")
        for i, (text, cnt) in enumerate(rows):
            w.write(f"{i}\t{text}\t{cnt}\n")
    print(f"候補 {len(rows):,} 語を書き出しました: {CANDIDATES}")
    print(f"（{min_count}回以上・機械式NGと既存verdicts drop を除外済み）")
    print("次: search-query-screener にこの TSV のインデックス範囲を渡して意味判定させる。")


def _load_verdicts_raw(path=VERDICTS_PATH):
    """既存 verdicts を {query: (verdict, reason, judged_at)} で読む。"""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        f.readline()  # header
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) >= 4:
                out[cols[0]] = (cols[1], cols[2], cols[3])
    return out


def ingest(json_path):
    """screener の JSON を verdicts.tsv に追記マージする。"""
    with open(os.path.expanduser(json_path), encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        sys.exit("JSON はオブジェクトの配列である必要があります。")

    existing = _load_verdicts_raw()
    now = dt.date.today().isoformat()
    added = 0
    for rec in data:
        q = rec.get("query")
        v = rec.get("verdict")
        if not q or v not in ("drop", "keep"):
            continue
        reason = (rec.get("reason") or "").replace("\t", " ").replace("\n", " ")
        existing[q] = (v, reason, now)
        added += 1

    os.makedirs(os.path.dirname(VERDICTS_PATH), exist_ok=True)
    with open(VERDICTS_PATH, "w", encoding="utf-8") as w:
        w.write("query\tverdict\treason\tjudged_at\n")
        for q, (v, reason, judged) in sorted(existing.items()):
            w.write(f"{q}\t{v}\t{reason}\t{judged}\n")

    drops = sum(1 for v in existing.values() if v[0] == "drop")
    print(f"{added} 件を取り込みました。verdicts.tsv 合計 {len(existing)} 件（drop {drops} 件）。")
    print("次: python3 scripts/google_activity_map.py で再生成し、drop 語が消えたか確認。")


def main():
    argv = sys.argv[1:]
    if "--candidates" in argv:
        min_count = DEFAULT_MIN
        if "--min" in argv:
            i = argv.index("--min")
            min_count = int(argv[i + 1])
        build_candidates(min_count)
        return
    if "--from" in argv:
        i = argv.index("--from")
        ingest(argv[i + 1])
        return
    sys.exit(__doc__)


if __name__ == "__main__":
    main()
