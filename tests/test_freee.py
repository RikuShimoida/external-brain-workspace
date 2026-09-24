#!/usr/bin/env python3
"""freee_analyze.py / freee_rules.py / freee_client.py のテスト（#75）。

このリポジトリは公開なので、明細・店名・金額はすべて架空。freee には接続しない。
特に「スナップショット無しでは書けない」「口座で絞った明細に別口座が混ざったら止まる」
（7/13 の誤削除の教訓）をここで固定する。

実行: python3 -m pytest tests/ もしくは python3 tests/test_freee.py
"""
from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import freee_analyze as fa  # noqa: E402
import freee_client as fc  # noqa: E402
import freee_rules as fr  # noqa: E402


def _txn(i, desc, wallet="テストカード", wtype="credit_card", side="expense", amount=1000):
    return {"id": i, "date": "2026-01-01", "description": desc, "amount": amount, "entry_side": side,
            "walletable_type": wtype, "walletable_id": 1, "status": 1,
            "_wallet_name": wallet, "_wallet_type": wtype}


RULES = [
    {"description": "テスト書店", "account_item_name": "新聞図書費", "tax_name": "課対仕入10%", "active": True},
    {"description": "テスト電力", "account_item_name": "水道光熱費", "entry_side_str": "expense"},
    {"description": "テスト電力", "account_item_name": "事業主貸"},
    {"description": "テスト年金", "account_item_name": "事業主貸"},
    {"description": "停止中の店", "account_item_name": "消耗品費", "active": False},
]
OWNER_DRAW = {"事業主貸"}


@contextmanager
def _raises(exc):
    """pytest.raises の代わり（このリポジトリは標準ライブラリのみ）。"""
    try:
        yield
    except exc:
        return
    raise AssertionError(f"{exc.__name__} が送出されなかった")


def test_norm_揃える():
    assert fa.norm("ＡＢＣ　ｄｅｆ") == "abcdef"
    assert fa.norm("カ－ドサ―ビス") == fa.norm("カ-ドサ-ビス")


def test_カード引落の合計行は銀行明細だけ除外():
    assert fa.is_card_settlement(_txn(1, "ﾗｸﾃﾝｶ-ド 楽天カード", wtype="bank_account"))
    assert not fa.is_card_settlement(_txn(2, "楽天カード", wtype="credit_card"))


def test_analyze_4分類():
    txns = [
        _txn(1, "テスト書店 渋谷"),                       # 一意にマッチ
        _txn(2, "テスト電力 1月分"),                      # 費目が割れる → unmatched(ambiguous)
        _txn(3, "テスト年金"),                            # 事業主貸
        _txn(4, "知らない店"),                            # 未マッチ
        _txn(5, "停止中の店"),                            # 無効ルールは使わない → 未マッチ
        _txn(6, "JCB 引落", wtype="bank_account"),        # 除外
    ]
    r = fa.analyze(txns, RULES, OWNER_DRAW)
    assert [x["txn"]["id"] for x in r["matched"]] == [1]
    assert [x["txn"]["id"] for x in r["owner_draw"]] == [3]
    assert [x["txn"]["id"] for x in r["excluded"]] == [6]
    un = {x["txn"]["id"]: x["ambiguous"] for x in r["unmatched"]}
    assert set(un) == {2, 4, 5}
    assert un[2] == ["水道光熱費", "事業主貸"]


def _row(txn_id, item, conf="high", kw="知らない店", owner="false"):
    return {"txn_id": str(txn_id), "account_item_name": item, "confidence": conf,
            "rule_keyword": kw, "is_owner_draw": owner, "comment": ""}


def test_候補の組み立て():
    txns = {i: _txn(i, "知らない店") for i in range(1, 9)}
    rows = [
        _row(1, "消耗品費"),                           # 作る
        _row(2, "消耗品費"),                           # 同じ店 → 1ルールにまとめる
        _row(3, "事業主貸", owner="true"),             # 事業主貸
        _row(4, "消耗品費", conf="low", kw="別の店"),   # 確度 low
        _row(5, "消耗品費", kw=""),                    # キーワードなし
        _row(6, "存在しない費目", kw="店6"),            # freee に無い費目
        _row(7, "新聞図書費", kw="テスト書店"),          # 既存ルールと重複
        _row(8, ""),                                   # 未分類（対象外）
    ]
    txns[7] = _txn(7, "テスト書店", wallet="")
    existing = [{"description": "テスト書店", "account_item_name": "新聞図書費", "walletable": "",
                 "tax_name": "課対仕入10%"}]
    resolve = fr.build_tax_resolver([{"name": "消耗品費", "default_tax_code": 136}],
                                    [{"code": 136, "name_ja": "課対仕入10%"}], existing)
    names = {"消耗品費", "新聞図書費", "事業主貸"}
    create, skip = fr.build_candidates(rows, txns, existing, resolve, names)
    assert [c["txn_id"] for c in create] == [1]
    assert create[0]["candidate"]["act"] == 0  # --auto なしは提案のみ
    reasons = sorted(s["reason"].split("(")[0] for s in skip)
    assert len(skip) == 6
    assert "既存ルールと重複" in reasons

    create_auto, _ = fr.build_candidates(rows[:1], txns, existing, resolve, names, auto=True)
    assert create_auto[0]["candidate"]["act"] == 1


def test_スナップショット無しでは書けない(tmp_path):
    with _raises(fc.WriteGuardError):
        fc.check_snapshot(None)
    with _raises(fc.WriteGuardError):
        fc.check_snapshot(tmp_path / "無い.json")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"to_create": []}), encoding="utf-8")
    with _raises(fc.WriteGuardError):
        fc.check_snapshot(bad)
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"user_matchers": []}), encoding="utf-8")
    fc.check_snapshot(ok)


def test_create_user_matcherはスナップショット無しで送信しない():
    client = fc.FreeeClient.__new__(fc.FreeeClient)  # 通信しないよう初期化を飛ばす
    sent = []
    client._send = lambda *a, **k: sent.append(a)
    client._company_id = 1
    with _raises(fc.WriteGuardError):
        client.create_user_matcher({"description": "x"}, snapshot=None)
    assert sent == []


def test_読み取りクライアントはGET以外を送れない():
    client = fc.FreeeClient.__new__(fc.FreeeClient)
    methods = []
    client._send = lambda method, *a, **k: methods.append(method) or {}
    client.request("/api/1/deals")
    assert methods == ["GET"]
    assert not any(hasattr(client, m) for m in ("delete", "delete_deal", "create_deal", "put"))


def test_別口座の明細が混ざったら止める():
    txns = [{"walletable_type": "credit_card", "walletable_id": 1},
            {"walletable_type": "credit_card", "walletable_id": 2}]
    with _raises(RuntimeError):
        fc.check_same_wallet(txns, "credit_card", 1)
    fc.check_same_wallet(txns[:1], "credit_card", 1)


def _run():
    import tempfile

    failures = 0
    for name, fn in list(globals().items()):
        if not name.startswith("test_"):
            continue
        try:
            if "tmp_path" in fn.__code__.co_varnames:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print(f"  OK  {name}")
        except AssertionError as e:
            failures += 1
            print(f" FAIL {name}: {e}")
    if failures:
        print(f"\n{failures} 件失敗")
        return 1
    print("\n全テスト通過")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
