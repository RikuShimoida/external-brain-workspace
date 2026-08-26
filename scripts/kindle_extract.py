#!/usr/bin/env python3
"""Kindle のハイライトを1冊1 Markdown に書き出す。

books スキルが相談時に読む「本人が線を引いた箇所」の実体。
volumes/*.md（一般公開の書評から再構成した要約）が "本が何を言ったか" なのに対し、
こちらは "オーナーが何に反応したか" を持つ。

閾値で間引かない。ハイライトは読みながら本人が既に選び終えた文なので、
こちらでさらに選別すると本人の選択を上書きしてしまう。

**このリポジトリは公開されている。** 出力先の kindle-archive/ は .gitignore 済みで、
書籍本文の逐語がここから外に出ることはない。volumes/ 側にはポインタしか書かないこと。

使い方:
    python3 scripts/kindle_extract.py [--dry-run] [--input パス] [--outdir パス] [--title 部分一致]
      --dry-run … 書き出さず対象の冊数・件数だけ表示
      --input   … ハイライト JSON（既定: kindle-archive/highlights.json）
      --outdir  … 出力先（既定: kindle-archive/books）
      --title   … 書名の部分一致で絞る

出力:
    kindle-archive/books/<書名>_<ASIN>.md
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kindle_parse import INPUT, filename, load

OUTDIR = "kindle-archive/books"


def render(book, exported_at):
    """1冊ぶんの Markdown を組み立てる。"""
    lines = [
        "---",
        f"title: {book.title}",
        f"author: {book.author}",
        f"asin: {book.asin}",
        f"highlights: {len(book.highlights)}",
        f"notes: {book.num_notes}",
        "---",
        "",
        f"# {book.title}",
        "",
        f"> オーナーが Kindle で実際に線を引いた箇所。{len(book.highlights)} 件"
        f"（うち自分のメモ付き {book.num_notes} 件）。",
        "> 書籍本文の引用にあたるため、Podcast / note / ツイートで使うときは"
        "引用の範囲（主従・出典明記）に注意すること。",
        "",
    ]
    for i, h in enumerate(book.highlights, 1):
        where = " / ".join(x for x in (f"位置 {h.location}" if h.location else "",
                                       f"p.{h.page}" if h.page else "",
                                       h.color) if x)
        lines.append(f"## {i}." + (f"（{where}）" if where else ""))
        lines.append("")
        lines.append(f"> {h.text}")
        lines.append("")
        if h.note:
            lines.append(f"**本人のメモ:** {h.note}")
            lines.append("")
    if exported_at:
        lines.append(f"<!-- エクスポート: {exported_at} / docs/kindle-export.md -->")
    return "\n".join(lines) + "\n"


def main():
    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    path = INPUT
    outdir = OUTDIR
    title_filter = None
    if "--input" in argv:
        path = argv[argv.index("--input") + 1]
    if "--outdir" in argv:
        outdir = argv[argv.index("--outdir") + 1]
    if "--title" in argv:
        title_filter = argv[argv.index("--title") + 1]

    books, failed, exported_at = load(path)
    if title_filter:
        books = [b for b in books if title_filter in b.title]
    if not books:
        sys.exit("対象の本がありません。")

    total_h = sum(len(b.highlights) for b in books)
    if dry:
        print(f"[dry-run] {len(books):,} 冊 / ハイライト {total_h:,} 件 を書き出します → {outdir}/")
        for b in books[:20]:
            print(f"  {len(b.highlights):4d} 件  {filename(b)}")
        if len(books) > 20:
            print(f"  … 他 {len(books) - 20} 冊")
        return

    os.makedirs(outdir, exist_ok=True)
    written = 0
    for b in books:
        with open(os.path.join(outdir, filename(b)), "w", encoding="utf-8") as w:
            w.write(render(b, exported_at))
        written += 1

    print(f"書き出し: {written:,} 冊 / ハイライト {total_h:,} 件 → {outdir}/")
    if failed:
        print(f"⚠️ 取得に失敗した本が {len(failed)} 冊あります（取りこぼし）。"
              f"docs/kindle-export.md の「取りこぼしたとき」を参照。")


if __name__ == "__main__":
    main()
