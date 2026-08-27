# Worktree 開発ワークフロー設計

BeerSalon で運用している「司令塔 + git worktree 並列開発」を、このリポジトリ向けに移植した設計。
2026-08-26 にオーナーと合意（Issue #24）。

BeerSalon 版（`~/Documents/repository/BeerSalon/docs/worktree-workflow.md`）との**最大の違いは、
共有されているのが DB ではなく「アーカイブの実体」と「MCP」**であること。ここが制約の根っこになる。

---

## 1. 基本思想

**並列・単独を問わず、実装は git worktree で行う（既定）。`main` のチェックアウトは「司令塔」専用とし、実装で汚さない。**

- `main` メインチェックアウト = 司令塔（指揮所）。常に clean に保つ。
- 各タスクの実装は `.claude/worktrees/<branch>` で行う。
- `/impl`（単独）も `/parallel`（並列）も「worktree を切る」が共通の起点になる。

### なぜこの形か（Why）

- 司令塔の `git status` がいつ見ても綺麗で、ブランチ取り違え・stash 地獄が起きない。
- worktree はファイルを物理的に分離するので、複数タスクの変更が混ざらない。
- オーナーは「記憶を信用しない」前提で動く。**どのタスクがどこにあるかがディレクトリとして目に見える**のは、
  頭の中で状態を保持しなくてよいという意味で相性がいい。

### 撤退路（`--no-worktree`）

`/impl <Issue> --no-worktree` で、worktree を作らず従来どおり司令塔でブランチを切って実装できる。

- 1行の typo 修正など、worktree のオーバーヘッドが割に合わないとき用。
- worktree 運用が恒常的に割に合わないと判断したら、運用として `--no-worktree` を既定にし、
  その判断をこの節に追記する。**やめるときは Git で戻すのではなくスキルのスイッチで切る。**

---

## 2. 重要な前提：worktree が隔離するのは「Git 管理下のファイルだけ」

worktree は作業ディレクトリのファイルを分離するが、**以下は全 worktree で共有されたまま**である。

| 共有されるもの | 実体 | 影響 |
|---|---|---|
| アーカイブ（入力） | `.worktreeinclude` の `link` 行（`*-archive`） | Git 管理外。§3 でシンボリックリンクを張るため、**全 worktree が同じ実体を見る** |
| 生成物（出力） | `.worktreeinclude` の `link` 行（出力ディレクトリ） | 同上。worktree 撤去で生成物を失わないよう、あえて本体側へ書かせている |
| MCP | Evernote / Twitter / Google Calendar / freee | レート制限があり、外部サービスへの書き込みは取り消せない |

→ 「常時 worktree 化」が解決するのは *Git 管理下のファイルの分離* であって *データと外部サービスの分離* ではない。

### ① 同じディレクトリを書き換えるタスクは並列禁止（直列化）

以下のタスクは、複数 worktree で同時に走らせると互いの出力を壊す。

- `scripts/*_map.py` / `scripts/*_extract.py` の実行（アーカイブ配下を作り直す）
- 同じ出力ディレクトリへ書き出すスキルの実行（例: 2つの worktree で同時に `/note-draft`）
- `evernote-archive/note_map.tsv` の再生成

**自動で走るものが1つだけある。** `scripts/claude_log_sync.py`（Claude Code ログの取り込み）は
`.claude/settings.json` の `SessionStart` フックから発火する。これがここのルールを破らないよう、
スクリプト側に安全装置を持たせてある。

- **worktree では走らない。** `.git` がファイルなら worktree と判定して即やめる。
  worktree で Claude Code を起動してもアーカイブには触らない。
- **ロックを取る。** 司令塔で二重に走っても片方だけが進む。
- いずれも「やめる」だけで、既存の抽出物には触らない。

詳細は [data-sources.md](data-sources.md) の「消える前に取り切るための仕組み」。

**対策**: 司令塔が適格判定で検出し、最初の1つだけ走らせて他は待機させる（直列）。
判定に迷う場合は推測せず、「このタスクはアーカイブや生成物を書き換えますか？」とオーナーに確認する。

### ② MCP への書き込みは司令塔だけが行う

- **`post_tweet`（X への投稿）・`create_event` / `update_event`（カレンダー）・`edit_note` / `create_note`（Evernote）は、
  worktree のサブエージェントに実行させない。**
