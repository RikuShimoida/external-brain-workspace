#!/usr/bin/env python3
"""再生リストの動画IDを YouTube Data API v3 でタイトル・チャンネルに解決する。

Takeout の再生リストには「動画 ID と追加日時」しか無い。10年分の好みを読むには
チャンネル名が要るので、videos.list（1回50件・1クォータ）で引いて
youtube-archive/.cache/video_meta.tsv に貯める。

- **読み取り専用**。Google に送るのは動画IDだけ（個人データは送らない）。
- **再開可能**。既に TSV にある ID は問い合わせない。何度叩いても二重に数えない。
- 削除済み・非公開で返ってこなかった ID は status=missing として記録する（再問い合わせしない）。
- カテゴリID は videoCategories.list（regionCode=JP・1クォータ）で日本語名に直す。

API キーは .env の YOUTUBE_API_KEY（オーナーが Google Cloud Console で発行）。

使い方:
    python3 scripts/youtube_resolve.py [--dry-run] [--limit N]
      --dry-run … 未解決件数と必要な API 呼び出し回数だけ表示（通信しない）
      --limit N … 未解決のうち先頭 N 件だけ解決する（お試し用）

出力:
    youtube-archive/.cache/video_meta.tsv
      列: video_id, status(ok/missing), channel_id, channel_title, title, category, published_at
"""
import os
import sys
import csv
import json
import time
import urllib.parse
import urllib.request
import urllib.error

from youtube_parse import playlist_video_ids, load_video_meta, VIDEO_META

API = "https://www.googleapis.com/youtube/v3"
BATCH = 50
FIELDS = ["video_id", "status", "channel_id", "channel_title", "title", "category", "published_at"]


def _api_key():
    key = os.environ.get("YOUTUBE_API_KEY", "")
    if not key and os.path.exists(".env"):
        with open(".env", encoding="utf-8") as f:
            for line in f:
                if line.startswith("YOUTUBE_API_KEY="):
                    key = line.split("=", 1)[1].strip()
    if not key:
        sys.exit("YOUTUBE_API_KEY が見つかりません（.env に設定してください。手順は .env.example）")
    return key


def _get(path, params, key):
    q = urllib.parse.urlencode({**params, "key": key})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(f"{API}/{path}?{q}", timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            msg = json.load(e).get("error", {}).get("message", "")
            if e.code == 403 and "quota" in msg.lower():
                sys.exit(f"本日の API 使用量の上限に達しました。明日もう一度実行すれば続きから再開します。")
            if e.code >= 500 and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            sys.exit(f"API エラー HTTP {e.code}: {msg}")
        except urllib.error.URLError:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise


def _categories(key):
    data = _get("videoCategories", {"part": "snippet", "regionCode": "JP", "hl": "ja"}, key)
    return {c["id"]: c["snippet"]["title"] for c in data.get("items", [])}


def _clean(s):
    return (s or "").replace("\t", " ").replace("\n", " ").strip()


def main():
    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    limit = None
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])

    all_ids = playlist_video_ids()
    if not all_ids:
        sys.exit("再生リストが見つかりません: youtube-archive/_raw/ に展開しましたか？"
                 "（scripts/youtube_extract.py --unpack <zip>）")
    done = load_video_meta()
    todo = sorted(all_ids - set(done))
    if limit is not None:
        todo = todo[:limit]
    calls = (len(todo) + BATCH - 1) // BATCH

    print(f"再生リスト内のユニーク動画: {len(all_ids):,}")
    print(f"解決済み: {len(done):,} / 今回の対象: {len(todo):,}（API 呼び出し {calls:,} 回 + カテゴリ 1 回）")
    if dry or not todo:
        return

    key = _api_key()
    cats = _categories(key)
    new_file = not os.path.exists(VIDEO_META)
    os.makedirs(os.path.dirname(VIDEO_META), exist_ok=True)
    ok = missing = 0
    with open(VIDEO_META, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        if new_file:
            w.writeheader()
        for i in range(0, len(todo), BATCH):
            chunk = todo[i : i + BATCH]
            data = _get("videos", {"part": "snippet", "id": ",".join(chunk), "maxResults": BATCH}, key)
            found = {it["id"]: it["snippet"] for it in data.get("items", [])}
            for vid in chunk:
                sn = found.get(vid)
                if sn is None:
                    w.writerow({"video_id": vid, "status": "missing"})
                    missing += 1
                    continue
                w.writerow({
                    "video_id": vid,
                    "status": "ok",
                    "channel_id": sn.get("channelId", ""),
                    "channel_title": _clean(sn.get("channelTitle")),
                    "title": _clean(sn.get("title")),
                    "category": cats.get(sn.get("categoryId", ""), ""),
                    "published_at": (sn.get("publishedAt") or "")[:10],
                })
                ok += 1
            f.flush()  # 途中で止まっても、書けた分から再開できるように
            n = i // BATCH + 1
            if n % 50 == 0 or n == calls:
                print(f"  {n:,}/{calls:,} 回 … 解決 {ok:,} / 削除・非公開 {missing:,}")

    print(f"完了: 解決 {ok:,} 件 / 削除・非公開 {missing:,} 件 → {VIDEO_META}")


if __name__ == "__main__":
    main()
