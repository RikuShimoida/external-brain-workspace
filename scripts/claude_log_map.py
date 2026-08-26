#!/usr/bin/env python3
"""Claude Code の会話ログから「地図」を作る。

本文はディスクに残さず、1セッションぶんの (日付・プロジェクト・タイトル・発言数・文字数) だけを
一覧化する。どのセッションが濃いかをタイトルで眺めて、claude_log_extract.py で
本文を取るセッションを選ぶための下ごしらえ。

貼り付けた他人の文章は**消さずに列で印を付ける**（`pasted` / `template`）。
濃さの物差しは「最長発言」ではなく「自筆の最長発言」（`longest_self`）のほうを見る。
判定の中身は claude_log_parse.py の docstring を参照。

**この地図は上書きではなくマージで書く。** 元ログ（~/.claude/projects/）は既定30日で
自動削除されるため、素直に書き直すと「もう元ログが無いセッション」の行が地図から消えてしまう。
削除は最終更新日で効くので、地図を作り直したその日に消えていなくても、
回さない期間が30日を超えた分から順に地図から欠けていくことになる。
そこで `session` をキーに、今回スキャンできた行は最新で置き換え、
**スキャンに現れなかった既存の行はそのまま残す**。消えたログは二度と再生成できない。

`last_seen` 列は「最後に元ログ側で実在を確認できた日」。この日付が古い行は、
元ログがもう無く、地図と `deep/` だけが残っている行という意味になる。

元ログ（~/.claude/projects/）は読むだけで、書き換えも削除もしない。

使い方:
    python3 scripts/claude_log_map.py [--root パス]
      --root … ログの置き場（既定: ~/.claude/projects）

出力:
    claude-log-archive/session_map.tsv  … 1行=1セッション（日付順・マージ書き込み）
    標準出力に件数・期間・濃いセッションの上位・今回の新規/更新件数などのサマリ
"""
import datetime
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claude_log_parse import LOG_ROOT, iter_sessions

OUT = "claude-log-archive/session_map.tsv"

COLUMNS = [
    "date", "project", "session", "title", "utterances", "chars",
    "longest", "longest_self", "pasted", "template", "last_seen",
]

# 中身が変わったかを見るときに比べない列。last_seen は毎回動くので除く。
COMPARE = [c for c in COLUMNS if c != "last_seen"]


def clean(s):
    """TSV を壊さないよう、タブと改行を潰す。"""
    return s.replace("\t", " ").replace("\n", " ").strip()


def read_existing(path):
    """既存の地図を {session_id: 行(dict)} で読む。

    last_seen 列が無かった頃の地図もそのまま読めるようにしてある（欠けた列は空文字）。
    """
    rows = {}
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
        for line in f:
            if not line.strip():
                continue
            row = dict(zip(header, line.rstrip("\n").split("\t")))
            sid = row.get("session")
            if sid:
                rows[sid] = {c: row.get(c, "") for c in COLUMNS}
    return rows


def to_row(s, today):
    """Session を地図の1行（dict）にする。"""
    return {
        "date": s.date,
        "project": clean(s.project),
        "session": s.session_id,
        "title": clean(s.title),
        "utterances": str(len(s.utterances)),
        "chars": str(s.chars),
        "longest": str(s.longest),
        "longest_self": str(s.longest_self),
        "pasted": str(s.count("pasted")),
        "template": str(s.count("template")),
        "last_seen": today,
    }


def num(row, key):
    """地図の行から数値列を取る（壊れていたら 0 扱い）。"""
    try:
        return int(row.get(key) or 0)
    except ValueError:
        return 0


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

    today = datetime.date.today().isoformat()
    existing = read_existing(OUT)
    scanned = {s.session_id: to_row(s, today) for s in sessions}

    new_ids = [i for i in scanned if i not in existing]
    changed_ids = [
        i for i in scanned
        if i in existing
        and any(scanned[i][c] != existing[i][c] for c in COMPARE)
    ]
    gone_ids = [i for i in existing if i not in scanned]

    # 今回見えた行で上書きし、見えなかった既存の行は残す（元ログが消えていても地図には残る）。
    merged = dict(existing)
    merged.update(scanned)
    rows = sorted(merged.values(), key=lambda r: (r["date"], r["project"], r["session"]))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as w:
        w.write("\t".join(COLUMNS) + "\n")
        for r in rows:
            w.write("\t".join(r[c] for c in COLUMNS) + "\n")

    # --- サマリ（地図に載っている全行から。元ログが消えた行も含む） ---
    total_u = sum(num(r, "utterances") for r in rows)
    total_c = sum(num(r, "chars") for r in rows)
    dates = sorted(r["date"] for r in rows if r["date"])
    print(f"地図のセッション: {len(rows):,} 件"
          f"（今回スキャンできた {len(scanned):,} 件 / 元ログが消えた {len(gone_ids):,} 件）")
    print(f"本人の発言: {total_u:,} 件 / {total_c:,} 字")
    if dates:
        print(f"期間: {dates[0]} 〜 {dates[-1]}")
    print(f"今回の差分: 新規 {len(new_ids):,} 件 / 更新 {len(changed_ids):,} 件")

    # 貼り付け・定型文の内訳（消さずに印を付けているだけなので、上の総数にも含まれている）
    for kind, label in (("pasted", "貼り付け"), ("template", "定型文")):
        n = sum(num(r, kind) for r in rows)
        print(f"  うち{label}: {n:,} 件")

    by_project = Counter()
    chars_by_project = Counter()
    for r in rows:
        by_project[r["project"]] += num(r, "utterances")
        chars_by_project[r["project"]] += num(r, "chars")
    print("\nプロジェクト別:")
    for p, n in by_project.most_common():
        print(f"  {p}: {n:,} 件 / {chars_by_project[p]:,} 字")

    by_month = Counter(r["date"][:7] for r in rows if r["date"])
    print("\n月別セッション数:")
    for m in sorted(by_month):
        print(f"  {m}: {by_month[m]}")

    print("\n濃いセッション（自筆の最長発言の上位10件）:")
    for r in sorted(rows, key=lambda r: -num(r, "longest_self"))[:10]:
        mark = " 貼付あり" if num(r, "pasted") or num(r, "template") else ""
        print(
            f"  {r['date']} {r['project'][:24]:<24} 自筆最長{num(r, 'longest_self'):>6,}字"
            f" / {num(r, 'utterances'):>3}件{mark}  {r['title'][:32]}"
        )

    if gone_ids:
        print(f"\n元ログが消えたセッション（地図にだけ残っている）: {len(gone_ids)} 件")
        for i in sorted(gone_ids, key=lambda i: existing[i]["date"])[:10]:
            r = existing[i]
            print(f"  {r['date']} {r['project'][:24]:<24} {r['title'][:32]}")

    print(f"\n一覧を書き出しました: {OUT}")


if __name__ == "__main__":
    main()
