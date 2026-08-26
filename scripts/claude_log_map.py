#!/usr/bin/env python3
"""Claude Code の会話ログから「地図」を作る。

本文はディスクに残さず、1セッションぶんの (日付・プロジェクト・タイトル・発言数・文字数) だけを
一覧化する。どのセッションが濃いかをタイトルで眺めて、claude_log_extract.py で
本文を取るセッションを選ぶための下ごしらえ。

貼り付けた他人の文章は**消さずに列で印を付ける**（`pasted` / `template`）。
濃さの物差しは「最長発言」ではなく「自筆の最長発言」（`longest_self`）のほうを見る。
判定の中身は claude_log_parse.py の docstring を参照。

元ログ（~/.claude/projects/）は読むだけで、書き換えも削除もしない。

使い方:
    python3 scripts/claude_log_map.py [--root パス]
      --root … ログの置き場（既定: ~/.claude/projects）

出力:
    claude-log-archive/session_map.tsv  … 1行=1セッション（日付順）
    標準出力に件数・期間・濃いセッションの上位などのサマリ
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claude_log_parse import LOG_ROOT, iter_sessions

OUT = "claude-log-archive/session_map.tsv"


def clean(s):
    """TSV を壊さないよう、タブと改行を潰す。"""
    return s.replace("\t", " ").replace("\n", " ").strip()


def main():
    args = sys.argv[1:]
    root = LOG_ROOT
    if "--root" in args:
        i = args.index("--root")
        root = os.path.expanduser(args[i + 1])

    if not os.path.isdir(root):
        sys.exit(f"ログが見つかりません: {root}")

    sessions = iter_sessions(root)
    if not sessions:
        sys.exit(f"発言のあるセッションがありません: {root}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as w:
        w.write(
            "date\tproject\tsession\ttitle\tutterances\tchars"
            "\tlongest\tlongest_self\tpasted\ttemplate\n"
        )
        for s in sessions:
            w.write(
                f"{s.date}\t{clean(s.project)}\t{s.session_id}\t{clean(s.title)}"
                f"\t{len(s.utterances)}\t{s.chars}\t{s.longest}\t{s.longest_self}"
                f"\t{s.count('pasted')}\t{s.count('template')}\n"
            )

    # サマリ
    total_u = sum(len(s.utterances) for s in sessions)
    total_c = sum(s.chars for s in sessions)
    dates = [s.date for s in sessions if s.date]
    print(f"発言のあるセッション: {len(sessions):,} 件")
    print(f"本人の発言: {total_u:,} 件 / {total_c:,} 字")
    if dates:
        print(f"期間: {dates[0]} 〜 {dates[-1]}")

    # 貼り付け・定型文の内訳（消さずに印を付けているだけなので、上の総数にも含まれている）
    for kind, label in (("pasted", "貼り付け"), ("template", "定型文")):
        n = sum(s.count(kind) for s in sessions)
        c = sum(len(u.text) for s in sessions for u in s.utterances if u.kind == kind)
        share = c / total_c if total_c else 0
        print(f"  うち{label}: {n:,} 件 / {c:,} 字（全体の {share:.1%}）")

    by_project = Counter()
    chars_by_project = Counter()
    for s in sessions:
        by_project[s.project] += len(s.utterances)
        chars_by_project[s.project] += s.chars
    print("\nプロジェクト別:")
    for p, n in by_project.most_common():
        print(f"  {p}: {n:,} 件 / {chars_by_project[p]:,} 字")

    by_month = Counter(s.date[:7] for s in sessions if s.date)
    print("\n月別セッション数:")
    for m in sorted(by_month):
        print(f"  {m}: {by_month[m]}")

    print("\n濃いセッション（自筆の最長発言の上位10件）:")
    for s in sorted(sessions, key=lambda s: -s.longest_self)[:10]:
        mark = " 貼付あり" if s.count("pasted") or s.count("template") else ""
        print(
            f"  {s.date} {s.project[:24]:<24} 自筆最長{s.longest_self:>6,}字"
            f" / {len(s.utterances):>3}件{mark}  {clean(s.title)[:32]}"
        )

    print(f"\n一覧を書き出しました: {OUT}")


if __name__ == "__main__":
    main()
