#!/usr/bin/env python3
"""ChatGPT エクスポート ZIP から「深い人生相談」だけ本文抽出する。

conversations-*.json をストリームで読み、
  (1) タイトルが人生相談系キーワードに該当し、
  (2) 本文ありメッセージ数が閾値以上
の会話だけを Markdown 化して chatgpt-archive/lifetalk/ に書き出す。

使い方:
    python3 scripts/chatgpt_extract.py [閾値] [--dry-run]
      閾値      … 本文ありメッセージ数の下限（既定 15）
      --dry-run … 書き出さず件数だけ表示
"""
import sys
import glob
import json
import zipfile
import re
from datetime import datetime, timezone

KW = [
    "悩", "迷", "人生", "キャリア", "転職", "独立", "フリーランス", "案件",
    "税", "確定申告", "お金", "貯金", "投資", "資産", "将来", "夢", "目標",
    "家族", "妻", "あや", "りゆ", "子ども", "子育て", "育児", "父", "母",
    "ADHD", "発達", "不安", "しんどい", "疲れ", "メンタル", "うつ",
    "幸せ", "価値観", "生き方", "自分", "性格", "自己", "強み", "弱み",
    "健康", "ダイエット", "運動", "習慣", "時間", "後悔", "決断", "選択",
    "漫画", "お笑い", "クリエイター", "Podcast", "ポッドキャスト", "発信",
    "恋愛", "結婚", "友人", "人間関係", "相談",
]

ROLE_JP = {"user": "あなた", "assistant": "ChatGPT"}


def text_of(msg):
    content = msg.get("content") or {}
    if content.get("content_type") != "text":
        return ""
    parts = content.get("parts") or []
    return "".join(p for p in parts if isinstance(p, str)).strip()


def ordered_messages(mapping):
    """mapping ツリーを create_time 順に並べ、本文ありの user/assistant 発言を返す。"""
    msgs = []
    for node in mapping.values():
        m = node.get("message")
        if not m:
            continue
        role = (m.get("author") or {}).get("role")
        if role not in ("user", "assistant"):
            continue
        t = text_of(m)
        if not t:
            continue
        msgs.append((m.get("create_time") or 0, role, t))
    msgs.sort(key=lambda x: x[0])
    return msgs


def fmt_date(ts):
    if not ts:
        return "0000-00-00"
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%Y-%m-%d")


def safe_name(s):
    s = re.sub(r"[^\w぀-ヿ一-鿿 ー-]", "", s)
    return s.strip().replace(" ", "_")[:40] or "無題"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    threshold = int(args[0]) if args else 15
    dry = "--dry-run" in sys.argv

    zip_path = sorted(glob.glob("chatgpt-archive/*.zip"))[0]
    outdir = "chatgpt-archive/lifetalk"
    if not dry:
        import os
        os.makedirs(outdir, exist_ok=True)

    picked = []
    with zipfile.ZipFile(zip_path) as zf:
        members = sorted(
            m for m in zf.namelist() if m.startswith("conversations-") and m.endswith(".json")
        )
        for m in members:
            with zf.open(m) as f:
                convs = json.load(f)
            for c in convs:
                title = (c.get("title") or "（無題）").strip()
                if not any(k in title for k in KW):
                    continue
                msgs = ordered_messages(c.get("mapping") or {})
                if len(msgs) < threshold:
                    continue
                ts = c.get("create_time") or (msgs[0][0] if msgs else 0)
                date = fmt_date(ts)
                picked.append((date, ts or 0, title, msgs))

    picked.sort(key=lambda x: x[1])
    print(f"閾値 {threshold} メッセージ以上の深い相談: {len(picked)} 件")

    if dry:
        for date, _ts, title, msgs in picked:
            print(f"  {date}  {len(msgs):>3}  {title[:50]}")
        return

    for date, _ts, title, msgs in picked:
        fname = f"{outdir}/{date}_{safe_name(title)}.md"
        with open(fname, "w", encoding="utf-8") as w:
            w.write(f"# {title}\n\n")
            w.write(f"- 日付: {date}\n- メッセージ数: {len(msgs)}\n\n---\n\n")
            for _t, role, text in msgs:
                w.write(f"**{ROLE_JP[role]}:**\n\n{text}\n\n")
    print(f"{len(picked)} 件を {outdir}/ に書き出しました。")


if __name__ == "__main__":
    main()
