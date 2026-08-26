# external-brain-workspace
XやEvernoteにアクセスすることができ、外部サービスに保存された自分の思考から新たなアイデアを生み出す

## X (Twitter) MCP のセットアップ

このリポジトリでは [`@enescinar/twitter-mcp`](https://www.npmjs.com/package/@enescinar/twitter-mcp) を MCP サーバーとして設定済みです（`.mcp.json`）。ツイートの投稿・検索ができます。

### 1. X API の認証情報を取得

1. [X Developer Portal](https://developer.x.com/) でアプリを作成
2. アプリの権限を **Read and Write** に設定（投稿に必要）
3. 以下の4つを取得
   - API Key
   - API Secret Key
   - Access Token
   - Access Token Secret

### 2. 認証情報を設定

`.env.example` をコピーして `.env` を作り、値を埋めます（`.env` は Git 管理外）。

```bash
cp .env.example .env
# エディタで .env を開いて4つの値を入力
```

### 3. 環境変数を読み込んで Claude Code を起動

Claude Code は `.mcp.json` の `${VAR}` をシェルの環境変数から展開します。`.env` を読み込んでから起動してください。

```bash
set -a && source .env && set +a && claude
```

毎回打つのが面倒なら、付属の `scripts/claude.sh` を使えます。

```bash
./scripts/claude.sh
```

### 4. 動作確認

Claude Code 起動後、`/mcp` で `twitter` サーバーが接続済み（connected）になっていることを確認してください。

## Evernote MCP のセットアップ

Evernote 公式のリモート MCP サーバー（`https://mcp.evernote.com/mcp`）を設定済みです（`.mcp.json`）。ノートの検索・閲覧・作成・編集、ノートブック/タグ/タスクの管理ができます。認証は OAuth なので、API キーやトークンの手動設定は不要です。

### 1. Claude Code で認証

`.mcp.json` に設定済みなので、Claude Code を起動して `/mcp` を実行します。`evernote` サーバーを選んで認証（authenticate）すると、ブラウザで Evernote へのサインイン承認画面が開きます。承認すると `connected` になります。

```bash
./scripts/claude.sh   # または claude
# 起動後、/mcp → evernote → authenticate
```

### 2. 動作確認

`/mcp` で `evernote` サーバーが接続済み（connected）になっていることを確認してください。

> 補足: 公式 Evernote MCP はベータ版です。問題があれば Evernote のサポートチケットにメッセージ「MCP」と記載して報告できます。

## Gmail（claude.ai コネクタ）のセットアップ

Gmail は Twitter / Evernote と違い、**`.mcp.json` では設定できません**。claude.ai 側のコネクタとして認可します。

### 1. claude.ai で認可

claude.ai のコネクタ設定を開き、Gmail を認可します。Claude Code のセッション内から認可フローを走らせることはできません。

### 2. Claude Code を再起動する（重要）

**MCP コネクタは Claude Code の起動時に読み込まれます。** claude.ai で認可しても、すでに動いているセッションには反映されません。必ず起動し直してください。

```bash
# いったん終了してから
./scripts/claude.sh
```

### 3. 動作確認

`list_labels` を呼んで `SENT` の件数が返れば接続できています。読み取り3種（`list_labels` / `search_threads` / `get_message`）だけを使い、送信・削除・ラベル変更などの書き込み系ツールは使いません（詳細は [docs/data-sources.md](docs/data-sources.md)）。
