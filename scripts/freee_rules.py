#!/usr/bin/env python3
"""Claude が費目を埋めた unmatched.tsv から、freee の自動登録ルールの候補を組み、作る。

旧リポジトリ freee-transaction-agent の lib/rule-creator.mjs を移植したもの（#75）。
取引（deal）は直接登録しない。deal を API で作っても元の明細は未処理のまま残り二重計上になる。
ルールを作れば freee 本来の「自動で経理」が登録・消込をする。

既定はドライラン（候補を表示するだけで freee に書かない）。
--apply のときだけ書く。その前に必ず、作成前のルール一覧と作る候補を
<run>/snapshot_before.json に保存する（保存しないと freee_client が書き込みを拒む）。

act（ルールの動き）:
  0 = 取引を推測（freee が提案するだけ。オーナーが画面で確定）… 既定
  1 = 取引を自動登録（明細が自動で消込される）… --auto のとき確度 high だけ

作らないもの（グレー。オーナーが freee の画面で判断する）:
  事業主貸 / 確度 low / ルール化キーワードなし / 税区分を解決できない / 既存ルールと重複

使い方:
    python3 scripts/freee_rules.py freee-archive/runs/<日時>          … ドライラン
    python3 scripts/freee_rules.py freee-archive/runs/<日時> --apply  … 作る（act=0）
    python3 scripts/freee_rules.py freee-archive/runs/<日時> --apply --auto
      --root パス   … リポジトリのルート（既定: カレント）
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

from freee_analyze import OWNER_DRAW_CATEGORY
from freee_client import FreeeApiError, FreeeClient


def build_tax_resolver(account_items: list[dict], taxes: list[dict], existing_rules: list[dict]):
    """費目名 → 税区分名。既存ルールで実際に使われている組み合わせを最優先で流用する。"""
    from_rules: dict[str, str] = {}
    for r in existing_rules:
        name, tax = r.get("account_item_name"), r.get("tax_name")
        if name and tax and name not in from_rules:
            from_rules[name] = tax
    code_to_name = {t["code"]: (t.get("name_ja") or t.get("name")) for t in taxes}
    from_items: dict[str, str] = {}
    for a in account_items:
        nm = code_to_name.get(a.get("default_tax_code"))
        if a.get("name") and nm:
            from_items[a["name"]] = nm
    return lambda item: from_rules.get(item) or from_items.get(item)


def _rule_key(r: dict) -> str:
    return f"{(r.get('description') or '').strip()}|{r.get('account_item_name') or ''}|{r.get('walletable') or ''}"


def read_classified(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def build_candidates(rows: list[dict], txns_by_id: dict[int, dict], existing_rules: list[dict],
                     resolve_tax, account_item_names: set[str], auto: bool = False):
    """分類済みの行からルール候補を組む。まだ作らない。→ (create, skip)"""
    existing = {_rule_key(r) for r in existing_rules}
    create: list[dict] = []
    skip: list[dict] = []
    for row in rows:
        item = (row.get("account_item_name") or "").strip()
        if not item:
            continue  # 未分類の行（Claude が埋めていない）は対象外
        txn = txns_by_id.get(int(row["txn_id"]))
        keyword = (row.get("rule_keyword") or "").strip()
        conf = (row.get("confidence") or "").strip()

        def _skip(reason: str) -> None:
            skip.append({"reason": reason, "row": row})

        if txn is None:
            _skip("元の明細が source.json に無い")
        elif item not in account_item_names:
            _skip(f"freee に無い費目名({item})")
        elif not keyword:
            _skip("ルール化キーワードなし")
        elif (row.get("is_owner_draw") or "").strip().lower() == "true" or item == OWNER_DRAW_CATEGORY:
            _skip("事業主貸（オーナーが freee の画面で判断）")
        elif conf not in ("high", "medium"):
            _skip(f"確度{conf or '未記入'}")
        elif not resolve_tax(item):
            _skip(f"税区分を解決できない({item})")
        else:
            cand = {
                "description": keyword,
                "account_item_name": item,
                "tax_name": resolve_tax(item),
                "walletable": txn["_wallet_name"],
                "entry_side_str": txn["entry_side"],
                "condition": 0,  # 部分一致
                "act": 1 if auto and conf == "high" else 0,
                "active": True,
                "priority": 10,
                "qualified_invoice_setting": "non_qualified",
            }
            key = _rule_key(cand)
            if key in existing:
                _skip("既存ルールと重複")
            else:
                existing.add(key)  # 同じ店が何行あっても1ルール
                create.append({"candidate": cand, "txn_id": txn["id"], "confidence": conf})
    return create, skip


def print_plan(create: list[dict], skip: list[dict]) -> None:
    print("| # | キーワード | 費目 | 口座 | act | 確度 |")
    print("|---|---|---|---|---|---|")
    for i, c in enumerate(create, 1):
        k = c["candidate"]
        print(f"| {i} | {k['description']} | {k['account_item_name']} | {k['walletable']} | {k['act']} | {c['confidence']} |")
    reasons: dict[str, int] = {}
    for s in skip:
        reasons[s["reason"]] = reasons.get(s["reason"], 0) + 1
    print(f"\n作成候補 {len(create)} 件 / 作らない {len(skip)} 件"
          + ("（" + "、".join(f"{r} {n}" for r, n in reasons.items()) + "）" if reasons else ""))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", help="freee_analyze.py が作った freee-archive/runs/<日時>")
    ap.add_argument("--root", default=".")
    ap.add_argument("--apply", action="store_true", help="実際にルールを作る（既定はドライラン）")
    ap.add_argument("--auto", action="store_true", help="確度 high を act=1（自動登録）で作る")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    run_dir = (root / args.run_dir).resolve()

    source = json.loads((run_dir / "source.json").read_text(encoding="utf-8"))
    rows = read_classified(run_dir / "unmatched.tsv")
    txns_by_id = {t["id"]: t for t in source["unmatched_txns"]}
    account_items = source["account_items"]
    names = {a["name"] for a in account_items}

    client = FreeeClient(root) if args.apply else None
    # 書くときは analyze 後にルールが増えている可能性があるので、最新のルール一覧で重複を判定する
    existing = client.get_user_matchers() if client else source["user_matchers"]
    resolve_tax = build_tax_resolver(account_items, source["taxes"], existing)
    create, skip = build_candidates(rows, txns_by_id, existing, resolve_tax, names, auto=args.auto)
    print_plan(create, skip)

    if not args.apply:
        print("\nドライラン: freee には何も書いていません（作るときは --apply）", file=sys.stderr)
        return
    if not create:
        print("作るルールがありません", file=sys.stderr)
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    snapshot = run_dir / f"snapshot_before_{stamp}.json"
    snapshot.write_text(json.dumps({
        "taken_at": datetime.now().isoformat(timespec="seconds"),
        "user_matchers": existing,
        "to_create": create,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"作成前の状態を保存: {snapshot.relative_to(root)}", file=sys.stderr)

    applied = []
    for c in create:
        try:
            res = client.create_user_matcher(c["candidate"], snapshot=snapshot)
            applied.append({**c, "result": res})
        except FreeeApiError as e:
            applied.append({**c, "error": str(e)})
    (run_dir / f"applied_{stamp}.json").write_text(json.dumps(applied, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for a in applied if "error" not in a)
    print(f"ルール作成 {ok} 件 / 失敗 {len(applied) - ok} 件（結果: applied_{stamp}.json）", file=sys.stderr)


if __name__ == "__main__":
    main()
