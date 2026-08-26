---
name: merge
description: PR を Merge commit 方式でマージし、リモート・ローカル両方のブランチを削除して司令塔 main を最新化する。マージのタイミングはオーナーが決める。
when_to_use: PR をマージしたい時、「マージして」「merge」「この PR マージ」などの発言時。/impl の完了報告で「このままマージする」を選んだ時もこれを実行する。
---

## PR マージ

引数: `$ARGUMENTS`（PR 番号。例: 23）

### 前提条件

- このスキルは**司令塔（`main`）から実行する**。手順4で対象ブランチをローカル削除するため、
  そのブランチに立ったままでは削除できない。
- 実行冒頭で必ず確認する。
  ```bash
  git branch --show-current
  git status --porcelain
  ```
  - 既に `main` ならそのまま続行。
  - `main` 以外で **clean** なら、`git switch main` してから続行する。
  - **dirty（未コミット変更あり）なら自動切替せず停止**し、
    「未コミット変更があります。コミットまたは退避してから再実行してください」と案内する。
- マージのタイミングはオーナーが決める。`/impl` のフロー内で自動実行せず、明示的に選ばれた時だけ起動する。

### 手順

#### 1. マージ前チェック

```bash
gh pr view $ARGUMENTS --json number,title,headRefName,baseRefName,state,mergeable
```

- `state` が `OPEN` であること。`MERGED` / `CLOSED` なら報告して停止
  （既にマージ済みなら、手順4のローカル後片付けだけ実施するか確認する）。
- `baseRefName` が `main` であること。想定外のベースなら勝手にマージせず確認する。
- `mergeable` が `MERGEABLE` であること。`CONFLICTING` なら報告して停止
  （**このスキルではコンフリクトを解消しない**）。
- `headRefName` を控える（手順4で使う）。

> このリポジトリには CI が無いため、BeerSalon 版にある `gh pr checks --watch` の
> CI 待ちガードは行わない。**CI を追加したら、この節に待ちを足すこと。**

#### 2. マージ実行（Merge commit 方式 + リモートブランチ削除）

```bash
gh pr merge $ARGUMENTS --merge --delete-branch
```

- **なぜ `--merge`（Merge commit）か**: 個々のコミットを `main` の履歴の鎖に残し、
  `git checkout <コミットID>` での断面復元や `git bisect` を可能にするため。
  Squash は中間コミットへの到達性を構造的に捨てるので採用しない。
- `--delete-branch` でリモートのブランチを削除する。

#### 3. Issue のクローズ確認

このリポジトリはデフォルトブランチが `main` なので、PR 本文の `Closes #N` により
**GitHub 側で Issue が自動クローズされる**。

```bash
gh issue view <N> --json number,state,title
```

- 自動クローズされていない場合（本文にキーワードが無かった等）のみ、
  対応 Issue 番号を確認したうえで `gh issue close <N> --comment "PR #$ARGUMENTS のマージに伴いクローズ"` を実行する。
- **Issue 番号を特定できないなら、推測でクローズしてはならない。** 報告して手動対応に委ねる。

#### 4. 司令塔 main の最新化とローカルブランチ削除

```bash
git pull --ff-only origin main
git branch -d <headRefName>
git fetch --prune origin
```

- `--ff-only` が失敗する場合は、勝手に rebase / merge せず報告して指示を仰ぐ。
- `git branch -d`（小文字）を使う。マージ済みでなければ削除を拒否する安全側の動作。
  **失敗しても `-D` へ勝手に切り替えない**（未マージのコミットが残っている可能性があるため報告する）。
- 対象ブランチの worktree が残っている場合（通常は `/impl` の 2-3 で撤去済み）は、
  先に `git worktree remove` してからブランチを削除する。

#### 5. 完了報告

1. マージした PR 番号・タイトル・URL
2. クローズされた Issue 番号（自動 / 手動のどちらか）
3. 削除したブランチ（リモート / ローカル）
4. 司令塔 `main` の最新コミット
5. 異常があればその内容と、オーナーに委ねた判断

### 禁止事項

- `state` が OPEN でない、または `mergeable` が MERGEABLE でない PR を勝手にマージすること
- ベースが `main` 以外の PR をオーナー確認なしにマージすること
- コンフリクトをこのスキル内で勝手に解消すること
- `git branch -d` の失敗時に `-D` へ勝手に切り替えること
- 対応 Issue 番号を特定できないのに、推測で `gh issue close` すること
