---
name: note-draft
description: X の過去ツイート（twitter-archive のローカルアーカイブ）と Evernote のノートという外部脳を参照して、note.com にそのまま貼れる「Podcast の下敷きを兼ねた記事」の下書きを生成し、note-drafts/YYYY-MM-DD.md に書き出す。note を書くこと自体が Podcast のひとり語りの骨組みになる形を狙う。Podcast を始める前に note でネタを要約投稿して note / Podcast / 開発プロダクトへの流入導線を作りたいとき、ラジオ用の台本を毎回作らずに済ませたいときに使う。
---

# note 下書き生成スキル（Podcast の下敷きを兼ねる）

X の過去ツイートと Evernote のノートという2つの「外部脳」を参照し、
**note.com にそのまま貼れる記事の下書き**を生成する。ゴールは、その記事を書くこと
自体が **ひとり語り Podcast の骨組み**になっていること（背景は Issue #7、および
[references/note-criteria.md](references/note-criteria.md) 参照）。

過去の投稿・ノートから「人格のルーツになる言葉」を拾う部分は、既存の
`podcast-neta` スキルと発掘資産（`extract_tweets.py` / `podcast-idea-miner` /
`selection-criteria.md`）をそのまま流用する。このスキルはその発掘結果を
**note に貼れる記事の形に整え、ファイルに書き出す**ところに責任を持つ。

## 大方針（CLAUDE.md と一致）

- **台本は作らない。** 逐語的なセリフ台本ではなく、note 記事＝話の骨組み＋核の一言を作る。
  本番は本人がそれを見ながら自分の言葉で膨らませて話す前提（[references/note-criteria.md](references/note-criteria.md)）。
- **記事で全部言い切らない。** note で問いを立てて引き込み、深い話は Podcast に残す。
  記事は Podcast の完全なネタバレにしない。
- **捏造しない。** 各記事は必ず**実在する投稿/ノートの引用**に紐づける。
  過去の自分が言っていないことを、言ったかのように書かない。
- **勝手に突き進まない。** 探索範囲・生成本数・書き出しの各チェックポイントで一声かける。
- **一度に浴びせない。** 提案は一度に大量に出さず、数本ずつに絞る（オーナーの特性）。
- 重い走査は `podcast-idea-miner` サブエージェントに隔離し、本体コンテキストを汚さない。

## note.com への投稿について

note.com には安定した投稿 API / MCP が無い前提で運用する。このスキルの責任は
**「そのまま貼れる下書きをファイルに用意する」ところまで**。実際の note への投稿は
オーナーが `note-drafts/YYYY-MM-DD.md` からコピペして手で行う（一石二鳥の"貼るだけ"を実現する）。

> 将来 note 投稿の MCP を導入したら、tweet-draft と同じ「承認 → 投稿」フローを足す余地はある。
> それまでは自動投稿しない（そもそも手段が無い）。

## 手順

### 0. 前提確認
- 作業ディレクトリは repo ルート（`external-brain-workspace`）想定。
- X アーカイブが `twitter-archive/extracted/data/tweets.js` にあることを確認する。
  無ければオーナーにアーカイブの場所を尋ねる。
- **今回どの外部脳を使うか**を確認する（X アーカイブだけ / Evernote だけ / 両方）。
  Evernote を使うなら `/mcp` で evernote が connected か確認する。

### 1. ネタの発掘（既存資産を流用）
`podcast-neta` スキルの手順 1〜2 と同じ要領で、外部脳からネタを発掘する。

1. **ツイートの機械的前処理**（X を使う場合）:

   ```bash
   python3 .claude/skills/podcast-neta/scripts/extract_tweets.py \
     --tweets twitter-archive/extracted/data/tweets.js \
     --account twitter-archive/extracted/data/account.js \
     --out note-drafts/.cache/tweets_candidates.json \
     --min-len 15
   ```

   出力件数（`kept`）を控える。ここはまだ意味的な選別はしていないことを伝える。

