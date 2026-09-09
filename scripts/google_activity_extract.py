#!/usr/bin/env python3
"""Google の検索履歴から、濃い「関心の塊」だけを本文（＝検索語一覧）に抽出する。

会話ではなく「検索語＋回数＋時刻」なので、LINE/Instagram の「日×相手の会話」ではなく
**頻度重視**で束ねる。THRESHOLD 回以上くり返した検索語（＝一過性でなく本当に関心を
持ったこと）だけを、年ごと（既定）または全期間の頻度上位で Markdown 化する。
1回きりの検索は search_map.tsv には残すが deep には出さない（ノイズを持ち込まない）。

安全: 二段フィルタ（機械式NG + 意味判定 verdicts.tsv）を通過した語だけを扱う。
セ ンシティブ語は parse の時点で落ちているので、ここには出てこない前提。

Takeout zip の展開ヘルパも兼ねる（検索カテゴリの1 JSON だけを _raw/ に取り出す）:

    python3 scripts/google_activity_extract.py --unpack ~/Downloads/takeout-*.zip
      → google-activity-archive/_raw/マイアクティビティ.json を作る（zip 自体は残す）

抽出:
    python3 scripts/google_activity_extract.py [閾値] [--dry-run] [--by year|freq]
      閾値      … 検索回数の下限。既定 2（＝2回以上）
      --dry-run … 書き出さず対象だけ表示（本文＝検索語は伏せて件数のみ）
      --by      … year（年ごと・既定）/ freq（全期間の頻度上位1枚）

出力:
    google-activity-archive/deep/interests_YYYY.md  … 年ごとの頻度上位（--by year）
    google-activity-archive/deep/top_queries.md      … 全期間の頻度上位（--by freq）
"""
import os
import sys
import zipfile
import datetime as dt
from collections import defaultdict

from google_activity_parse import parse, aggregate, BASE

OUTDIR = "google-activity-archive/deep"
THRESHOLD = 2
# zip 内の検索カテゴリ JSON のファイル名（末尾一致で探す）。
SEARCH_JSON_BASENAME = "マイアクティビティ.json"
SEARCH_CATEGORY = "検索"


def _uname(info):
    """zip エントリ名を正しい UTF-8 に直す。

    Takeout の zip は日本語ファイル名を UTF-8 で書くが、汎用フラグ 0x800 が立って
    いない実装では cp437 として読まれ文字化けする。立っていればそのまま UTF-8。
    """
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def unpack(zip_path, out_dir=BASE):
    """Takeout zip から検索カテゴリの JSON だけを out_dir に取り出す。

    zip 全体は展開しない（サムネ等のノイズを持ち込まない）。検索カテゴリの
    マイアクティビティ.json を1本だけ out_dir 直下に書く。
    """
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        target = None
        for info in z.infolist():
            if info.is_dir():
                continue
            name = _uname(info)
            # 「マイ アクティビティ/検索/マイアクティビティ.json」を狙う
            if name.endswith(SEARCH_JSON_BASENAME) and f"/{SEARCH_CATEGORY}/" in name:
                target = info
                break
        if target is None:
            sys.exit(f"検索カテゴリの {SEARCH_JSON_BASENAME} が zip 内に見つかりません: {zip_path}")
        dest = os.path.join(out_dir, SEARCH_JSON_BASENAME)
        with z.open(target) as src, open(dest, "wb") as dst:
            dst.write(src.read())
    print(f"展開しました: {dest}")
    return dest


def _write_year(agg, threshold):
    """年ごとに、閾値以上くり返した検索語を回数降順で書く。"""
    # 年 → [(text, count)]。語は「その語が出た年すべて」に計上する
    by_year = defaultdict(list)
    for text, a in agg.items():
        if a["count"] < threshold:
            continue
        for y in sorted(a["years"]):
            by_year[y].append((text, a["count"]))
    files = 0
    for y, rows in sorted(by_year.items()):
        rows.sort(key=lambda r: (-r[1], r[0]))
        fname = f"{OUTDIR}/interests_{y}.md"
        with open(fname, "w", encoding="utf-8") as w:
            w.write(f"# {y} 年の関心（{threshold}回以上くり返した検索・{len(rows)}語）\n\n")
            w.write("| 検索語 | 回数 |\n|---|---|\n")
            for text, cnt in rows:
                # | をエスケープして表崩れを防ぐ
                safe = text.replace("|", "\\|")
                w.write(f"| {safe} | {cnt} |\n")
        files += 1
    return files


def _write_freq(agg, threshold):
    """全期間の頻度上位を1枚に書く。"""
    rows = [(t, a["count"]) for t, a in agg.items() if a["count"] >= threshold]
    rows.sort(key=lambda r: (-r[1], r[0]))
    fname = f"{OUTDIR}/top_queries.md"
    with open(fname, "w", encoding="utf-8") as w:
        w.write(f"# くり返した検索（全期間・{threshold}回以上・{len(rows)}語）\n\n")
        w.write("| 検索語 | 回数 |\n|---|---|\n")
        for text, cnt in rows:
            safe = text.replace("|", "\\|")
            w.write(f"| {safe} | {cnt} |\n")
    return 1


def main():
    argv = sys.argv[1:]

    # --unpack: zip 展開モード（抽出はしない）
    if "--unpack" in argv:
        i = argv.index("--unpack")
        zip_path = os.path.expanduser(argv[i + 1])
        unpack(zip_path)
        return

    dry = "--dry-run" in argv
    if dry:
        argv.remove("--dry-run")
    by = "year"
    if "--by" in argv:
        i = argv.index("--by")
        by = argv[i + 1]
        del argv[i : i + 2]
    nums = [a for a in argv if not a.startswith("--")]
    threshold = int(nums[0]) if nums else THRESHOLD

    queries, stats = parse()
    if not queries:
        sys.exit("検索語が見つかりません: _raw/ に展開しましたか？（--unpack で展開）")
    agg = aggregate(queries)

    n_repeat = sum(1 for a in agg.values() if a["count"] >= threshold)
    print(f"閾値 {threshold} 回以上の検索語: {n_repeat:,} 語")

    if dry:
        # 本文（検索語）は出さず、件数だけ。年別の内訳のみ表示する。
        by_year = defaultdict(int)
        for a in agg.values():
            if a["count"] >= threshold:
                for y in a["years"]:
                    by_year[y] += 1
        for y in sorted(by_year):
            print(f"  {y}: {by_year[y]:,} 語")
        return

    os.makedirs(OUTDIR, exist_ok=True)
    files = _write_year(agg, threshold) if by == "year" else _write_freq(agg, threshold)
    print(f"{files} ファイルを {OUTDIR}/ に書き出しました（--by {by}）。")


if __name__ == "__main__":
    main()
