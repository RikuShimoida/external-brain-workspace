#!/usr/bin/env bash
# .worktreeinclude を読んで、新しい worktree へ Git 管理外のものを引き継ぐ。
#
# 対象の定義は .worktreeinclude ただ1つ。このスクリプトには対象名を一切書かない。
# （以前はスキルとドキュメントに for ループがべた書きで複製されており、アーカイブを足すたびに
#  同期を取りこぼしていた。Issue #39 で一元化した。）
#
# 使い方:
#   scripts/worktree_init.sh <worktree のパス>              リンク/コピーを実行
#   scripts/worktree_init.sh --dry-run <worktree のパス>    実行せず対象を列挙
#   scripts/worktree_init.sh --check                        link 行が .gitignore に入っているか検証
set -euo pipefail

ORIG_PWD="$PWD"
cd "$(dirname "$0")/.."
ROOT="$PWD"
INCLUDE="$ROOT/.worktreeinclude"

usage() {
  cat >&2 <<'EOU'
使い方:
  scripts/worktree_init.sh <worktree のパス>            リンク/コピーを実行
  scripts/worktree_init.sh --dry-run <worktree のパス>  実行せず対象を列挙
  scripts/worktree_init.sh --check                      link 行が .gitignore に入っているか検証
EOU
  exit 2
}

MODE=apply
W_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) MODE=dry-run ;;
    --check)   MODE=check ;;
    -h|--help) usage ;;
    -*)        echo "エラー: 不明なオプション: $1" >&2; usage ;;
    *)
      if [ -n "$W_ARG" ]; then
        echo "エラー: worktree のパスは1つだけ指定してください。" >&2
        usage
      fi
      W_ARG="$1"
      ;;
  esac
  shift
done

[ -f "$INCLUDE" ] || { echo "エラー: $INCLUDE が見つかりません。" >&2; exit 1; }

# .worktreeinclude を「種別 対象」の行だけに正規化する（コメントと空行を落とす）
read_include() {
  sed -e 's/#.*//' -e 's/[[:space:]]*$//' "$INCLUDE" | grep -v '^[[:space:]]*$' || true
}

# --- --check: link 対象が .gitignore に入っているか検証 ---------------------
# 入れ忘れると、worktree で張ったリンクが untracked のまま残り、個人データを
# コミットする事故につながる（docs/worktree-workflow.md §3）。
if [ "$MODE" = check ]; then
  ok=0
  ng=0
  while read -r kind target _rest; do
    [ "$kind" = link ] || continue
    if git -C "$ROOT" check-ignore -q -- "$target"; then
      ok=$((ok + 1))
    else
      echo "NG: $target が .gitignore に入っていません（末尾スラッシュ無しで追加すること）" >&2
      ng=$((ng + 1))
    fi
  done <<EOF
$(read_include)
EOF
  echo "check: link ${ok}件 OK / ${ng}件 NG"
  [ "$ng" -eq 0 ] || exit 1
  exit 0
fi

# --- apply / dry-run --------------------------------------------------------
[ -n "$W_ARG" ] || { echo "エラー: worktree のパスを指定してください。" >&2; usage; }

case "$W_ARG" in
  /*) W="$W_ARG" ;;
  *)  W="$ORIG_PWD/$W_ARG" ;;
esac
W="${W%/}"

[ -d "$W" ] || { echo "エラー: worktree が見つかりません: $W" >&2; exit 1; }
[ -e "$W/.git" ] || { echo "エラー: worktree ではありません（.git が無い）: $W" >&2; exit 1; }
[ "$W" != "$ROOT" ] || { echo "エラー: 司令塔のチェックアウト自身は初期化できません。" >&2; exit 1; }

linked=0
copied=0
skipped=0

while read -r kind target _rest; do
  src="$ROOT/$target"
  dst="$W/$target"

  case "$kind" in
    link)
      if [ ! -e "$src" ]; then
        echo "skip: ${target}（本体側に存在しません）"
        skipped=$((skipped + 1))
        continue
      fi
      if [ -e "$dst" ] || [ -L "$dst" ]; then
        echo "skip: ${target}（すでにあります）"
        skipped=$((skipped + 1))
        continue
      fi
      if [ "$MODE" = dry-run ]; then
        echo "link: $target -> $src"
      else
        mkdir -p "$(dirname "$dst")"
        ln -s "$src" "$dst"
        echo "link: $target"
      fi
      linked=$((linked + 1))
      ;;
    copy)
      if [ ! -f "$src" ]; then
        echo "skip: ${target}（本体側に存在しません）"
        skipped=$((skipped + 1))
        continue
      fi
      if [ -e "$dst" ]; then
        echo "skip: ${target}（すでにあります）"
        skipped=$((skipped + 1))
        continue
      fi
      if [ "$MODE" = dry-run ]; then
        echo "copy: $target"
      else
        mkdir -p "$(dirname "$dst")"
        cp "$src" "$dst"
        echo "copy: $target"
      fi
      copied=$((copied + 1))
      ;;
    *)
      echo "警告: .worktreeinclude の不明な種別を無視します: $kind $target" >&2
      ;;
  esac
done <<EOF
$(read_include)
EOF

label="完了"
[ "$MODE" = dry-run ] && label="dry-run"
echo "${label}: リンク ${linked}本 / コピー ${copied}本 / スキップ ${skipped}件"