2. **意味的な選別**: 候補を約 250 件ずつのチャンクに分け、`podcast-idea-miner` を
   **並列起動**する（1メッセージに複数の Agent 呼び出しを並べる）。
   - 選別基準として [../podcast-neta/references/selection-criteria.md](../podcast-neta/references/selection-criteria.md) の全文を渡す。
   - Evernote を使う場合は `evernote` モードのマイナーを 1 つ追加する。
     テーマ種の例:「生き方 価値観」「後悔 挫折 転機」「こだわり 偏愛」「ものづくり 個人開発」。
   - マイナーは score 3 以上のネタを構造化 JSON で返す（捏造しない）。

> 発掘の詳細な運用は `podcast-neta/SKILL.md` を正とする。重複させず参照する。
> ここは「1記事 = 1エピソード」になる、語り応えのあるネタを優先して選ぶ。

### 2. 記事への整形（本体で実施）
発掘された各ネタ（`quote` / `why` / `angle` / `theme_hint`）を、
[references/note-criteria.md](references/note-criteria.md) の物差しに従って
**note に貼れる記事本文**に整形する。

- 記事の型は **フック → 本題（気づき/原体験/こだわり）→ 問い・余白 → Podcast への導線**。
- 元の引用の**主旨を保つ**。過去の自分の考えを、今の一人称で言い直す。
  引用の意味を歪めたり、言っていない主張を足したりしない。
- **逐語台本にしない。** 骨組みと核の一言に留め、記事で結論まで言い切らない。
- 800〜1,500 字程度を基本。1つのネタから**切り口違いで最大2案**まで作ってよい。
- **タイトル案を2つ**添える（note のタイトルは流入を左右する）。

各記事には、**必ず出典（元ツイートの日付 / Evernote ノート名）を併記**する。

### 3. 下書きファイルに書き出す
`note-drafts/YYYY-MM-DD.md`（日付は `date +%F`）に、次の構成で書く。
**note に貼る本文と、メタ情報（出典・狙い）を明確に分ける**（本文だけコピペできるように）。

```markdown
# note 下書き — YYYY-MM-DD

## 1. <ひとことラベル>（テーマ: <theme_hint>）

**タイトル案**: 「<案A>」／「<案B>」

--- ここから note に貼る本文（案A）---

## <記事内の見出し>

<フック 2〜3行>

<本題。引用を核にした一人称の語り>

<問い・余白。結論は言い切らない>

> この話、Podcast でもう少し深く話します。

--- ここまで ---

（切り口違いの案Bがあれば同じ形で続ける）

- **出典**: > <元の引用>  （X, YYYY / Evernote「ノート名」）
- **Podcast での深掘りポイント**: <記事で言い切らず本番で語る核。1〜2行>
- **狙い**: <この記事で人格のどの側面が伝わるか。1文>
```

同じ日に複数回走らせる場合は上書き確認をする。
`note-drafts/` は個人的な引用を含む成果物なので `.gitignore` で丸ごと除外する
（`podcast-ideas/` と同じ扱い。手元には残るが Git 管理外）。`.cache/` はその中の中間生成物。

### 4. 本体チャットで数本だけ提案する
書き出したファイルパスと、**特に推したい記事を 2〜3 本だけ**本体チャットで見せる。
全文は貼らない（ファイルに任せる）。そのうえでオーナーに聞く:

> このうち note に出すならどれがいいですか？（番号で / 直したい所があれば直します）

- 大量に列挙しない。今見るべき 2〜3 本に絞る（オーナーの特性）。
- オーナーが選んだら、その本文を整え直し、**"貼るだけ"の完成形**にして渡す。

## 補足
- `twitter` MCP の `search_tweets` は直近しか取れない。過去の網羅分析は必ず
  ローカルアーカイブ（`extract_tweets.py`）を使う。
- ネタは捏造しない。すべて実在する投稿/ノートの引用に紐づける。
- このスキルの成果物（note 記事）は、そのまま `podcast-neta` の深掘り対象にもなる。
  記事にした種は Podcast のエピソード候補として再利用できる。
