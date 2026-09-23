#!/usr/bin/env python3
"""オーナーの話し言葉の「地図」と、数えられる特徴の集計を作る。

話し方プロファイル（speech_profile.md）は隔離エージェントが書くが、その材料と検算は
ここで機械的に作る。数えられるもの（フィラー・語尾・言い回し）はスクリプトで数え、
LLM には「数えた結果の解釈」と「実在する発言からの引用」だけをさせる（捏造防止）。

使い方:
    python3 scripts/voice_map.py [--dry-run]
    python3 scripts/voice_map.py --verify-profile   # プロファイルの引用がすべて実在するか照合

出力（voice-archive/ 配下）:
    speech_map.tsv        … 話し言葉1件=1行の索引（本文なし）
                            列: source, date, ref, chars, fillers
    deep/utterances.tsv   … 話し言葉の本文（プロファイルを書くときの材料・引用の照合先）
                            列: idx, source, date, ref, fillers, text（改行は " / "）
    features.md           … 集計（フィラーの頻度、語尾、話し言葉に特有の言い回し）
"""
import os
import re
import sys
import math
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from voice_parse import iter_all, FILLERS, FILLER_RE, one_line  # noqa: E402

OUT_DIR = "voice-archive"
MAP = f"{OUT_DIR}/speech_map.tsv"
UTTER = f"{OUT_DIR}/deep/utterances.tsv"
FEATURES = f"{OUT_DIR}/features.md"
PROFILE = f"{OUT_DIR}/speech_profile.md"

NGRAM = (3, 4, 5, 6)
NGRAM_MIN = 8       # 話し言葉側でこれ未満しか出ない言い回しは載せない（偶然を拾わない）
TOP = 40
# 語尾: 文の区切り（。！？!? 改行 / 「、」の直前）の手前2〜4文字
_END_SPLIT = re.compile(r"[。！？!?\n]|、")
_JA = re.compile(r"^[぀-ヿ一-鿿ー]+$")


def endings(text):
    out = Counter()
    for seg in _END_SPLIT.split(text):
        seg = seg.strip()
        if len(seg) < 6:
            continue
        for n in (2, 3, 4):
            tail = seg[-n:]
            if _JA.match(tail):
                out[tail] += 1
    return out


def ngrams(text):
    out = Counter()
    t = re.sub(r"\s+", "", text)
    for n in NGRAM:
        for i in range(len(t) - n + 1):
            g = t[i : i + n]
            if _JA.match(g):
                out[g] += 1
    return out


def _characteristic(spoken, written):
    """話し言葉側に偏る言い回し（対数オッズ比、加算スムージング）。"""
    s_tot, w_tot = sum(spoken.values()) or 1, sum(written.values()) or 1
    rows = []
    for g, c in spoken.items():
        if c < NGRAM_MIN:
            continue
        w = written.get(g, 0)
        score = math.log((c + 1) / s_tot) - math.log((w + 1) / w_tot)
        rows.append((score, g, c, w))
    rows.sort(reverse=True)
    # 長い言い回しに含まれる短い断片の重複を間引く
    picked = []
    for score, g, c, w in rows:
        if any(g in p[1] and c <= p[2] * 1.2 for p in picked):
            continue
        picked.append((score, g, c, w))
        if len(picked) >= TOP:
            break
    return picked


