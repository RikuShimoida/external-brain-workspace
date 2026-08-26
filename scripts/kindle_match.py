#!/usr/bin/env python3
"""Kindle のハイライトと books スキルの56冊を書名で突き合わせる。

どの volumes/*.md に「本人が線を引いた箇所」へのポインタを足せるかを出す。
書名は Kindle 側（Amazon の商品名）と volumes 側（Evernote 由来）で表記が揺れるので、
全半角・副題・記号を落として比較し、完全一致→部分一致の順で拾う。

**自動でファイルを書き換えない。** 突き合わせの結果を出すだけで、
volumes/ をどう更新するかはオーナーの判断（1冊ずつ内容を見て決める）。

使い方:
    python3 scripts/kindle_match.py [--input パス] [--index パス]
      --input … ハイライト JSON（既定: kindle-archive/highlights.json）
      --index … books の索引（既定: .claude/skills/books/index.md）

出力:
    標準出力に3区分（両方にある / ハイライトのみ / volumes のみ）
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kindle_parse import INPUT, load, normalize_title

INDEX = ".claude/skills/books/index.md"


def load_index(path):
    """index.md の表から (書名, ファイル名) を拾う。"""
    if not os.path.exists(path):
        raise SystemExit(f"索引が見つかりません: {path}")
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 3:
                continue
            title, fname = cells[0], cells[1]
            # 見出し行と区切り行を弾く
            if not fname.endswith(".md") or set(title) <= set("-: "):
                continue
            rows.append((title, fname))
    if not rows:
        raise SystemExit(f"索引から本を読み取れませんでした: {path}")
    return rows


def main():
    argv = sys.argv[1:]
    path = INPUT
    index = INDEX
    if "--input" in argv:
        path = argv[argv.index("--input") + 1]
    if "--index" in argv:
        index = argv[argv.index("--index") + 1]

    books, _failed, _ = load(path)
    shelf = load_index(index)

    norm_shelf = [(normalize_title(t), t, f) for t, f in shelf]
    matched, kindle_only = [], []
    used = set()

    for b in books:
        nb = normalize_title(b.title)
        hit = None
        for ns, t, f in norm_shelf:
            if ns and ns == nb:
                hit = (t, f)
                break
        if not hit:  # 完全一致が無ければ、片方がもう片方を含む形で拾う
            for ns, t, f in norm_shelf:
                if ns and nb and (ns in nb or nb in ns):
                    hit = (t, f)
                    break
        if hit:
            matched.append((b, hit[0], hit[1]))
            used.add(hit[1])
        else:
            kindle_only.append(b)

    shelf_only = [(t, f) for t, f in shelf if f not in used]

    print(f"Kindle 側: {len(books)} 冊 / books 索引: {len(shelf)} 冊\n")

    print(f"■ 両方にある（volumes にポインタを足せる）: {len(matched)} 冊")
    for b, t, f in sorted(matched, key=lambda x: -len(x[0].highlights)):
        same = "" if normalize_title(b.title) == normalize_title(t) else f"  ※書名ゆれ: {b.title}"
        print(f"  {len(b.highlights):4d} 件  {t}  ({f}){same}")

    print(f"\n■ ハイライトはあるが volumes に無い: {len(kindle_only)} 冊")
    for b in kindle_only:
        print(f"  {len(b.highlights):4d} 件  {b.title}")

    print(f"\n■ volumes にあるがハイライトが無い: {len(shelf_only)} 冊")
    for t, f in shelf_only:
        print(f"        {t}  ({f})")


if __name__ == "__main__":
    main()
