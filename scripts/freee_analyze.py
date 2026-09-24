#!/usr/bin/env python3
"""freee の未処理明細を既存の自動登録ルールと照合し、費目推定の下ごしらえをする（読むだけ）。

旧リポジトリ freee-transaction-agent の lib/analyzer.mjs を移植したもの（#75）。
freee には何も書かない。

未処理明細（status=1）を4つに分ける:
  matched   … 既存ルールが一意にマッチ（事業主貸以外）→ freee の「自動で経理」に任せる
  owner_draw… 既存ルールが事業主貸にマッチ
  unmatched … ルール未マッチ、または複数ルールで費目が割れる → Claude が費目を推定する
  excluded  … 銀行明細に出るカード引き落としの合計行（カード側の明細と二重計上になる）

出力（freee-archive/runs/<日時>/。Git 管理外）:
  unmatched.tsv … 未マッチ明細。右側の空欄（account_item_name 〜 comment）を Claude が埋める
  source.json   … ルール作成に要る元データ（明細・ルール・費目・税区分）
  summary.json  … 件数

使い方:
    python3 scripts/freee_analyze.py
      --root パス   … リポジトリのルート（既定: カレント）
      --dry-run     … 書き出さず件数だけ出す
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from freee_client import ARCHIVE_REL, FreeeClient

RUNS_REL = f"{ARCHIVE_REL}/runs"

OWNER_DRAW_CATEGORY = "事業主貸"

# カード引き落とし合計行の判定キーワード（銀行明細のみ対象）
CARD_SETTLEMENT_KEYWORDS = [
    "カ-ドサ-ビス", "カードサービス",
    "PAYPAYカ-ド", "PAYPAYカード", "ペイペイカ-ド",
    "ラクテンカ-ド", "楽天カード",
    "ミツイスミトモカ-ド", "三井住友カード",
    "セゾン", "トヨタフアイナンス", "トヨタファイナンス",
    "ジエ-シ-ビ-", "ＪＣＢ", "JCB",
    "イオンクレジット", "エポスカ-ド", "エポスカード",
]

# Claude が埋める列（freee_rules.py が読む）
CLASS_COLUMNS = ["account_item_name", "is_owner_draw", "confidence", "rule_keyword", "comment"]
TSV_COLUMNS = ["txn_id", "date", "wallet", "wallet_type", "entry_side", "amount", "description",
               "ambiguous"] + CLASS_COLUMNS

_ZEN = {c: chr(ord(c) - 0xFEE0) for c in
        "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ０１２３４５６７８９"}
_TRANS = str.maketrans({**_ZEN, "−": "-", "ー": "-", "―": "-", "－": "-"})


def norm(s: str | None) -> str:
    """全角英数・長音を揃え、小文字化して空白を消す（素朴な部分一致照合用）。"""
    return re.sub(r"\s+", "", (s or "").translate(_TRANS).lower())


def is_card_settlement(txn: dict) -> bool:
    if txn.get("_wallet_type") != "bank_account":
        return False
    d = norm(txn.get("description"))
    return any(norm(kw) in d for kw in CARD_SETTLEMENT_KEYWORDS)


def match_rules(txn: dict, rules: list[dict]) -> list[dict]:
    desc = norm(txn.get("description"))
    hits = []
    for r in rules:
        if r.get("entry_side_str") and r["entry_side_str"] != txn.get("entry_side"):
            continue
        if r.get("walletable") and norm(r["walletable"]) != norm(txn.get("_wallet_name")):
            continue
        if r.get("min_amount") is not None and txn.get("amount", 0) < r["min_amount"]:
            continue
        if r.get("max_amount") is not None and txn.get("amount", 0) > r["max_amount"]:
            continue
        kw = norm(r.get("description"))
        if kw and kw in desc:
            hits.append(r)
    return hits


def analyze(txns: list[dict], rules: list[dict], owner_draw_items: set[str]) -> dict[str, list[dict]]:
    active = [r for r in rules if r.get("active") is not False]
    out: dict[str, list[dict]] = {"matched": [], "owner_draw": [], "unmatched": [], "excluded": []}
    for txn in txns:
        if is_card_settlement(txn):
            out["excluded"].append({"txn": txn, "reason": "カード引き落とし合計行（二重計上防止）"})
            continue
        hits = match_rules(txn, active)
        items = list(dict.fromkeys(h.get("account_item_name") for h in hits))
        if not hits:
            out["unmatched"].append({"txn": txn, "ambiguous": []})
        elif len(items) > 1:
            out["unmatched"].append({"txn": txn, "ambiguous": items})
        elif items[0] in owner_draw_items:
            out["owner_draw"].append({"txn": txn, "item": items[0]})
        else:
            out["matched"].append({"txn": txn, "item": items[0], "rule": hits[0]})
    return out


def owner_draw_item_names(account_items: list[dict]) -> set[str]:
    return {a["name"] for a in account_items if a.get("account_category") == OWNER_DRAW_CATEGORY}


def write_unmatched_tsv(path: Path, unmatched: list[dict]) -> None:
    rows = sorted(unmatched, key=lambda u: -u["txn"].get("amount", 0))
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(TSV_COLUMNS)
        for u in rows:
            t = u["txn"]
            w.writerow([t["id"], t.get("date", ""), t["_wallet_name"], t["_wallet_type"], t.get("entry_side", ""),
                        t.get("amount", ""), (t.get("description") or "").replace("\t", " "),
                        " / ".join(u["ambiguous"])] + [""] * len(CLASS_COLUMNS))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    client = FreeeClient(root)
    txns = client.get_unprocessed_txns()
    rules = client.get_user_matchers()
    account_items = client.get_account_items()
    taxes = client.get_taxes()

    result = analyze(txns, rules, owner_draw_item_names(account_items))
    counts = {k: len(v) for k, v in result.items()}
    summary = {"taken_at": datetime.now().isoformat(timespec="seconds"), "unprocessed": len(txns),
               "rules": len(rules), **counts}
    print(f"未処理 {len(txns)} 件 / ルール {len(rules)} 件 → 一致 {counts['matched']} / 事業主貸 "
          f"{counts['owner_draw']} / 未マッチ {counts['unmatched']} / 除外 {counts['excluded']}", file=sys.stderr)
    if args.dry_run:
        return

    run_dir = root / RUNS_REL / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=False)
    write_unmatched_tsv(run_dir / "unmatched.tsv", result["unmatched"])
    (run_dir / "source.json").write_text(json.dumps({
        "unmatched_txns": [u["txn"] for u in result["unmatched"]],
        "user_matchers": rules,
        "account_items": account_items,
        "taxes": taxes,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"書き出し: {run_dir.relative_to(root)}/（unmatched.tsv {counts['unmatched']} 行）", file=sys.stderr)
    print(run_dir.relative_to(root))


if __name__ == "__main__":
    main()
