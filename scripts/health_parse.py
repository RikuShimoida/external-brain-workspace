#!/usr/bin/env python3
"""iPhone ヘルスケアの書き出し（export.zip）から歩数だけを読むための共通パーサー。

ヘルスケアアプリの「すべてのヘルスケアデータを書き出す」でできた zip を
health-archive/ に置いて読む。ヘルスケアには API / MCP が無いので、
Instagram / 家計と同じく公式エクスポートをローカルパースする方式。

実データで確認した構造:
  - zip の中身は apple_health_export/export.xml（約240MB）と export_cda.xml。
  - 歩数は <Record type="HKQuantityTypeIdentifierStepCount" sourceName=...
    startDate="YYYY-MM-DD hh:mm:ss +0900" value="123"/>。数分〜1時間単位の細切れ。
  - 計測元（sourceName）は iPhone と Apple Watch。同じ時間帯を両方が数えることがある。

プライバシー: export.xml には心拍・体重・健診以外の健康データも丸ごと入っている。
このパーサーは歩数（StepCount）以外を一切読まずに捨てる。zip は展開せず、
中の export.xml をストリームで逐次処理する（全体をメモリに載せない）。

health_map.py から import して使う（household_parse を household_map が
import するのと同じ流儀）。

使い方（単体実行。確認用のサマリだけ出す）:
    python3 scripts/health_parse.py
      --root パス … リポジトリのルート（既定: カレント）
"""
import argparse
import sys
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

ARCHIVE_REL = "health-archive"
EXPORT_XML = "apple_health_export/export.xml"
STEP_TYPE = "HKQuantityTypeIdentifierStepCount"


@dataclass
class StepRecord:
    date: str      # YYYY-MM-DD（記録時点の端末のローカル日付）
    source: str    # 計測元（sourceName）
    value: int


def find_export(root: Path) -> Path | None:
    """health-archive/ にある書き出し zip のうち、名前順で最後（＝最新）を返す。"""
    zips = sorted((root / ARCHIVE_REL).glob("*.zip"))
    return zips[-1] if zips else None


def parse_steps(zip_path: Path) -> list[StepRecord]:
    records: list[StepRecord] = []
    with zipfile.ZipFile(zip_path) as zf, zf.open(EXPORT_XML) as f:
        for _, el in ET.iterparse(f, events=("end",)):
            if el.tag == "Record" and el.get("type") == STEP_TYPE:
                records.append(StepRecord(
                    date=el.get("startDate", "")[:10],
                    source=el.get("sourceName", ""),
                    value=int(float(el.get("value", "0"))),
                ))
            el.clear()
    return records


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."),
                    help="リポジトリのルート（既定: カレント）")
    args = ap.parse_args()

    zip_path = find_export(args.root)
    if zip_path is None:
        print(f"書き出し zip が見つかりません: {args.root}/{ARCHIVE_REL} に置きましたか？",
              file=sys.stderr)
        return 1
    records = parse_steps(zip_path)
    dates = sorted({r.date for r in records})
    print(f"入力: {zip_path.name}", file=sys.stderr)
    print(f"歩数レコード: {len(records):,} 件", file=sys.stderr)
    if dates:
        print(f"期間: {dates[0]} 〜 {dates[-1]}（{len(dates):,} 日）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
