#!/usr/bin/env python3
"""ChatGPT エクスポート ZIP から会話の「地図」を作る。

ZIP を全展開せず、conversations-*.json を1つずつストリームで読み、
各会話の (作成日, タイトル, メッセージ数) だけを抜き出して一覧化する。
本文はメモリにもディスクにも残さない（地図づくりが目的）。

使い方:
    python3 scripts/chatgpt_map.py chatgpt-archive/*.zip
出力:
    chatgpt-archive/conversation_map.tsv  … 全会話の一覧（日付順）
    標準出力に件数・期間などのサマリ
"""
import sys
import glob
import json
import zipfile
from datetime import datetime, timezone


def count_messages(mapping):
    """mapping ツリーから、実際に本文のある user/assistant 発言数を数える。"""
    n = 0
    for node in mapping.values():
        msg = node.get("message")
        if not msg:
            continue
        author = (msg.get("author") or {}).get("role")
        if author not in ("user", "assistant"):
            continue
        parts = (msg.get("content") or {}).get("parts") or []
        text = "".join(p for p in parts if isinstance(p, str)).strip()
        if text:
            n += 1
    return n


def fmt_date(ts):
    if not ts:
        return "0000-00-00"
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%Y-%m-%d")


def main():
    zip_glob = sys.argv[1] if len(sys.argv) > 1 else "chatgpt-archive/*.zip"
    zip_path = sorted(glob.glob(zip_glob))[0]

    rows = []  # (date, ts, title, msg_count)
    with zipfile.ZipFile(zip_path) as zf:
        members = sorted(
            m for m in zf.namelist() if m.startswith("conversations-") and m.endswith(".json")
        )
        for m in members:
            with zf.open(m) as f:
                convs = json.load(f)
            for c in convs:
                ts = c.get("create_time") or c.get("update_time")
                title = (c.get("title") or "（無題）").replace("\t", " ").replace("\n", " ").strip()
                nmsg = count_messages(c.get("mapping") or {})
                rows.append((fmt_date(ts), ts or 0, title, nmsg))

    rows.sort(key=lambda r: r[1])  # 作成時刻順

    out = "chatgpt-archive/conversation_map.tsv"
    with open(out, "w", encoding="utf-8") as w:
        w.write("date\ttitle\tmessages\n")
        for date, _ts, title, nmsg in rows:
            w.write(f"{date}\t{title}\t{nmsg}\n")

    # サマリ
    total = len(rows)
    dates = [r[0] for r in rows if r[0] != "0000-00-00"]
    span = f"{dates[0]} 〜 {dates[-1]}" if dates else "不明"
    total_msg = sum(r[3] for r in rows)
    # 年ごとの件数
    from collections import Counter
    by_year = Counter(r[0][:4] for r in rows)

    print(f"会話の総数: {total} 件")
    print(f"期間: {span}")
    print(f"総メッセージ数（本文あり）: {total_msg:,}")
    print("年ごとの会話数:")
    for y in sorted(by_year):
        print(f"  {y}: {by_year[y]} 件")
    print(f"\n一覧を書き出しました: {out}")


if __name__ == "__main__":
    main()
