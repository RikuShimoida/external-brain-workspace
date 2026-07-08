---
name: podcast-neta
description: X の過去ツイート（twitter-archive のローカルアーカイブ）と Evernote のノートから、ひとり語り Podcast のネタになりそうなポエム/哲学系の言葉を発掘し、「こんなネタどうですか？」と Markdown で提案する。過去の投稿を Podcast/ラジオのネタに再利用したいとき、自分のキャラクターや価値観を語れる話題を探したいときに使う。
---

# Podcast ネタ発掘スキル

X の過去ツイートと Evernote のノートという2つの「外部脳」から、
**ひとり語り Podcast** のネタになる言葉を発掘し、提案する。

狙いは、バズった投稿ではなく **人格のルーツを感じさせる言葉** を拾い、
ユーザーのキャラクターが伝わるエピソードの種を作ること
（背景は [references/selection-criteria.md](references/selection-criteria.md) 参照）。

## 大方針

- **勝手に突き進まない。** 各チェックポイントでユーザーに確認する。特に Evernote の探索範囲、
  提案件数、ファイル書き出しの前は必ず一声かける。
- 選別の物差しは常に [references/selection-criteria.md](references/selection-criteria.md) に従う。
- 重い走査は `podcast-idea-miner` サブエージェントに隔離し、本体コンテキストを汚さない。

## 手順

### 0. 前提確認
- 作業ディレクトリは repo ルート（`external-brain-workspace`）想定。
- X アーカイブが `twitter-archive/extracted/data/tweets.js` にあることを確認する。
  無ければユーザーにアーカイブの場所を尋ねる。
- Evernote も使うなら `/mcp` で evernote が connected か確認する。未接続なら
  「Evernote は使わず X だけで進めますか？」と確認する。

### 1. ツイートの機械的前処理
`scripts/extract_tweets.py` を実行し、RT・他人へのリプライ・短い反応・重複を落とした
候補 JSON を作る。

```bash
python3 .claude/skills/podcast-neta/scripts/extract_tweets.py \
  --tweets twitter-archive/extracted/data/tweets.js \
  --account twitter-archive/extracted/data/account.js \
  --out podcast-ideas/.cache/tweets_candidates.json \
  --min-len 15
```

出力される件数（`kept`）を控える。ここはまだ意味的な選別はしていない
（構造ノイズを落としただけ）ことをユーザーに伝える。

### 2. 意味的な選別（マイナーを並列で走らせる）
候補が数百件あると 1 エージェントでは宝石を見落とす。**チャンク分割して
`podcast-idea-miner` を並列起動**する（1メッセージに複数の Agent 呼び出しを並べる）。

- チャンクサイズの目安: 1 チャンク **約 250 件**。`kept` 件数から必要チャンク数を計算する。
- 各マイナーへの指示（tweets モード）:
  - `podcast-ideas/.cache/tweets_candidates.json` を Read
  - 担当インデックス範囲（例: 0〜249）だけを評価
  - [references/selection-criteria.md](references/selection-criteria.md) の全文を選別基準として渡す
  - 指定 JSON 形式で score 3 以上のものだけ返す
- Evernote を使う場合、`evernote` モードのマイナーを 1 つ追加起動する:
  - テーマ種の例:「生き方 価値観」「後悔 挫折 転機」「こだわり 偏愛」「時間 待つこと 効率」
    「孤独 承認 つながり」「ものづくり 個人開発」「クラフトビール ビール」
  - ユーザーが探索したいノートブックやテーマを指定していればそれを優先する

> Evernote を走らせる前に、探索するテーマ種でよいかユーザーに一度確認するとよい。

### 3. 統合・クラスタリング（本体で実施）
各マイナーが返した JSON を集約し、本体エージェントが:
- 重複（同じ趣旨の引用）をまとめる
- `theme_hint` を手がかりに **テーマ（クラスタ）** を作る。各テーマに根拠 2〜5 件をぶら下げる
- score と "語れる熱量" で全体を並べ替える
- **単発の種**（1ツイート＝1エピソード）と **テーマ**（複数を束ねた柱）の両方を用意する

件数が多い場合、ユーザーに「今回は上位いくつを深掘りして提案しますか？」と確認する。

### 4. 提案の Markdown を書き出す
`podcast-ideas/YYYY-MM-DD.md`（日付は `date +%F` で取得）に、次の構成で書く。

```markdown
# Podcast ネタ提案 — YYYY-MM-DD

## テーマ（哲学の柱）
### 1. <テーマ名>
- **なぜあなたらしいか**: ...
- **語る切り口**: ...
- **タイトル案**: 「...」/「...」
- **根拠の投稿/ノート**:
  - > <引用>  （X, YYYY / Evernote「ノート名」）

## 単発の種（1投稿＝1エピソード）
### A. <ひとことラベル>
- **引用**: > <本文>  （出典）
- **語る切り口**: ...
- **タイトル案**: 「...」
```

各提案には必ず **引用元**（出典と日付）を残す。提案は "断定" ではなく
"こんなネタどうですか？" というトーンで書く。

### 5. 本体チャットで要約
書き出したファイルパスと、特に推したいネタを 3〜5 個だけ本体チャットで紹介する。
全件は貼らない（ファイルに任せる）。次にどれを深掘りするかユーザーに委ねる。

## 補足
- `podcast-ideas/` は個人的な引用を含む成果物なので、リポジトリの `.gitignore` で丸ごと除外している（手元には残るが Git 管理外）。`.cache/` はその中の中間生成物。
- 同じ日に複数回走らせる場合は上書き確認をする。
- ネタは捏造しない。すべて実在する投稿/ノートの引用に紐づける。
