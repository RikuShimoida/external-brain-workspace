#!/usr/bin/env python3
"""Claude Code の会話ログから「濃いセッション」だけ本文を抽出する。

そのセッションでいちばん長い発言が閾値を超えるものだけを Markdown 化する。
発言の中央値は 17 字（「はい」「OK」などの相槌）で、合計文字数で選ぶと相槌の多い
セッションが上位に来てしまう。LINE と同じく「最長発言」で見ると、
設計や相談を書き下したセッションだけを拾える。

抜き出すのはそのセッションの発言全部。長文だけ切り出すと前後の文脈が消えるため。
Claude 側の応答は入れない（膨大なうえ、外部脳として要るのは本人の言葉のほう）。

元ログ（~/.claude/projects/）は読むだけで、書き換えも削除もしない。

使い方:
    python3 scripts/claude_log_extract.py [閾値] [--dry-run] [--project 名前] [--root パス]
      閾値        … そのセッションの最長発言の文字数の下限（既定 100）
      --dry-run   … 書き出さず対象セッションだけ表示
      --project   … プロジェクト名で絞る（部分一致）
      --root      … ログの置き場（既定: ~/.claude/projects）

出力:
    claude-log-archive/deep/YYYY-MM-DD_プロジェクト_セッション頭8桁.md
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claude_log_parse import LOG_ROOT, iter_sessions

OUTDIR = "claude-log-archive/deep"
THRESHOLD = 100


def safe_name(s):
    """ファイル名に使える形に均す。"""
    s = re.sub(r"[^\w぀-ヿ一-鿿 ー-]", "", s)
    return s.strip().replace(" ", "_")[:40] or "無題"


def main():
    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    project_filter = None
    root = LOG_ROOT
    if "--project" in argv:
        i = argv.index("--project")
        project_filter = argv[i + 1]
        del argv[i : i + 2]
    if "--root" in argv:
        i = argv.index("--root")
        root = os.path.expanduser(argv[i + 1])
        del argv[i : i + 2]
    nums = [a for a in argv if not a.startswith("--")]
    threshold = int(nums[0]) if nums else THRESHOLD

    if not os.path.isdir(root):
        sys.exit(f"ログが見つかりません: {root}")

    sessions = iter_sessions(root)
    picked = [
        s
        for s in sessions
        if s.longest >= threshold
        and (project_filter is None or project_filter in s.project)
    ]

    total_u = sum(len(s.utterances) for s in picked)
    total_c = sum(s.chars for s in picked)
    print(
        f"最長 {threshold} 字以上のセッション: {len(picked)} 件"
        f"（発言 {total_u:,} 件 / 本文計 {total_c:,} 字）"
    )

    if dry:
        for s in picked:
            print(
                f"  {s.date}  {s.project[:24]:<24} {len(s.utterances):>3}件"
                f"  最長{s.longest:>6,}字  {s.title[:32]}"
            )
        return

    os.makedirs(OUTDIR, exist_ok=True)
    for s in picked:
        fname = f"{OUTDIR}/{s.date}_{safe_name(s.project)}_{s.session_id[:8]}.md"
        with open(fname, "w", encoding="utf-8") as w:
            w.write(f"# {s.title}\n\n")
            w.write(
                f"- 日付: {s.date}\n"
                f"- プロジェクト: {s.project}\n"
                f"- セッション: {s.session_id}\n"
                f"- 発言数: {len(s.utterances)}\n"
                f"- 最長: {s.longest} 字\n\n---\n\n"
            )
            for u in s.utterances:
                w.write(f"**{u.timestamp}:**\n\n{u.text}\n\n")
    print(f"{len(picked)} 件を {OUTDIR}/ に書き出しました。")


if __name__ == "__main__":
    main()
