#!/usr/bin/env python3
"""Google の検索履歴から「地図」を作る。

二段フィルタ（機械式NG + 意味判定 verdicts.tsv）を通過した検索語を、語ごとに
畳み込んで search_map.tsv に一覧化する。**除外後の全ユニーク語**を残す（後から
grep して「いつ何に関心を持ったか」を引ける索引にするため）。deep は頻度で絞るが、
地図は絞らない——LINE/Instagram の「地図=全件・deep=閾値」と同じ非対称。

本文（会話）は無く、地図に載るのは検索語そのもの＋回数＋期間だけ。センシティブ語は
parse の時点で落ちているので、この TSV には出てこない前提。

使い方:
    python3 scripts/google_activity_map.py [--dry-run]
      --dry-run … 書き出さず件数サマリだけ（漏洩チェック前の下見に）

出力:
    google-activity-archive/search_map.tsv … 1行=1検索語（回数降順）
    標準エラーに件数の内訳（総件数・純クエリ・NG除外・意味判定除外・残存・年別など）
"""
import sys
import datetime as dt
from collections import Counter

from google_activity_parse import parse, aggregate

OUT = "google-activity-archive/search_map.tsv"


def _date_str(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%Y/%m/%d") if ts else ""


def main():
    dry = "--dry-run" in sys.argv[1:]

    queries, stats = parse()
    if stats["total"] == 0:
        sys.exit("データが見つかりません: google-activity-archive/_raw/ に展開しましたか？"
                 "（scripts/google_activity_extract.py --unpack <zip>）")

    agg = aggregate(queries)

    # --- サマリ（stderr。本文＝検索語は出さない） ---
    e = sys.stderr
    print(f"総レコード: {stats['total']:,}", file=e)
    print(f"純検索クエリ（正規化後）: {stats['pure']:,}", file=e)
    print(f"機械式NG 除外: {stats['ng_removed']:,}", file=e)
    print(f"意味判定 drop 除外: {stats['verdict_removed']:,}", file=e)
    print(f"残存クエリ（延べ）: {stats['kept']:,}", file=e)
    print(f"残存ユニーク語: {len(agg):,}", file=e)
    repeat = sum(1 for a in agg.values() if a["count"] >= 2)
    print(f"  うち2回以上: {repeat:,}", file=e)

    dates = [q.ts for q in queries if q.ts]
    if dates:
        lo = dt.datetime.fromtimestamp(min(dates)).date()
        hi = dt.datetime.fromtimestamp(max(dates)).date()
        print(f"期間: {lo} 〜 {hi}", file=e)
    by_year = Counter()
    for q in queries:
        if q.ts:
            by_year[dt.datetime.fromtimestamp(q.ts).strftime("%Y")] += 1
    print("年ごとの延べ件数:", file=e)
    for y in sorted(by_year):
        print(f"  {y}: {by_year[y]:,}", file=e)

    if dry:
        print("(--dry-run: 書き出しはしていません)", file=e)
        return

    # 回数降順・同数は語順で安定化
    rows = sorted(agg.items(), key=lambda kv: (-kv[1]["count"], kv[0]))
    with open(OUT, "w", encoding="utf-8") as w:
        w.write("query\tcount\tfirst\tlast\tyears\n")
        for text, a in rows:
            years = ",".join(sorted(a["years"]))
            w.write(
                f"{text}\t{a['count']}\t{_date_str(a['first'])}\t"
                f"{_date_str(a['last'])}\t{years}\n"
            )

    print(f"\n一覧を書き出しました: {OUT}", file=e)


if __name__ == "__main__":
    main()
