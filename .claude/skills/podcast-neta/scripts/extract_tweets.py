#!/usr/bin/env python3
"""X アーカイブ (tweets.js) を機械的に前処理し、Podcast ネタ候補になりうる
「自分の言葉のツイート」だけを抽出して JSON に落とす。

意味的な選別（ポエム/哲学系かどうか）はこのスクリプトでは行わない。
ここでは決定的なルールでノイズ（RT・他人へのリプライ・URLだけ・短すぎる反応）
を落とし、後段の LLM が読みやすい compact な候補リストを作ることに専念する。

使い方:
    python3 extract_tweets.py \
        --tweets <path/to/tweets.js> \
        --account <path/to/account.js> \
        --out <path/to/candidates.json> \
        --min-len 15
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# t.co / http(s) URL と @メンションを落とすための正規表現
URL_RE = re.compile(r"https?://\S+")
MENTION_RE = re.compile(r"[@＠]\w+")
WS_RE = re.compile(r"\s+")


def load_js_array(path: Path) -> list:
    """`window.YTD.xxx.partN = [ ... ]` 形式の JS ファイルから配列部分を取り出して JSON パース。"""
    text = path.read_text(encoding="utf-8")
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"配列が見つかりません: {path}")
    return json.loads(text[start : end + 1])


def own_account_id(account_path: Path | None) -> str | None:
    if account_path is None or not account_path.exists():
        return None
    try:
        arr = load_js_array(account_path)
        return arr[0]["account"]["accountId"]
    except Exception:
        return None


def clean(text: str) -> str:
    """本文から URL・メンションを取り除き、長さ判定に使う「中身」を返す。"""
    t = URL_RE.sub("", text)
    t = MENTION_RE.sub("", t)
    t = t.replace("　", " ")
    t = WS_RE.sub(" ", t).strip()
    return t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tweets", required=True, type=Path)
    ap.add_argument("--account", type=Path, default=None)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--min-len", type=int, default=15,
                    help="URL/メンションを除いた本文の最小文字数（これ未満は反応系として除外）")
    args = ap.parse_args()

    own_id = own_account_id(args.account)
    raw = load_js_array(args.tweets)

    kept: list[dict] = []
    seen_text: set[str] = set()
    stats = {
        "total": len(raw),
        "retweets": 0,
        "reply_to_others": 0,
        "too_short_or_url_only": 0,
        "duplicates": 0,
        "kept": 0,
    }

    for item in raw:
        t = item.get("tweet", item)
        full = t.get("full_text", "")

        # 1) リツイートを除外
        if t.get("retweeted") is True or full.startswith("RT @"):
            stats["retweets"] += 1
            continue

        # 2) 他人へのリプライを除外（自分への連投＝スレッドは残す）
        reply_uid = t.get("in_reply_to_user_id_str") or t.get("in_reply_to_user_id")
        is_self_thread = False
        if reply_uid:
            if own_id and str(reply_uid) == str(own_id):
                is_self_thread = True
            else:
                stats["reply_to_others"] += 1
                continue
        # own_id が取れない場合、先頭が @ で始まるものはリプライとみなして除外
        if own_id is None and full.lstrip().startswith("@"):
            stats["reply_to_others"] += 1
            continue

        c = clean(full)

        # 3) URL/メンションを除くと短すぎる反応・実況を除外
        if len(c) < args.min_len:
            stats["too_short_or_url_only"] += 1
            continue

        # 4) 完全重複を除外
        if c in seen_text:
            stats["duplicates"] += 1
            continue
        seen_text.add(c)

        kept.append({
            "id": t.get("id_str") or t.get("id"),
            "date": t.get("created_at"),
            "text": full.strip(),
            "clean_text": c,
            "chars": len(c),
            "favs": int(t.get("favorite_count", 0) or 0),
            "rts": int(t.get("retweet_count", 0) or 0),
            "self_thread": is_self_thread,
            "reply_to_id": t.get("in_reply_to_status_id_str") if is_self_thread else None,
        })

    stats["kept"] = len(kept)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(stats, ensure_ascii=False, indent=2), file=sys.stderr)
    print(f"→ {args.out} に {len(kept)} 件を書き出しました", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
