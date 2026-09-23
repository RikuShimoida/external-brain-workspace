#!/usr/bin/env python3
"""YouTube から、年ごとの「好みの塊」（くり返し出てくるチャンネル）を Markdown に抽出する。

地図（watch_map.tsv）は全チャンネルを残すが、deep は THRESHOLD 件以上その年に出てきた
チャンネルだけ（＝一過性でなく本当に追いかけていた相手）。年ごとに、上位カテゴリの
内訳と、チャンネル一覧（視聴／後で見る／保存 の内訳つき）を書く。
動画タイトルは deep に出さない（意味判定に掛けているのはチャンネル名だけのため）。

Takeout zip の展開ヘルパも兼ねる:

    python3 scripts/youtube_extract.py --unpack ~/Downloads/takeout-*.zip
      → youtube-archive/_raw/ に watch-history.json・登録チャンネル.csv・再生リスト/*.csv
        だけを取り出す（本人アップロード動画の mp4 などは取り出さない。zip 自体は残す）

抽出:
    python3 scripts/youtube_extract.py [閾値] [--dry-run]
      閾値 … その年の件数の下限。既定 3

出力:
    youtube-archive/deep/taste_YYYY.md
"""
import os
import sys
import zipfile
from collections import Counter, defaultdict

from google_activity_extract import _uname
from youtube_parse import parse, aggregate, BASE

OUTDIR = "youtube-archive/deep"
THRESHOLD = 3
_ROOT = "YouTube と YouTube Music/"
# zip 内パス（_ROOT 以降）→ _raw/ 以下の置き場所
_WANT = {
    "履歴/watch-history.json": "watch-history.json",
    "登録チャンネル/登録チャンネル.csv": "登録チャンネル.csv",
}
_PLAYLIST = "再生リスト/"


def unpack(zip_path, out_dir=BASE):
    n = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            name = _uname(info)
            if _ROOT not in name:
                continue
            rel = name.split(_ROOT, 1)[1]
            if rel in _WANT:
                dest = os.path.join(out_dir, _WANT[rel])
            elif rel.startswith(_PLAYLIST) and rel.endswith(".csv"):
                dest = os.path.join(out_dir, rel)
            else:
                continue  # mp4・コメント・検索履歴などは取り出さない
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as dst:
                dst.write(src.read())
            n += 1
    if n == 0:
        sys.exit(f"「{_ROOT}」配下が zip 内に見つかりません: {zip_path}")
    print(f"{n} ファイルを {out_dir}/ に取り出しました。")


def _by_year(events, threshold):
    """{year: [(name, total, watch, later, playlist, top_category)]}, {year: Counter(category)}"""
    per = defaultdict(lambda: defaultdict(Counter))  # year → key → Counter(source/cat)
    names = {}
    cats = defaultdict(Counter)
    import datetime as dt
    for e in events:
        if not e.ts:
            continue
        y = dt.datetime.fromtimestamp(e.ts).strftime("%Y")
        key = e.channel_id or e.channel
        names[key] = e.channel
        c = per[y][key]
        c["total"] += 1
        c[e.source] += 1
        if e.category:
            c["cat:" + e.category] += 1
            cats[y][e.category] += 1
    out = {}
    for y, chans in per.items():
        rows = []
        for key, c in chans.items():
            if c["total"] < threshold:
                continue
            top = max((k for k in c if k.startswith("cat:")), key=lambda k: c[k], default="")
            rows.append((names[key], c["total"], c["watch"], c["later"], c["playlist"], top[4:]))
        rows.sort(key=lambda r: (-r[1], r[0]))
        out[y] = rows
    return out, cats


def main():
    argv = sys.argv[1:]
    if "--unpack" in argv:
        unpack(os.path.expanduser(argv[argv.index("--unpack") + 1]))
        return

    dry = "--dry-run" in argv
    nums = [a for a in argv if not a.startswith("--")]
    threshold = int(nums[0]) if nums else THRESHOLD

    events, _ = parse()
    if not events:
        sys.exit("データが見つかりません: --unpack と youtube_resolve.py を先に実行しましたか？")
    by_year, cats = _by_year(events, threshold)

    for y in sorted(by_year):
        print(f"  {y}: {len(by_year[y]):,} チャンネル（{threshold}件以上）")
    if dry:
        return

    os.makedirs(OUTDIR, exist_ok=True)
    for y, rows in sorted(by_year.items()):
        with open(f"{OUTDIR}/taste_{y}.md", "w", encoding="utf-8") as w:
            w.write(f"# {y} 年の YouTube（{threshold}件以上出てきたチャンネル・{len(rows)}件）\n\n")
            w.write("視聴＝視聴履歴（2026年4月以降のみ）／後で見る＝見たかった／保存＝自作の再生リストに残した\n\n")
            if cats[y]:
                total = sum(cats[y].values())
                w.write("## カテゴリの内訳（保存した動画）\n\n")
                w.write("| カテゴリ | 件数 | 割合 |\n|---|---|---|\n")
                for cat, n in cats[y].most_common(10):
                    w.write(f"| {cat} | {n} | {n * 100 // total}% |\n")
                w.write("\n")
            w.write("## チャンネル\n\n| チャンネル | 計 | 視聴 | 後で見る | 保存 | 主なカテゴリ |\n"
                    "|---|---|---|---|---|---|\n")
            for name, tot, wa, la, pl, cat in rows:
                safe = name.replace("|", "\\|")
                w.write(f"| {safe} | {tot} | {wa} | {la} | {pl} | {cat} |\n")
    print(f"{len(by_year)} ファイルを {OUTDIR}/ に書き出しました。")


if __name__ == "__main__":
    main()