- 理由: これらは外部サービスへの不可逆な書き込みであり、`tweet-draft` スキルの「承認制」も
  postmortem の「ノートを直接更新する」も、**オーナーの承認が前提**になっている。
  並列で走るサブエージェントは承認の窓口を持たない。
- 読み取り（`semantic_search` / `search_notes` / `get_note` / `list_events`）は並列で行ってよい。
  ただしレート制限があるため、全件走査のような重い読み取りは同時に何本も走らせない。

### ③ 検証は「テスト」ではなく「実際に走らせて数を見る」

このリポジトリには UT / E2E / CI が無い。代わりの品質ゲートは以下（`/impl` Phase 1-3 と対応）。

| 変更対象 | 検証方法 |
|---|---|
| `scripts/*.py` | `--dry-run` があれば先に dry-run → 実行し、**処理件数・出力ファイル数を報告**する |
| スキル / エージェント定義 | フロントマターが読めること、参照している相対パス（`references/` `scripts/` 等）が実在すること |
| ドキュメント / CLAUDE.md | リンク先のファイルが実在すること、記載した件数・パスが現物と一致すること |

**捏造しないこと**（CLAUDE.md の原則）は検証にも適用される。「たぶん動く」で報告しない。

---

## 3. worktree 作成の正確な手順

### main 起点で切る（必須）

```bash
git fetch origin main
git worktree add .claude/worktrees/<branch> origin/main -b <branch>
```

- ブランチ命名は `/impl` と同じ規則: `feature/<issue番号>-<英語スラッグ>` / `bugfix/<issue番号>-<英語スラッグ>`。
- **なぜ生の `git worktree add` か**: Claude Code の Agent `isolation: "worktree"` はベースを
  細かく指定できない。起点を明示できる生コマンドを使い、常に `origin/main` の最新から切る。

### worktree の初期化（スキルの手続きとして明示的に実行）

git / Claude Code のネイティブ機能では自動化されないため、worktree 作成直後に必ず行う。
**司令塔のリポジトリルートで**次を実行する。

```bash
scripts/worktree_init.sh .claude/worktrees/<branch>
```

#### 対象の定義は `.worktreeinclude` ただ1つ

`scripts/worktree_init.sh` は `.worktreeinclude` を読むだけで、対象名を一切持たない。
`link` 行は実体をコピーせずシンボリックリンクを張り、`copy` 行は複製する。
**アーカイブや出力ディレクトリを増やすときに書き換えるのは `.worktreeinclude` と `.gitignore` の2つだけ**で、
このドキュメントもスキルも触らなくてよい。

> **なぜこの形か。** 以前はここと `.claude/skills/impl/SKILL.md` に同じ `for d in ...` が
> べた書きで複製されており、対象を足すたびに3箇所へ手で同期する必要があった。
> 実際に `claude-log-archive` と `kindle-archive` を2回続けて取りこぼしている（Issue #31 / #39）。
> **ドキュメントと定義は直るのに、実際に走るコマンドが置き去りになる**のが再発パターンだった。
> だからここには**対象一覧もループ本体も書かない**。書いた時点で重複が復活する。

補助モード:

| コマンド | 用途 |
|---|---|
| `scripts/worktree_init.sh --dry-run <path>` | 実行せず対象を列挙する |
| `scripts/worktree_init.sh --check` | `link` 行が `.gitignore` に入っているかを `git check-ignore` で検証する |

`--check` は個人データ混入の予防線。`.worktreeinclude` に足して `.gitignore` に足し忘れると、
worktree で張ったリンクが untracked のまま残り、誤ってコミットしうる。

- 再実行しても安全（既にあるものはスキップする）。
- **なぜコピーではなくリンクか**: アーカイブは合計で約1GB ある。タスクごとに複製すると
  ディスクも時間も無駄で、しかも本体側の更新が worktree に反映されない。
  出力ディレクトリをリンクするのは、**worktree を撤去しても生成物（ネタ・下書き・判断ログ）が消えないため**。
- リンクである以上、複数 worktree が同じ実体を見る。だから §2 ① の直列化ルールが要る。
- 依存インストール（`pnpm install` 相当）は不要。Python の標準ライブラリしか使っていない。

#### 検証で分かったこと（2026-08-26 に実機確認）

