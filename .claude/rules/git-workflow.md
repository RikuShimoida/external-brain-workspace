## Git 作業フロー

### ブランチ作成ルール

- コード・設定・ドキュメントを変更する作業を始めるときは、**必ず作業用ブランチを切る**こと。
  `main` に直接コミットしない。
- ブランチ名は `feature/<issue番号>-<短い英語スラッグ>` を基本とする（例: `feature/5-cross-apply-beersalon-rules`）。
  Issue番号がない場合は `feature/<短いスラッグ>` でよい。
- 変更がまとまったら `gh pr create` でプルリクエストを作成し、`main` へは PR 経由でマージする。

### 破壊的操作

- `git push --force` / `git reset --hard` / `git rebase` / `git branch -D` などの破壊的コマンドは、
  実行前に目的・影響範囲・リスクをユーザーに明示して確認をとること（[command-rules.md](command-rules.md) の「確認時の説明義務」に従う）。
