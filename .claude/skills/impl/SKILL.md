---
name: impl
description: Issue 起点の実装フロー。main 起点で worktree を作成し、実装 → 検証 → コミット → PR 作成 → worktree 撤去までを一貫して実行する。事前に /plan で計画承認済みであることが前提。
when_to_use: 「実装して」「この Issue やって」「implement」などの発言時、Issue 番号を指定して実装を依頼された時。事前に /plan で計画がオーナーに承認されていること。
---

## Issue 起点の実装

引数: `$ARGUMENTS`（Issue 番号。例: 19。`--no-worktree` を後置できる）

### 前提条件

- `/plan $ARGUMENTS` で計画を出し、オーナーが承認済みであること。
  未承認なら、先に `/plan $ARGUMENTS` を実行するよう案内して終了する。
- **worktree 起点の常時運用が前提**。設計の全体像は [docs/worktree-workflow.md](../../../docs/worktree-workflow.md) を参照。
  単独実装でも割り込み実装でも 1タスク = 1 worktree で行い、司令塔（`main`）は clean に保つ。

#### このスキルは司令塔自身が実行する

`/impl` はサブエージェントに丸投げせず、**いまの会話（司令塔）がそのまま worktree の中で作業する**。
CLAUDE.md の「勝手に突き進まない。分岐は逐一オーナーに確認する」を守るため、
判断の分岐でオーナーに聞ける場所に居続ける必要があるから。
**複数 Issue をまとめて投入したいときだけ `/parallel` を使う**（そちらはサブエージェントに委譲する）。

#### 撤退路（`--no-worktree`）

- 既定は worktree モード。
- 引数に **`--no-worktree`** が含まれる場合は worktree を作らず、司令塔でブランチを切って実装する
  （1-0b / 1-1b）。1行の typo 修正など、worktree が割に合わないタスク用。
  - 例: `/impl 19 --no-worktree`

---

### Phase 1: 実装

#### 1-0. 前提チェック（worktree モード。満たさなければ停止）

- `git branch --show-current` が `main` であること。
  - `main` 以外なら「`git switch main` してから再実行してください」と案内して停止。
- 司令塔の作業ツリーが clean であること（`git status --porcelain` が空）。
  - clean でなければ、未コミット変更の扱いをオーナーに確認してから進む。
- 司令塔のローカル `main` を最新化する（clean を確認した後）。
  ```bash
  git pull --ff-only origin main
  ```
  - `--ff-only` が失敗する場合は、勝手に rebase / merge せず状況を報告して指示を仰ぐ。

#### 1-0b. 前提チェック（`--no-worktree` 時）

- `main` が clean であることだけ確認し、worktree は作らない。並列実装はできない（単独タスク向け）。

#### 1-1. worktree とブランチの作成（worktree モード）

- ブランチ命名: `feature/<issue番号>-<英語スラッグ>` または `bugfix/<issue番号>-<英語スラッグ>`
- 手順:
  ```bash
  git fetch origin main
  git worktree add .claude/worktrees/<prefix>-$ARGUMENTS-<スラッグ> origin/main -b <prefix>/$ARGUMENTS-<スラッグ>
  ```
  - **なぜ生の `git worktree add` か**: Claude Code の Agent `isolation: "worktree"` では起点を
    明示できない。常に `origin/main` の最新から切るため、生コマンドを使う。

##### worktree の初期化（必ず実行する）

アーカイブと生成物は Git 管理外なので、worktree にはそのままでは存在しない。
対象の定義は `.worktreeinclude`（このリポジトリ独自の取り決め。git の標準機能ではない）。

```bash
W=.claude/worktrees/<このタスクの worktree>
for d in twitter-archive chatgpt-archive evernote-archive line-archive calendar-archive \
         claude-log-archive kindle-archive \
         podcast-ideas tweet-drafts note-drafts decisions analysis; do
  [ -e "$d" ] && ln -s "$(pwd)/$d" "$W/$d"
done
[ -f .env ] && cp .env "$W/.env"
[ -f .claude/settings.local.json ] && cp .claude/settings.local.json "$W/.claude/settings.local.json"
```

- **リンクであってコピーではない**（アーカイブは合計約1GB）。生成物ディレクトリもリンクなので、
  worktree を撤去しても出力は本体側に残る。
- **worktree 内で `rm -rf <リンク名>/` を打ってはならない。** リンク先の実体（本体のアーカイブ）が消える。
  リンクだけ消したいときはスラッシュ無しの `rm <リンク名>`。
- 依存インストールは不要（Python 標準ライブラリのみ）。
- 以降の作業（1-2〜1-5）は、すべてこの worktree ディレクトリ内で行う。

#### 1-1b. ブランチ作成（`--no-worktree` 時）