- **`.gitignore` は末尾スラッシュを付けてはいけない。** `twitter-archive/` と書くとディレクトリにしか
  マッチせず、**シンボリックリンクは無視されず untracked として残る**。司令塔と worktree の
  `git status` が汚れ、リンクを誤ってコミットする事故につながるため、`twitter-archive` と書く。
- **リンクを消すときはスラッシュを付けない。** worktree 内で `rm -rf twitter-archive/` と打つと
  **リンク先の実体（本体側の約360MB）が消える**。撤去は `rm twitter-archive`（リンクだけ削除）か、
  `git worktree remove` に任せる。
- **`git worktree remove` は無視ファイル（`.env` / `settings.local.json` / `__pycache__`）が
  残っていても通る**（`--force` は不要）。逆に、追跡ファイルに変更が残っていると弾かれる＝
  作業の取りこぼしを防ぐガードとして機能する。
- worktree の実サイズは 872KB だった（リンクなので実体はコピーされない）。

### 後片付け

- PR 作成完了後に `git worktree remove .claude/worktrees/<branch>`。
- 未コミット変更が残る場合は撤去せずオーナーに報告する。
- `.gitignore` に `.claude/worktrees/` を追加済み（司令塔のチェックアウトを汚さない）。

---

## 4. 並列の全体像

```
worktree-A (実装サブエージェント) ──「実装＋検証完了。PR作成済み」──┐
worktree-B (実装サブエージェント) ──「実装＋検証完了。PR作成済み」──┤
worktree-C (実装サブエージェント) ──「実装＋検証完了。PR作成済み」──┤
                                                                  ▼
                                        ┌────────────────────────────────┐
                                        │ 司令塔 (main)                    │
                                        │ ・適格判定（並列可否）             │
                                        │ ・アーカイブ書き換えタスクを直列化   │
                                        │ ・MCP への書き込みを一手に引き受ける │
                                        │ ・/merge でマージ                 │
                                        └────────────────────────────────┘
```

BeerSalon と違い、**検品台（共有DB）が無いぶん直列キューは軽い**。
直列になるのは「アーカイブや生成物を書き換えるタスク」と「MCP への書き込み」だけ。

---

## 5. アンチパターン（やってはいけない）

- アーカイブ（約1GB）を worktree へ実体コピーする
- 複数 worktree で同時に `scripts/*_map.py` / `*_extract.py` を実行する（出力が壊れる）
- サブエージェントに `post_tweet` / `create_event` / `edit_note` を実行させる（承認を飛ばした外部書き込み）
- worktree に出力ディレクトリをリンクせず、生成物ごと `git worktree remove` で消す
- **worktree 内で `rm -rf <リンク名>/` を打つ**（リンク先の実体、つまり本体のアーカイブが消える）
- `.gitignore` に末尾スラッシュ付きでデータディレクトリを書く（リンクが無視されなくなる）
- **リンク対象の一覧やループ本体を、スキル・ドキュメントへ書き写す**（定義は `.worktreeinclude` ただ1つ。
  複製した瞬間に「定義は直ったが実際に走るコマンドが古い」という取りこぼしが復活する）
- アーカイブを足したのに `.worktreeinclude` か `.gitignore` の片方だけ更新する
  （`scripts/worktree_init.sh --check` で検出できる）
- 司令塔（`main`）で実装を始めてしまい、`git status` を汚す

---

## 6. 既存資産への影響

| 対象 | 影響 |
|---|---|
| `/plan` | 新規。Issue から計画を出すだけ。Git 操作はしない |
| `/impl` | 新規。1タスク = 1 worktree の実装フロー本体。単独でも割り込みでもこれを呼ぶ |
| `/parallel` | 新規。複数 Issue 一括投入時のみ使う薄い司令塔。中身は各 Issue へ `/impl` 相当を発火するだけ |
| `/merge` | 新規。マージ + ブランチ削除 + 司令塔 `main` の最新化 |
| `external-brain-engineer` エージェント | 新規。`/impl` `/parallel` の実装担当 |
| 既存スキル（podcast-neta / tweet-draft / note-draft / books / decide / postmortem） | 変更なし。これらは「外部脳を使う」スキルであり、開発フローとは層が違う |
| `scripts/worktree_init.sh` | 新規。`.worktreeinclude` を読んで worktree を初期化する唯一の実行体（Issue #39） |
| `.gitignore` | `.claude/worktrees/` を追加 |
