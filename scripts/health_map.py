#!/usr/bin/env python3
"""iPhone ヘルスケアの歩数から「地図」と月次の推移を作る。

health-archive/*.zip（ヘルスケアの書き出し）の歩数レコードを日ごとに集計し、2つを書き出す:

  health-archive/step_map.tsv
      … 1日1行の歩数（日付・歩数・採用した計測元・計測元の数）。
        健康の相談で「この時期どれくらい動いていたか」を引くための索引。毎回フル上書き。

  health-archive/step_monthly.tsv
      … 月ごと1行の推移（記録日数・1日平均・合計・最大・最小）。

二重計上の扱い: iPhone と Apple Watch（や機種変更前後の2台の iPhone）が同じ日を
両方数えていることがある。足すと水増しになるので、計測元ごとに日合計を出し、
**その日いちばん多い計測元の値だけを採用**する（ヘルスケアアプリの優先順位付けの簡易版）。

プライバシー: 歩数以外の健康データは読まない（health_parse.py が捨てる）。
健康データは成果物（Podcast / ツイート / note）に数値を勝手に出さない。

使い方:
    python3 scripts/health_map.py
      --root パス   … リポジトリのルート（既定: カレント）
      --dry-run     … 書き込まず step_monthly.tsv の内容を標準出力に出す

出力:
    上記2種のファイル（--dry-run 時は月次の内容を標準出力に）
    stderr に件数・期間・二重計上を避けた日数などのサマリ
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

from health_parse import StepRecord, find_export, parse_steps

MAP_REL = "health-archive/step_map.tsv"
MONTHLY_REL = "health-archive/step_monthly.tsv"

MAP_COLUMNS = ["date", "歩数", "採用した計測元", "計測元の数"]
MONTHLY_COLUMNS = ["month", "記録日数", "1日平均", "合計", "最大", "最小"]


def _device(source: str) -> str:
    """計測元名（端末の名前）を種類だけに丸める。端末名そのものは地図に出さない。"""
    if "Watch" in source:
        return "Apple Watch"
    if "iPhone" in source:
        return "iPhone"
    return "その他"


def daily_steps(records: list[StepRecord]) -> list[tuple[str, int, str, int]]:
    """(日付, 歩数, 採用した計測元の種類, 計測元の数) を日付順で返す。"""
    per_day: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in records:
        per_day[r.date][r.source] += r.value
    rows = []
    for date in sorted(per_day):
        by_source = per_day[date]
        best = max(by_source, key=lambda s: by_source[s])
        rows.append((date, by_source[best], _device(best), len(by_source)))
    return rows


def build_map(rows: list[tuple[str, int, str, int]]) -> str:
    body = "\t".join(MAP_COLUMNS) + "\n"
    for date, steps, device, n in rows:
        body += f"{date}\t{steps}\t{device}\t{n}\n"
    return body


def build_monthly(rows: list[tuple[str, int, str, int]]) -> str:
    by_month: dict[str, list[int]] = defaultdict(list)
    for date, steps, _, _ in rows:
        by_month[date[:7]].append(steps)
    body = "\t".join(MONTHLY_COLUMNS) + "\n"
    for month in sorted(by_month):
        s = by_month[month]
        body += (f"{month}\t{len(s)}\t{round(sum(s) / len(s))}\t{sum(s)}"
                 f"\t{max(s)}\t{min(s)}\n")
    return body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."),
                    help="リポジトリのルート（既定: カレント）")
    ap.add_argument("--dry-run", action="store_true",
                    help="書き込まず標準出力に出す")
    args = ap.parse_args()

    root: Path = args.root
    zip_path = find_export(root)
    if zip_path is None:
        print(f"書き出し zip が見つかりません: {root}/health-archive に置きましたか？",
              file=sys.stderr)
        return 1

    records = parse_steps(zip_path)
    rows = daily_steps(records)
    if not rows:
        print("歩数レコードが0件でした", file=sys.stderr)
        return 1
    map_body = build_map(rows)
    monthly_body = build_monthly(rows)

    if args.dry_run:
        sys.stdout.write(monthly_body)
    else:
        (root / MAP_REL).write_text(map_body, encoding="utf-8")
        (root / MONTHLY_REL).write_text(monthly_body, encoding="utf-8")

    # --- サマリ（stderr） ---
    multi = sum(1 for *_, n in rows if n > 1)
    print(f"入力: {zip_path.name}", file=sys.stderr)
    print(f"歩数レコード: {len(records):,} 件", file=sys.stderr)
    print(f"期間: {rows[0][0]} 〜 {rows[-1][0]}（記録のある日 {len(rows):,} 日）",
          file=sys.stderr)
    print(f"計測元が複数あった日（多い方だけ採用）: {multi:,} 日", file=sys.stderr)
    if not args.dry_run:
        print(f"\n→ {root / MAP_REL} に {len(rows):,} 日分を書き出しました", file=sys.stderr)
        print(f"→ {root / MONTHLY_REL} に {monthly_body.count(chr(10)) - 1} か月分を書き出しました",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
