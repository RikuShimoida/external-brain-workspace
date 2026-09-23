#!/usr/bin/env python3
"""YouTube の意味判定（A-1b）の候補づくりと、判定結果の verdicts.tsv への追記マージ。

検索履歴の google_activity_screen.py と同じ型。判定するのは **チャンネル名・再生リスト名**
（動画タイトルは1回きりが多く数万件あるので、機械式NG だけに任せる）。
判定は隔離サブエージェント search-query-screener が行い、捨てる語を本体エージェントの
会話に載せないよう screener → JSON ファイル → このスクリプト、で完結させる。

候補づくり:
    python3 scripts/youtube_screen.py --candidates [--min 2]
      → youtube-archive/.cache/channel_candidates.tsv を作る。列: idx<TAB>query<TAB>count
        母集団 = 機械式NG を通過した「--min 回以上出てくるチャンネル」＋「登録チャンネル全件」
                 ＋「再生リスト名全件」。既に verdicts にある語は除く（判定済み）。

判定の取り込み:
    python3 scripts/youtube_screen.py --from <path.json>
      JSON 形式: [{"query":"...", "verdict":"drop"|"keep", "reason":"..."}, ...]

判定の締め（候補 TSV を**全範囲**判定し終えてから）:
    python3 scripts/youtube_screen.py --settle
      → 候補 TSV のうち verdicts に無い語を keep として記録する。screener は drop しか返さない
        ので、これをしないと次回 --candidates で判定済みの語がまた候補に出てくる
        （＝新しく増えたチャンネルだけを判定に回せなくなる）。

verdicts.tsv の列: query<TAB>verdict(drop/keep)<TAB>reason<TAB>judged_at
"""
import os
import sys
import json
import datetime as dt
from collections import Counter

from google_activity_parse import load_ng_patterns, is_blocked
from youtube_parse import parse, aggregate, load_subscriptions, playlist_files, VERDICTS_PATH

CANDIDATES = "youtube-archive/.cache/channel_candidates.tsv"
DEFAULT_MIN = 2


def _load_verdicts_raw(path=VERDICTS_PATH):
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


def build_candidates(min_count=DEFAULT_MIN):
    ng = load_ng_patterns()
    judged = _load_verdicts_raw()
    counts = Counter()

    events, _ = parse()
    for a in aggregate(events).values():
        if a["count"] >= min_count:
            counts[a["name"]] += a["count"]
    for _, name in load_subscriptions():
        counts[name] += 0
    for name, _ in playlist_files():
        counts[name] += 0

    rows = [(q, c) for q, c in counts.items()
            if q and q not in judged and not is_blocked(q, ng)]
    rows.sort(key=lambda r: (-r[1], r[0]))
    os.makedirs(os.path.dirname(CANDIDATES), exist_ok=True)
    with open(CANDIDATES, "w", encoding="utf-8") as w:
        w.write("idx\tquery\tcount\n")
        for i, (q, c) in enumerate(rows):
            safe = q.replace("\t", " ").replace("\n", " ")
            w.write(f"{i}\t{safe}\t{c}\n")
    print(f"候補 {len(rows):,} 語を書き出しました: {CANDIDATES}")
    print(f"（チャンネル {min_count}回以上＋登録チャンネル＋再生リスト名。機械式NG・判定済みは除外）")
    print("次: search-query-screener にこの TSV のインデックス範囲を渡して意味判定させる。")


def ingest(json_path):
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


def settle():
    """候補 TSV の未判定語を keep として verdicts に記録する。"""
    if not os.path.exists(CANDIDATES):
        sys.exit(f"候補 TSV がありません: {CANDIDATES}（先に --candidates）")
    with open(CANDIDATES, encoding="utf-8") as f:
        f.readline()
        queries = [line.rstrip("\n").split("\t")[1] for line in f if line.strip()]
    existing = _load_verdicts_raw()
    now = dt.date.today().isoformat()
    added = 0
    for q in queries:
        if q not in existing:
            existing[q] = ("keep", "screener: drop 判定なし", now)
            added += 1
    with open(VERDICTS_PATH, "w", encoding="utf-8") as w:
        w.write("query\tverdict\treason\tjudged_at\n")
        for q, (v, reason, judged) in sorted(existing.items()):
            w.write(f"{q}\t{v}\t{reason}\t{judged}\n")
    print(f"未判定 {added} 語を keep として記録しました。verdicts.tsv 合計 {len(existing)} 件。")


def main():
    argv = sys.argv[1:]
    if "--candidates" in argv:
        min_count = DEFAULT_MIN
        if "--min" in argv:
            min_count = int(argv[argv.index("--min") + 1])
        build_candidates(min_count)
        return
    if "--from" in argv:
        ingest(argv[argv.index("--from") + 1])
        return
    if "--settle" in argv:
        settle()
        return
    sys.exit(__doc__)


if __name__ == "__main__":
    main()
