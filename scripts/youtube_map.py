#!/usr/bin/env python3
"""YouTube の「地図」を作る。単位はチャンネル。

二段フィルタ（機械式NG + 意味判定 verdicts.tsv）を通過した視聴・保存をチャンネルごとに
畳み込み、watch_map.tsv に一覧化する。後から grep して「いつ誰を追いかけていたか」を
引く索引。登録だけして視聴/保存の無いチャンネルも subscribed=1 で載せる。

**地図に載せるのは意味判定に掛けた母集団だけ**（2回以上出てくるチャンネル＋登録チャンネル。
youtube_screen.py --candidates と同じ条件）。検索履歴の地図は1回きりの語も残すが、YouTube は
1回きりのチャンネルが5千件超あり意味判定に回していないので、件数の内訳にだけ数えて地図には出さない。

使い方:
    python3 scripts/youtube_map.py [--dry-run]

出力:
    youtube-archive/watch_map.tsv
      列: channel, count, watch, later, playlist, music, subscribed, top_category, first, last, years
        count    … watch + later + playlist の延べ件数
        watch    … 視聴履歴（**直近5か月ぶんしか無い**）
        later    … 「後で見る」系の再生リストへの保存（＝見たかった）
        playlist … それ以外の自作再生リストへの保存（＝残したかった）
        music    … うち YouTube Music での再生
        years    … 年:件数 をカンマ区切り
    標準エラーに件数の内訳（本文＝チャンネル名は出さない）
"""
import sys
import datetime as dt
from collections import Counter

from google_activity_parse import load_ng_patterns, is_blocked, load_verdicts
from youtube_parse import parse, aggregate, load_subscriptions, VERDICTS_PATH
from youtube_screen import DEFAULT_MIN as MIN_COUNT

OUT = "youtube-archive/watch_map.tsv"


def _date(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%Y/%m/%d") if ts else ""


def main():
    dry = "--dry-run" in sys.argv[1:]

    events, stats = parse()
    if stats["watch"] == 0 and stats["playlist"] == 0:
        sys.exit("データが見つかりません: youtube-archive/_raw/ に展開しましたか？"
                 "（scripts/youtube_extract.py --unpack <zip>）")
    agg = aggregate(events)

    # 登録チャンネル（NG / drop を通過したものだけ）
    ng, dropped = load_ng_patterns(), load_verdicts(VERDICTS_PATH)
    subs = [(cid, name) for cid, name in load_subscriptions()
            if not is_blocked(name, ng) and name not in dropped]
    sub_keys = set()
    for cid, name in subs:
        key = cid or name
        sub_keys.add(key)
        if key not in agg:
            agg[key] = {"name": name, "count": 0, "watch": 0, "later": 0, "playlist": 0,
                        "music": 0, "first": 0, "last": 0, "years": Counter(),
                        "categories": Counter()}

    e = sys.stderr
    print(f"視聴履歴: {stats['watch']:,} 件 / 再生リスト: {stats['playlist']:,} 件", file=e)
    print(f"  未解決（resolve 前）: {stats['unresolved']:,} / 削除・非公開: {stats['missing']:,}", file=e)
    print(f"機械式NG 除外: {stats['ng_removed']:,} / 意味判定 drop 除外: {stats['verdict_removed']:,}", file=e)
    print(f"残存（延べ）: {stats['kept']:,}", file=e)
    print(f"チャンネル数: {len(agg):,}（うち登録 {len(sub_keys):,}・2回以上 "
          f"{sum(1 for a in agg.values() if a['count'] >= 2):,}）", file=e)
    by_year = Counter()
    for a in agg.values():
        by_year.update(a["years"])
    print("年ごとの延べ件数:", file=e)
    for y in sorted(by_year):
        print(f"  {y}: {by_year[y]:,}", file=e)

    if dry:
        print(f"地図に載る見込み: {sum(1 for k, a in agg.items() if a['count'] >= MIN_COUNT or k in sub_keys):,}", file=e)
        print("(--dry-run: 書き出しはしていません)", file=e)
        return

    rows = [(k, a) for k, a in agg.items() if a["count"] >= MIN_COUNT or k in sub_keys]
    rows.sort(key=lambda kv: (-kv[1]["count"], kv[1]["name"]))
    print(f"地図に載せるチャンネル: {len(rows):,}（{MIN_COUNT}回以上 or 登録。"
          f"1回きり {len(agg) - len(rows):,} は内訳のみ）", file=e)
    with open(OUT, "w", encoding="utf-8") as w:
        w.write("channel\tcount\twatch\tlater\tplaylist\tmusic\tsubscribed\t"
                "top_category\tfirst\tlast\tyears\n")
        for key, a in rows:
            name = a["name"].replace("\t", " ")
            top = a["categories"].most_common(1)[0][0] if a["categories"] else ""
            years = ",".join(f"{y}:{c}" for y, c in sorted(a["years"].items()))
            w.write(f"{name}\t{a['count']}\t{a['watch']}\t{a['later']}\t{a['playlist']}\t"
                    f"{a['music']}\t{int(key in sub_keys)}\t{top}\t{_date(a['first'])}\t"
                    f"{_date(a['last'])}\t{years}\n")
    print(f"\n一覧を書き出しました: {OUT}（{len(rows):,} 行）", file=e)


if __name__ == "__main__":
    main()
