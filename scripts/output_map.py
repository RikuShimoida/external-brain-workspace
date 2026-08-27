#!/usr/bin/env python3
"""このリポジトリ自身が貯めた生成物（Podcast ネタ / ツイート下書き / note 下書き /
判断ログ）を走査し、「既出ネタの地図」を TSV で書き出す。

同じネタを何度も提案する事故を防ぐのが目的（Issue #14）。
各スキルは提案の前にこの地図を読み、既出とかぶっていないかを確かめる。

**突き合わせのキーは引用本文である。** 生成物にはツイート ID が残っていないため
（出典は `（X, 2022-11）` のような年月表記だけ）、ID では突き合わせられない。

**先頭一致では足りない。** 同じツイートでも、Podcast ネタでは要約されて
「スマート＝仕事ができるという認識が3年目まであった」、ツイート下書きでは逐語で
「スマートである＝仕事ができる という認識が社会人3年目くらいまではあった」と
書かれる。先頭も末尾もズレるので、**文字 N-gram の重なり**で突き合わせる。
2026-08-27 時点の生成物 8 ファイル・引用 63 件に対し、この方式で既出の重複が
4 組見つかった（先頭一致では 0 組しか見つからなかった）。

**機械で拾えるのは「同じ引用」まで。** 別の引用で同じテーマを語っている重複は
`label` 列を読んで LLM 側が判断する。地図＋深掘りの2段構えは他のソースと同じ。

使い方:
    python3 scripts/output_map.py                      # outputs-archive/output_map.tsv を作り直す
    python3 scripts/output_map.py --dry-run            # 書き込まず標準出力に出す
    python3 scripts/output_map.py --match "<引用本文>"  # この引用が既出かを地図に問い合わせる
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 走査対象と、地図に載せるときの種別名
TARGET_DIRS = {
    "podcast-ideas": "podcast",
    "tweet-drafts": "tweet",
    "note-drafts": "note",
    "decisions": "decision",
}

OUT_REL = Path("outputs-archive") / "output_map.tsv"

# 出典アンカー。この4系統に紐づく引用だけを拾う。
# note 下書きの本文中にも `>` の引用は出てくるが、それは記事の一部であって
# 既出ネタの出典ではないので、アンカー方式で明確に切り分ける。
ANCHOR_RE = re.compile(r"\*\*(?:出典|根拠の投稿[^*]*|元の言葉)\*\*")
# 判断ログ（decisions/）は引用の次の行に `> —（出典: ノート「…」）` が来る
INLINE_SOURCE_RE = re.compile(r"（出典[:：]")

BULLET_QUOTE_RE = re.compile(r"^\s*[-*]\s*>\s?(.*)$")
BARE_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

# 引用の末尾に付く出典。`（X, 2020）`『（Evernote「…」）』『—（出典: ノート「…」）』
TRAIL_SOURCE_RE = re.compile(
    r"[（(]\s*(?:出典[:：]\s*)?((?:X|Ｘ|Evernote|ノート|本人|習慣)[^（）()]*)[）)]\s*$"
)
ANY_PAREN_RE = re.compile(r"[（(]([^（）()]+)[）)]")

# 正規化で落とす記号。表記ゆれ・引用符・省略記号の有無で取りこぼさないため。
STRIP_CHARS = set("「」『』\"'“”‘’…・、。，．,.!?！？〜~()（）［］[]｛｝{}　 \t-–—―:：;；/／\\|｜＝=→←↑↓")

POSTED_RE = re.compile(r"✅\s*投稿済み")
# `## 1. ラベル（テーマ: …）✅ 投稿済み（…）` から表示用のラベルだけ取り出す
LABEL_CLEAN_RE = re.compile(r"^\s*(?:\d+[.)]|[A-Z][.)])\s*")
# `## 1. …` `### A. …` のような連番見出し＝ネタ1件ぶんの区切り
NUMBERED_RE = re.compile(r"^\s*(?:\d+[.)]|[A-Z][.)])\s")

KEY_LEN = 24
NGRAM = 8
# 同じ素材とみなす閾値。短いほうの N-gram のうち何割が共有されているか。
MATCH_THRESHOLD = 0.35

COLUMNS = ["kind", "file", "date", "label", "status", "source", "key", "quote"]


def normalize(text: str) -> str:
    """引用本文を突き合わせ用に正規化する（出典と記号と空白を落とす）。"""
    body = TRAIL_SOURCE_RE.sub("", text)
    return "".join(c for c in body if c not in STRIP_CHARS)


def grams(norm: str, n: int = NGRAM) -> set[str]:
    if len(norm) <= n:
        return {norm} if norm else set()
    return {norm[i:i + n] for i in range(len(norm) - n + 1)}


def similarity(a: str, b: str) -> float:
    """短いほうを基準にした包含率。要約・省略で長さが変わっても効くようにする。"""
    ga, gb = grams(a), grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / min(len(ga), len(gb))


def extract_source(quote: str, anchor_line: str) -> str:
    """引用の末尾から出典を取る。無ければアンカー行の括弧書きにフォールバックする。"""
    m = TRAIL_SOURCE_RE.search(quote)
    if m:
        return m.group(1).strip()
    m = ANY_PAREN_RE.search(anchor_line)
    if m:
        return m.group(1).strip()
    return ""


def clean_label(heading: str) -> str:
    label = POSTED_RE.split(heading)[0]
    return LABEL_CLEAN_RE.sub("", label).strip()


def flatten(text: str) -> str:
    """TSV に載せるため、タブと改行を潰す。"""
    return re.sub(r"\s+", " ", text).strip()


def split_block(block: list[tuple[bool, str]]) -> list[str]:
    """引用ブロックを個々の引用に割る。

    `- > …` は1行1引用、`> …` の連続は1つの引用の折り返しとして連結する。
    末尾だけの出典行（`> —（出典: …）`）は直前の引用にくっつける。
    """
    quotes: list[str] = []
    pending: list[str] = []
    for is_bullet, text in block:
        if is_bullet:
            if pending:
                quotes.append(" ".join(pending))
                pending = []
            quotes.append(text)
        else:
            pending.append(text)
    if pending:
        quotes.append(" ".join(pending))

    # 本文が空（出典しか無い）の断片は、直前の引用に併合する
    merged: list[str] = []
    for q in quotes:
        if not normalize(q) and merged:
            merged[-1] = f"{merged[-1]} {q}".strip()
        elif normalize(q):
            merged.append(q)
    return merged


def parse_file(path: Path, kind: str, rel: str) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    date_m = DATE_RE.search(path.name)
    date = date_m.group(1) if date_m else ""

    rows: list[dict] = []
    # 見出しは3種類が混ざる。1ファイル1判断の判断ログは `# 題`、ネタ/下書きは
    # `## 1. ラベル` の連番見出しが1件ぶんの区切り、note 下書きはさらに記事本文の
    # 見出し（連番なし）が同じレベルで挟まる。連番を優先しないと本文の見出しに
    # ラベルを奪われる。
    title = numbered = last_heading = ""
    prev_anchor = ""   # 直前の行がアンカーだったなら、その行を覚えておく

    def current_heading() -> str:
        if kind == "decision":
            return title          # 判断ログは1ファイル1判断。題がそのままラベル
        return numbered or last_heading or title

    i = 0
    while i < len(lines):
        line = lines[i]

        hm = HEADING_RE.match(line)
        if hm:
            level, text = len(hm.group(1)), hm.group(2)
            if level == 1:
                title, numbered, last_heading = text, "", ""
            elif NUMBERED_RE.match(text):
                numbered = last_heading = text
            else:
                last_heading = text
            prev_anchor = ""
            i += 1
            continue

        # `- **出典**: > 引用 （X, 2022-11）` … アンカーと引用が同じ行
        if ANCHOR_RE.search(line) and ">" in line:
            block = [(True, line.split(">", 1)[1].strip())]
            anchor_line = line
            nxt = i + 1
        # 引用ブロックの始まり
        elif BULLET_QUOTE_RE.match(line) or BARE_QUOTE_RE.match(line):
            block = []
            j = i
            while j < len(lines):
                m = BULLET_QUOTE_RE.match(lines[j])
                if m:
                    block.append((True, m.group(1).strip()))
                    j += 1
                    continue
                m = BARE_QUOTE_RE.match(lines[j])
                if m:
                    block.append((False, m.group(1).strip()))
                    j += 1
                    continue
                break
            anchor_line = prev_anchor
            nxt = j
            # アンカーに紐づくか、ブロック自身が出典を名乗るときだけ採用する。
            # これが note 本文中の引用を弾いている唯一の条件。
            has_source = any(INLINE_SOURCE_RE.search(t) for _, t in block)
            if not prev_anchor and not has_source:
                prev_anchor = ""
                i = nxt
                continue
        else:
            prev_anchor = line if ANCHOR_RE.search(line) else ""
            i += 1
            continue

        head = current_heading()
        for q in split_block(block):
            rows.append({
                "kind": kind,
                "file": rel,
                "date": date,
                "label": flatten(clean_label(head)),
                "status": "posted" if POSTED_RE.search(head) else "draft",
                "source": flatten(extract_source(q, anchor_line)),
                "key": normalize(q)[:KEY_LEN],
                "quote": flatten(q),
            })
        prev_anchor = ""
        i = max(nxt, i + 1)

    return rows


def build_rows(root: Path) -> tuple[list[dict], dict[str, tuple[int, int]]]:
    rows: list[dict] = []
    per_dir: dict[str, tuple[int, int]] = {}
    for dirname, kind in TARGET_DIRS.items():
        d = root / dirname
        if not d.exists():
            print(f"! {dirname} が無いのでスキップ", file=sys.stderr)
            per_dir[dirname] = (0, 0)
            continue
        files = sorted(d.glob("*.md"))
        before = len(rows)
        for f in files:
            rows.extend(parse_file(f, kind, f"{dirname}/{f.name}"))
        per_dir[dirname] = (len(files), len(rows) - before)
    rows.sort(key=lambda r: (r["kind"], r["date"], r["label"], r["key"]))
    return rows, per_dir


def find_dupes(rows: list[dict]) -> list[list[dict]]:
    """同じ素材が複数の生成物に出ている組を、N-gram の重なりで探す。"""
    norms = [normalize(r["quote"]) for r in rows]
    parent = list(range(len(rows)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a in range(len(rows)):
        for b in range(a + 1, len(rows)):
            if similarity(norms[a], norms[b]) >= MATCH_THRESHOLD:
                parent[find(a)] = find(b)

    groups: dict[int, list[dict]] = {}
    for idx, r in enumerate(rows):
        groups.setdefault(find(idx), []).append(r)
    # 複数ファイルにまたがるものだけが「既出の重複」
    return [g for g in groups.values() if len({r["file"] for r in g}) > 1]


def run_match(rows: list[dict], query: str) -> int:
    qn = normalize(query)
    hits = sorted(
        ((similarity(qn, normalize(r["quote"])), r) for r in rows),
        key=lambda t: t[0], reverse=True,
    )
    hits = [(s, r) for s, r in hits if s >= MATCH_THRESHOLD]
    if not hits:
        print("既出なし（この引用は過去の生成物に出ていない）")
        return 0
    print(f"既出あり: {len(hits)} 件")
    for s, r in hits:
        print(f"  [{s:.2f}] {r['kind']}/{r['status']}  {r['file']}")
        print(f"        テーマ: {r['label']}")
        print(f"        引用: {r['quote'][:80]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."),
                    help="リポジトリのルート（既定: カレント）")
    ap.add_argument("--out", type=Path, default=None,
                    help=f"出力先（既定: {OUT_REL}）")
    ap.add_argument("--dry-run", action="store_true",
                    help="書き込まず標準出力に出す")
    ap.add_argument("--match", metavar="引用本文",
                    help="この引用が既出かを地図に問い合わせる（書き込まない）")
    args = ap.parse_args()

    root: Path = args.root
    rows, per_dir = build_rows(root)

    if args.match:
        return run_match(rows, args.match)

    body = "\t".join(COLUMNS) + "\n"
    body += "".join("\t".join(r[c] for c in COLUMNS) + "\n" for r in rows)

    out: Path = args.out or (root / OUT_REL)
    if args.dry_run:
        sys.stdout.write(body)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding="utf-8")

    for dirname, (nf, nq) in per_dir.items():
        print(f"{dirname}: {nf} ファイル / 引用 {nq} 件", file=sys.stderr)
    print(f"合計 {len(rows)} 件", file=sys.stderr)

    dupes = find_dupes(rows)
    if dupes:
        print(f"\n既出の重複 {len(dupes)} 組（同じ素材が複数の生成物にある）:", file=sys.stderr)
        for g in dupes:
            print(f"  - {g[0]['quote'][:50]}…", file=sys.stderr)
            for r in g:
                print(f"      {r['file']}（{r['label']} / {r['status']}）", file=sys.stderr)
    else:
        print("\n既出の重複: なし", file=sys.stderr)

    if not args.dry_run:
        print(f"\n→ {out} に {len(rows)} 件を書き出しました", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
