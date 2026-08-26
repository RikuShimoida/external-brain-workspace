#!/usr/bin/env python3
"""Kindle のハイライトから「地図」を作る。

1行=1冊で (書名・著者・ASIN・ハイライト数・メモ数・総文字数・最長) だけを一覧化する。
どの本に濃く線を引いたかを眺めて、books スキルのどの巻に効くかを当たりを付けるための下ごしらえ。

他のソース（ChatGPT / LINE / Claude Code ログ）と違い、ハイライトは
**オーナーが読みながら既に選び終えた文**なので、ここで濃さの閾値を切って捨てることはしない。
地図は全冊ぶん作り、本文も全冊ぶん取る（kindle_extract.py）。

使い方:
    python3 scripts/kindle_map.py [--input パス] [--out パス]
      --input … ハイライト JSON（既定: kindle-archive/highlights.json）
      --out   … 出力先 TSV（既定: kindle-archive/book_map.tsv）

出力:
    kindle-archive/book_map.tsv  … 1行=1冊（ハイライトの多い順）
    標準出力に冊数・総ハイライト数・上位などのサマリ
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kindle_parse import INPUT, clean, load

OUT = "kindle-archive/book_map.tsv"


def main():
    argv = sys.argv[1:]
    path = INPUT
    out = OUT
    if "--input" in argv:
        path = argv[argv.index("--input") + 1]
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]

    books, failed, exported_at = load(path)
    if not books:
        sys.exit(f"ハイライトのある本がありません: {path}")

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as w:
        w.write("title\tauthor\tasin\thighlights\tnotes\tchars\tlongest\n")
        for b in books:
            w.write(
                f"{clean(b.title)}\t{clean(b.author)}\t{b.asin}"
                f"\t{len(b.highlights)}\t{b.num_notes}\t{b.chars}\t{b.longest}\n"
            )

    total_h = sum(len(b.highlights) for b in books)
    total_n = sum(b.num_notes for b in books)
    total_c = sum(b.chars for b in books)
    print(f"ハイライトのある本: {len(books):,} 冊")
    print(f"ハイライト総数: {total_h:,} 件（うち自分のメモ付き {total_n:,} 件）")
    print(f"総文字数: {total_c:,} 字")
    if exported_at:
        print(f"エクスポート日時: {exported_at}")
    print(f"→ {out}")

    print("\n濃い本 上位10冊:")
    for b in books[:10]:
        print(f"  {len(b.highlights):4d} 件  {b.title}")

    if failed:
        print(f"\n⚠️ 取得に失敗した本が {len(failed)} 冊あります（取りこぼし）:")
        for f in failed[:20]:
            print(f"  {clean(f.get('title')) or f.get('asin')} … {clean(f.get('reason'))}")
        print("  docs/kindle-export.md の「取りこぼしたとき」を参照してください。")


if __name__ == "__main__":
    main()
