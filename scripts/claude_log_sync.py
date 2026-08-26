#!/usr/bin/env python3
"""Claude Code の過去ログの抽出を、定期実行で自動的に回すための単一の口。

`claude_log_map.py`（地図）→ `claude_log_extract.py`（濃いセッションの本文）を順に走らせ、
最終実行日と前回からの差分を `claude-log-archive/last_run.json` に記録する。

**なぜ自動化が要るか。** 元ログ `~/.claude/projects/` は `cleanupPeriodDays` の既定
30日で自動削除される。X も Evernote も LINE も「取りに行けばいつでもある」が、
**Claude Code のログだけは、抽出を回さなかった期間がそのまま永久に失われる**。
手で思い出して月1回叩く運用は成立しない（意志ではなく環境で解く）。
保持期間そのものを延ばす手順は docs/data-sources.md を参照。

**安全装置が3つ入っている。**

1. **worktree では走らない。** `/impl` `/parallel` が作る作業ツリーから発火すると、
   アーカイブ配下を同時に書き換えて出力を壊す（docs/worktree-workflow.md §2 ①）。
   `.git` がファイルなら worktree と判定して即やめる。
2. **ロック。** 司令塔で二重に走っても片方だけが進む。1時間より古いロックは
   死んだプロセスの置き土産とみなして破る。
3. **実行間隔のガード。** 前回から既定24時間以内なら何もしない。
   セッション開始のたびに全走査しても意味がないため。

いずれの安全装置も「やめる」だけで、既存の抽出物には触らない。
地図はマージ書き込み、`deep/` は追記型なので、**元ログが消えた後に走っても過去の抽出物は減らない**。

使い方:
    python3 scripts/claude_log_sync.py [--force] [--quiet] [--min-interval-hours N]
      --force               … 実行間隔のガードを無視して必ず走らせる
      --quiet               … 子スクリプトの出力を伏せ、結果1行だけ出す（フック用）
      --min-interval-hours  … 前回からこの時間が経つまで走らない（既定 24）

出力:
    claude-log-archive/session_map.tsv   （claude_log_map.py がマージ更新）
    claude-log-archive/deep/*.md         （claude_log_extract.py が追記）
    claude-log-archive/last_run.json     … 最終実行日時と前回からの差分
"""
import datetime
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE = os.path.join(ROOT, "claude-log-archive")
MAP = os.path.join(ARCHIVE, "session_map.tsv")
DEEP = os.path.join(ARCHIVE, "deep")
LAST_RUN = os.path.join(ARCHIVE, "last_run.json")
LOCK = os.path.join(ARCHIVE, ".sync.lock")

MIN_INTERVAL_HOURS = 24
STALE_LOCK_SECONDS = 3600


def is_worktree():
    """このチェックアウトが worktree か。worktree では `.git` がファイルになる。"""
    return os.path.isfile(os.path.join(ROOT, ".git"))


def count_map_rows():
    """地図の行数（ヘッダを除く）。"""
    if not os.path.exists(MAP):
        return 0
    with open(MAP, encoding="utf-8") as f:
        return max(0, sum(1 for line in f if line.strip()) - 1)


def count_deep_files():
    if not os.path.isdir(DEEP):
        return 0
    return len([n for n in os.listdir(DEEP) if n.endswith(".md")])


def count_stale_rows(today):
    """元ログ側から消えた行の数（last_seen が今日でない行）。"""
    if not os.path.exists(MAP):
        return 0
    with open(MAP, encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
        if "last_seen" not in header:
            return 0
        i = header.index("last_seen")
        n = 0
        for line in f:
            if not line.strip():
                continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) <= i or cols[i] != today:
                n += 1
        return n


def acquire_lock():
    """ロックを取る。取れなければ False。古すぎるロックは破る。"""
    try:
        age = datetime.datetime.now().timestamp() - os.path.getmtime(LOCK)
        if age > STALE_LOCK_SECONDS:
            os.unlink(LOCK)
    except OSError:
        pass
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as w:
        w.write(f"{os.getpid()}\t{datetime.datetime.now().isoformat()}\n")
    return True


def release_lock():
    try:
        os.unlink(LOCK)
    except OSError:
        pass


def skipped_recently(min_hours):
    """前回実行からの経過が短ければ True。"""
    try:
        with open(LAST_RUN, encoding="utf-8") as f:
            last = datetime.datetime.fromisoformat(json.load(f)["last_run"])
    except (OSError, ValueError, KeyError):
        return False
    elapsed = datetime.datetime.now(last.tzinfo) - last
    return elapsed < datetime.timedelta(hours=min_hours)


def run(script, quiet):
    """子スクリプトを ROOT で走らせる。地図の出力先が相対パスなので cwd を固定する。"""
    proc = subprocess.run(
        [sys.executable, os.path.join("scripts", script)],
        cwd=ROOT,
        capture_output=quiet,
        text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(f"{script} が失敗しました (exit {proc.returncode})\n")
        if quiet and proc.stderr:
            sys.stderr.write(proc.stderr)
    return proc.returncode


def main():
    argv = sys.argv[1:]
    force = "--force" in argv
    quiet = "--quiet" in argv
    min_hours = MIN_INTERVAL_HOURS
    if "--min-interval-hours" in argv:
        min_hours = float(argv[argv.index("--min-interval-hours") + 1])

    def say(msg):
        if not quiet:
            print(msg)

    if is_worktree():
        say("worktree では走らせません（アーカイブを司令塔と共有しているため）。")
        return 0

    os.makedirs(ARCHIVE, exist_ok=True)

    if not force and skipped_recently(min_hours):
        say(f"前回の実行から {min_hours:g} 時間経っていないので何もしません（--force で強制実行）。")
        return 0

    if not acquire_lock():
        say("他のプロセスが実行中です（ロックあり）。何もしません。")
        return 0

    try:
        before_rows, before_deep = count_map_rows(), count_deep_files()

        if run("claude_log_map.py", quiet) != 0:
            return 1
        if run("claude_log_extract.py", quiet) != 0:
            return 1

        after_rows, after_deep = count_map_rows(), count_deep_files()
        today = datetime.date.today().isoformat()
        record = {
            "last_run": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "sessions_total": after_rows,
            "sessions_new": after_rows - before_rows,
            "sessions_gone": count_stale_rows(today),
            "deep_total": after_deep,
            "deep_new": after_deep - before_deep,
        }
        with open(LAST_RUN, "w", encoding="utf-8") as w:
            json.dump(record, w, ensure_ascii=False, indent=2)
            w.write("\n")

        print(
            f"Claude Code ログを取り込みました: "
            f"地図 {record['sessions_total']} 件（新規 {record['sessions_new']}）/ "
            f"deep {record['deep_total']} 件（新規 {record['deep_new']}）/ "
            f"元ログが消えた行 {record['sessions_gone']} 件"
        )
        return 0
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