```bash
git switch main && git pull --ff-only origin main
git switch -c <prefix>/$ARGUMENTS-<スラッグ>
```

- リンク・コピーは不要（本体のディレクトリをそのまま使う）。

##### 英語スラッグの決め方

- 小文字 + ハイフン区切り、日本語禁止、3〜5語以内。
- Issue タイトルの直訳ではなく要点を短く。
  - 例: 「Claude Code の過去ログをデータソースに追加する」→ `claude-log-archive`
- プレフィックス: バグ修正 → `bugfix/`、それ以外 → `feature/`

#### 1-2. 実装

- Issue の要件に基づいて実装する。
- **CLAUDE.md の原則を守る**。特に「ネタや引用を捏造しない」。
  引用は必ず実在する投稿・ノートに紐づけ、読んでいないものを読んだことにしない。
- 個人データを Git に混入させない。新しいアーカイブ・生成物ディレクトリを作ったら
  `.gitignore` への追加も同じ PR に含める。

#### 1-3. 検証（このリポジトリには UT / E2E / CI が無い）

「たぶん動く」で先に進まない。変更対象ごとに次を実行し、**実測値を控える**。

| 変更対象 | 検証 |
|---|---|
| `scripts/*.py` | `--dry-run` があれば先に dry-run → 本実行。処理件数・出力ファイル数を実測 |
| スキル / エージェント定義 | フロントマターが壊れていないこと、参照している相対パスが実在すること（`ls` で確認） |
| ドキュメント / CLAUDE.md | リンク先が実在すること、書いた件数・パスが現物と一致すること |

##### 共有資源の扱い（厳守）

- アーカイブ配下（`*-archive/`）や生成物ディレクトリは**シンボリックリンクで司令塔と共有**されている。
  ここへ**書き込む**検証は、他の worktree が同時に走っていないことを確認してから行う。
  並列実行中なら書き込みを保留し、司令塔に「要 直列実行」と報告する。
- **外部サービスへの書き込み（`post_tweet` / `create_event` / `edit_note` など）はここで行わない**。
  オーナーの承認が前提のため、完了報告に「要 承認」と書いて委ねる。

#### 1-4. ドキュメント同期

- 変更内容に応じて `CLAUDE.md` / `README.md` / `docs/` / 対象スキルの `SKILL.md` を更新する。
- 特に **CLAUDE.md のデータソース表**と **`docs/data-sources.md`** は実体とズレやすいので必ず確認する。
- CLAUDE.md は毎ターン context に乗る固定費。詳細は `docs/` に置き、**案内板に徹させる**。

---

### Phase 2: 完了

#### 2-1. コミット・プッシュ

- すべての変更をコミットする。コミットメッセージに Issue 番号を含める。
- `git status` が clean になっていることを確認してから push する。

#### 2-2. PR 作成

```bash
gh pr create --base main
```

- PR 本文に `Closes #$ARGUMENTS` を記載する。
  このリポジトリはデフォルトブランチが `main` なので、**マージ時に Issue は自動でクローズされる**。

#### 2-3. worktree の後片付け

worktree モードの場合のみ実施（`--no-worktree` 時はスキップ）。

```bash
git worktree remove .claude/worktrees/<このタスクの worktree>
```

- `.env` などの無視ファイルが残っていても撤去は通る（`--force` は不要。実機確認済み）。
  **追跡ファイルに未コミット変更が残っている場合だけ弾かれる**ので、そのときは撤去せず完了報告に明記する。
- 撤去しても、リンクしていた生成物は本体側に残っている（消えていないことを一言添える）。

#### 2-4. 完了報告

次を報告する。**長く書かず、箇条書きで短く**。

1. 何を変えたか / なぜ変えたか
2. 変更ファイル一覧
3. 検証結果（実行したコマンドと実測した件数・出力）
4. アーカイブ・生成物ディレクトリへ書き込んだか
5. 外部サービスへの書き込みで承認待ちのものがあるか
6. PR URL

#### 2-5. 次アクションの確認（2択のみ）

完了報告のあと、**AskUserQuestion で2択だけ**聞く。3つ以上並べない。

1. **このままマージする** — `/merge <PR番号>` の手順を実行する
2. **あとで決める** — 何もしない。後から `/merge <PR番号>` を叩けばよい

「あとで決める」を選ばれたら、PR 番号を明記して終了する。**勝手にマージしてはならない。**

---

### 禁止事項

- 検証（1-3）を飛ばしてコミット・PR 作成すること
- 司令塔（`main`）の作業ツリーで実装を始めること（`--no-worktree` 指定時を除く）
- worktree 初期化のリンク・コピーを省略すること（アーカイブが見えず、実装が空振りする）
- オーナーの承認なしに外部サービスへ書き込むこと
- オーナーの確認なしにマージすること
