#!/usr/bin/env python3
"""weekly_reflection.py の回帰テスト。

実ノートの見出しは <h2>/<h3>、配下は <li><div>...</div></li> という構造。
見出し検出を div/b/span まで広げると、見出し直後の <li> 内 <div> を「次の見出し」と
誤検出して配下が空になり、全項目0件になるバグがあった（Issue #47）。
このテストは、その実構造のダミーで抽出・日付付与・重複保持を固定する。

実行: python3 -m pytest tests/ もしくは python3 tests/test_weekly_reflection.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import weekly_reflection as wr  # noqa: E402


def _note(title: str, well_items: list[str], fail_items: list[str]) -> dict:
    """実ノートに寄せた ENML を組み立てる。配下は <li><div>...</div></li>。"""

    def ol(items):
        lis = "".join(f"<li><div>{t}</div></li>" for t in items)
        return f"<ol>{lis}</ol>"

    content = (
        '<h2><b>今日、運が良かったこと　俺のため</b></h2>'
        "<ol><li><div>朝散歩できた</div></li></ol><hr/>"
        '<h2><b>今日、運が悪かったこと　俺のため</b></h2><ol></ol><hr/>'
        '<h2><b>今日、うまくいったことと、原因　俺のため</b></h2>'
        f"{ol(well_items)}<hr/>"
        '<h2><b>今日、失敗したプロセス、原因　俺のため</b></h2>'
        f"{ol(fail_items)}<hr/>"
        '<h2><b>今日、失敗した結果、原因　俺のため</b></h2>'
        "<ol><li><div>寝る前スマホ</div></li></ol><hr/>"
    )
    return {"title": title, "content": content}


def test_extracts_from_real_structure(tmp_path):
    """<li><div> 構造から項目を拾えること（0件バグの回帰）。"""
    note = _note(
        "今日やること - 2026年9月5日",
        well_items=["設計を先に書いた", "こまめに休んだ"],
        fail_items=["確認を飛ばした"],
    )
    p = tmp_path / "n0905.json"
    p.write_text(json.dumps(note, ensure_ascii=False), encoding="utf-8")

    results, dates = wr.collect([p])
    assert len(results["luck_good"]) == 1
    assert len(results["went_well"]) == 2
    assert len(results["fail_process"]) == 1
    assert len(results["fail_result"]) == 1
    # 日付が付く
    assert all(d is not None for d, _t in results["went_well"])


def test_duplicates_kept_and_dated(tmp_path):
    """同じ文言が複数日に出たら、まとめず全件・日付で区別されること。"""
    n1 = _note("今日やること - 2026年9月3日", ["設計を先に書いた"], [])
    n2 = _note("今日やること - 2026年9月5日", ["設計を先に書いた"], [])
    p1 = tmp_path / "a.json"
    p2 = tmp_path / "b.json"
    p1.write_text(json.dumps(n1, ensure_ascii=False), encoding="utf-8")
    p2.write_text(json.dumps(n2, ensure_ascii=False), encoding="utf-8")

    results, _dates = wr.collect([p2, p1])  # わざと逆順で渡す
    well = results["went_well"]
    assert len(well) == 2  # まとめられていない
    # 日付昇順（9/3 が先）
    assert (well[0][0].month, well[0][0].day) == (9, 3)
    assert (well[1][0].month, well[1][0].day) == (9, 5)

    report = wr.build_report(results, wr._monday_of(min(_d for _d, _ in well)))
    assert "9/3　設計を先に書いた" in report
    assert "9/5　設計を先に書いた" in report


def test_title_date_formats():
    """タイトルの2形式（YYYY年M月D日 / @YYYY-MM-DD）を読めること。"""
    import datetime as dt

    assert wr.parse_date_from_title("今日やること - 2026年9月5日") == dt.date(2026, 9, 5)
    assert wr.parse_date_from_title("今日やること - @2026-09-06") == dt.date(2026, 9, 6)
    assert wr.parse_date_from_title("タイトルに日付なし") is None


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
