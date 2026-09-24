---
name: freee
description: freee の未処理明細（消込待ち）を分析し、既存ルールに当たらない明細の勘定科目をオーナー本人の文脈（Gmail・カレンダー・家計）で推定して、freee の自動登録ルールを増やす。確定申告の帳簿づけを「もう一人の自分」に任せるためのスキル。既定はドライランで、ルールを作るのはオーナーの承認後だけ。取引の削除・登録はしない。
when_to_use: 「freee の未処理を片付けて」「帳簿つけて」「freee のルール増やして」「/freee」などの発言時。月末や確定申告の前に未処理明細を減らしたいとき。税額の試算や試算表を見たいだけなら freee MCP（読み取り）で足りるので使わない。
---

# freee 帳簿づけスキル（自動登録ルールを増やす）

旧リポジトリ freee-transaction-agent（Vercel で毎月28日に自動実行）を外部脳へ移したもの（#75）。
自動実行はやめて、手で呼び、**書く前に毎回オーナーに見せる**形にした。

## 絶対ルール

1. **書けるのは自動登録ルールの作成だけ。** 取引（deal）の登録・更新・削除はしない。
   2026-07-13、取引の削除スクリプトが口座の絞り込みを無視され、全口座の 578件を誤削除した。
   消した取引の元の勘定科目は戻らない。ルールなら作り直せる。
2. **既定はドライラン。`--apply` はオーナーの承認を得てから。** 承認は1回ごと。前回の承認を流用しない。
3. **書く前に元の状態を保存する。** `freee_rules.py --apply` が自動で `snapshot_before_*.json` を書き、
   無ければ `freee_client.py` が書き込みを拒む。この仕組みを迂回するコードを足さない。
4. **このリポジトリは公開。** 明細・店名・金額は `freee-archive/`（Git 管理外）の中だけで扱う。
   チャットに出すのは費目・件数・キーワード程度にし、Git 管理下のファイルに書かない。
5. **並列に流さない。** freee への書き込みは MCP 書き込みと同じく司令塔だけが直列で行う。

## 前提

- `.env` に `FREEE_CLIENT_ID` / `FREEE_CLIENT_SECRET`、認証済みの
  `freee-archive/_secrets/tokens.json`（無ければ `python3 scripts/freee_token.py` をオーナーがターミナルで。
  認可コードをチャットに貼らせない）。
- 疎通確認: `python3 scripts/freee_token.py --check`

## 手順

### 1. 分析（読むだけ）

```bash
python3 scripts/freee_analyze.py
```

stderr の件数（未処理 / 一致 / 事業主貸 / 未マッチ / 除外）をオーナーに伝え、最後の行の
`freee-archive/runs/<日時>` を控える。未マッチが 0 件なら「新しく作るルールはありません」で終了。

### 2. 費目の推定（隔離）

`freee-txn-classifier` エージェントに `run_dir` を渡して `unmatched.tsv` を埋めさせる。
50 行を超えるときは行範囲で分けて順番に呼ぶ（同じファイルを書くので**並列にしない**）。
返ってきた JSON の件数（high / medium / low / 事業主貸 / 空欄）を控える。

### 3. 候補を見せる（ドライラン）

```bash
python3 scripts/freee_rules.py freee-archive/runs/<日時>
```

出てきた候補表と「作らない」内訳をオーナーに見せる。多いときは上位10件と件数だけ。
あわせて **act の意味**を一言添える：

- act=0（既定）… freee が「こうでは？」と提案するだけ。オーナーが画面で確定する
- act=1（`--auto`）… 確度 high だけ freee が自動で登録・消込する

### 4. 承認を取ってから作る

次を明示して承認を求める（`.claude/rules/command-rules.md` の確認時の説明義務）:

- 実行するコマンド全文（`--auto` の有無を含む）
- 作るルールの件数と act の内訳
- 作成前の状態は `snapshot_before_*.json` に保存されること
- 取り消しは freee の画面でルールを削除すれば戻せること（取引は作らない）

承認が来たら:

```bash
python3 scripts/freee_rules.py freee-archive/runs/<日時> --apply        # act=0
python3 scripts/freee_rules.py freee-archive/runs/<日時> --apply --auto # 確度 high を act=1
```

初回は `--auto` なしを勧める。freee の提案の当たり具合を見てから `--auto` に切り替える。

### 5. 報告（短く）

- 作ったルールの件数 / 失敗件数（`applied_*.json`）
- グレー（作らなかったもの）の件数と主な理由。**事業主貸はオーナーが freee の画面で**ルール登録する
- 次にオーナーがやること：freee の「自動で経理」画面で提案を確認する

## やってはいけないこと

- 承認なしの `--apply`
- `freee_client.py` に削除・更新・取引登録のメソッドを足すこと（必要になったら別 Issue で、1件ずつ確認する仕組みと一緒に）
- freee MCP の書き込み系ツールを使うこと（読み取りは可）
- 明細・金額・店名を Git 管理下に書くこと