def build(dry):
    spoken, written = [], []
    for u in iter_all():
        (spoken if u.spoken else written).append(u)

    by_src = Counter(u.source for u in spoken)
    all_by_src = Counter(u.source for u in spoken + written)
    e = sys.stderr
    print("話し言葉と判定した発言 / 全発言（30字以上）:", file=e)
    for src in ("claude", "chatgpt", "evernote"):
        print(f"  {src}: {by_src[src]:,} / {all_by_src[src]:,}", file=e)
    s_chars = sum(len(u.text) for u in spoken)
    print(f"話し言葉の合計: {len(spoken):,} 件 / {s_chars:,} 字", file=e)
    if dry:
        print("(--dry-run: 書き出しはしていません)", file=e)
        return

    spoken.sort(key=lambda u: (u.date, u.source, u.ref))
    os.makedirs(f"{OUT_DIR}/deep", exist_ok=True)
    with open(MAP, "w", encoding="utf-8") as w:
        w.write("source\tdate\tref\tchars\tfillers\n")
        for u in spoken:
            w.write(f"{u.source}\t{u.date}\t{u.ref}\t{len(u.text)}\t{u.fillers}\n")
    with open(UTTER, "w", encoding="utf-8") as w:
        w.write("idx\tsource\tdate\tref\tfillers\ttext\n")
        for i, u in enumerate(spoken):
            w.write(f"{i}\t{u.source}\t{u.date}\t{u.ref}\t{u.fillers}\t{one_line(u.text)}\n")

    # --- 集計 ---
    fill = Counter()
    for u in spoken:
        fill.update(FILLER_RE.findall(u.text))
    w_chars = sum(len(u.text) for u in written) or 1
    w_fill = Counter()
    for u in written:
        w_fill.update(FILLER_RE.findall(u.text))
    s_end, w_end, s_ng, w_ng = Counter(), Counter(), Counter(), Counter()
    for u in spoken:
        s_end.update(endings(u.text))
        s_ng.update(ngrams(u.text))
    for u in written:
        w_end.update(endings(u.text))
        w_ng.update(ngrams(u.text))

    with open(FEATURES, "w", encoding="utf-8") as w:
        w.write("# 話し言葉の特徴（voice_map.py が機械集計）\n\n")
        w.write(f"- 話し言葉: {len(spoken):,} 件 / {s_chars:,} 字"
                f"（claude {by_src['claude']} / chatgpt {by_src['chatgpt']} / evernote {by_src['evernote']}）\n")
        w.write(f"- 比較対象の書き言葉: {len(written):,} 件 / {w_chars:,} 字"
                "（同じ Claude / ChatGPT への発言のうち話し言葉と判定されなかったもの）\n\n")
        w.write("## フィラー（1,000字あたり）\n\n| フィラー | 回数 | 話し言葉 /1000字 | 書き言葉 /1000字 |\n|---|---|---|---|\n")
        for f in FILLERS:
            if fill[f]:
                w.write(f"| {f} | {fill[f]} | {fill[f] * 1000 / s_chars:.1f} | {w_fill[f] * 1000 / w_chars:.1f} |\n")
        w.write("\n## 語尾（区切りの直前。話し言葉に偏るもの上位）\n\n| 語尾 | 話し言葉 | 書き言葉 |\n|---|---|---|\n")
        for _, g, c, wc in _characteristic(s_end, w_end)[:25]:
            w.write(f"| {g} | {c} | {wc} |\n")
        w.write("\n## 話し言葉に特有の言い回し（3〜6文字・対数オッズ比の上位）\n\n| 言い回し | 話し言葉 | 書き言葉 |\n|---|---|---|\n")
        for _, g, c, wc in _characteristic(s_ng, w_ng):
            w.write(f"| {g} | {c} | {wc} |\n")

    print(f"書き出しました: {MAP} / {UTTER} / {FEATURES}", file=e)


_QUOTE = re.compile(r"「([^「」]{6,})」")


def verify_profile():
    """プロファイル内の「…」引用（6字以上）が utterances.tsv の本文に実在するか照合する。"""
    if not os.path.exists(PROFILE):
        sys.exit(f"{PROFILE} がありません")
    norm = lambda s: re.sub(r"[\s/、。…]", "", s)
    with open(UTTER, encoding="utf-8") as f:
        f.readline()
        corpus = norm("".join(line.rstrip("\n").split("\t", 5)[5] for line in f))
    with open(PROFILE, encoding="utf-8") as f:
        quotes = _QUOTE.findall(f.read())
    missing = [q for q in quotes if norm(q) not in corpus]
    print(f"引用 {len(quotes)} 件中、実在しないもの {len(missing)} 件")
    for q in missing:
        print(f"  NG: 「{q[:30]}」")
    sys.exit(1 if missing else 0)


def main():
    if "--verify-profile" in sys.argv[1:]:
        verify_profile()
        return
    build("--dry-run" in sys.argv[1:])


if __name__ == "__main__":
    main()
