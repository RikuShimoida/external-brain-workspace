#!/usr/bin/env python3
"""MF ME（マネーフォワード ME）の家計 CSV を読むための共通パーサー。

MF ME Web版の「収入・支出詳細」を月単位で CSV 書き出ししたものを、
household-archive/ に置いて読む。MF ME には API / MCP が無い（MCP があるのは
別物の「マネーフォワード クラウド」）ので、LINE / Instagram と同じく
公式エクスポートをローカルパースする方式。

このリポジトリの他のソースは事業会計（freee）だが、こちらは家計（生活費）の
お金の流れ。レンズが別なので混ぜない。

実データで確認した CSV の構造:
  - 文字コードは Shift-JIS（実質 cp932）。cp932 で読む。
  - 列: 計算対象, 日付, 内容, 金額（円）, 保有金融機関, 大項目, 中項目, メモ, 振替, ID
  - 計算対象 == "1" の行だけを家計集計に使う（"0" は振替・対象外で集計除外）。
  - 金額は正＝収入 / 負＝支出。
  - 日付は "YYYY/MM/DD"。ID 列が各明細のユニークキー。

プライバシー: 内容（店名）・保有金融機関（口座・カード名）は機微情報。
この関数は行をそのまま返すが、地図・サマリ側（household_map.py）では
個別明細を出さず大項目/中項目の集計までに留める。

household_map.py から import して使う（instagram_parse を instagram_map が
import するのと同じ流儀）。

使い方（単体実行。確認用のサマリだけ出す）:
    python3 scripts/household_parse.py
      --root パス … リポジトリのルート（既定: カレント）
"""
import argparse
import csv
import glob
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# household-archive 内の CSV を拾う相対 glob（リポジトリルートからの相対）
ARCHIVE_DIR = "household-archive"
CSV_GLOB = "*.csv"

ENCODING = "cp932"  # MF ME の CSV は Shift-JIS（実質 cp932）


@dataclass
class Entry:
    """家計 CSV の1明細（計算対象=1 のみ採用）。"""

    date: str        # "YYYY/MM/DD"
    month: str       # "YYYY-MM"
    content: str     # 内容（店名など・機微）
    amount: int      # 金額（正＝収入 / 負＝支出）
    account: str     # 保有金融機関（口座・カード名・機微）
    major: str       # 大項目
    minor: str       # 中項目
    memo: str        # メモ
    transfer: bool   # 振替フラグ
    uid: str         # ID（ユニークキー）

    @property
    def is_income(self) -> bool:
        return self.amount > 0

    @property
    def is_expense(self) -> bool:
        return self.amount < 0


def _month_of(date_str: str) -> str:
    """"YYYY/MM/DD" → "YYYY-MM"。パースできなければ空文字。"""
    parts = date_str.split("/")
    if len(parts) >= 2 and parts[0] and parts[1]:
        return f"{parts[0]}-{parts[1].zfill(2)}"
    return ""


def _to_int(amount_str: str) -> int:
    """金額文字列を int に。カンマ・空白を除去する。"""
    s = amount_str.replace(",", "").replace(" ", "").strip()
    if not s:
        return 0
    return int(s)


def parse_file(path: str) -> list[Entry]:
    """1つの CSV を読み、計算対象=1 の行だけ Entry にして返す。"""
    entries: list[Entry] = []
    with open(path, encoding=ENCODING, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 列名は全角括弧を含むため、get で拾う。キーが無い壊れ行はスキップ。
            target = (row.get("計算対象") or "").strip()
            if target != "1":
                continue  # 0 は振替・対象外＝集計除外
            date = (row.get("日付") or "").strip()
            entries.append(
                Entry(
                    date=date,
                    month=_month_of(date),
                    content=(row.get("内容") or "").strip(),
                    amount=_to_int(row.get("金額（円）") or "0"),
                    account=(row.get("保有金融機関") or "").strip(),
                    major=(row.get("大項目") or "").strip(),
                    minor=(row.get("中項目") or "").strip(),
                    memo=(row.get("メモ") or "").strip(),
                    transfer=((row.get("振替") or "0").strip() == "1"),
                    uid=(row.get("ID") or "").strip(),
                )
            )
    return entries


def parse_all(root: Path = Path(".")) -> list[Entry]:
    """household-archive/*.csv をすべて読み、計算対象=1 の明細を集めて返す。

    同じ ID の明細は重複排除する（複数月 CSV の期間が重なっても安全なように）。
    """
    pattern = os.path.join(str(root), ARCHIVE_DIR, CSV_GLOB)
    seen: set[str] = set()
    entries: list[Entry] = []
    for path in sorted(glob.glob(pattern)):
        for e in parse_file(path):
            if e.uid and e.uid in seen:
                continue
            if e.uid:
                seen.add(e.uid)
            entries.append(e)
    return entries


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."),
                    help="リポジトリのルート（既定: カレント）")
    args = ap.parse_args()

    entries = parse_all(args.root)
    if not entries:
        print(f"データが見つかりません: {args.root}/{ARCHIVE_DIR} に CSV を置きましたか？",
              file=sys.stderr)
        return 1

    income = sum(e.amount for e in entries if e.is_income)
    expense = sum(-e.amount for e in entries if e.is_expense)
    months = sorted({e.month for e in entries if e.month})
    print(f"明細（計算対象=1）: {len(entries):,} 件", file=sys.stderr)
    print(f"対象月: {', '.join(months)}", file=sys.stderr)
    print(f"収入合計: {income:,} 円 / 支出合計: {expense:,} 円 / 収支: {income - expense:,} 円",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
