#!/usr/bin/env python3
"""YouTube（Takeout「YouTube と YouTube Music」）を読む共通パーサー。

youtube_resolve.py（動画ID→メタ情報）・youtube_screen.py（意味判定の候補づくり）・
youtube_map.py（地図）・youtube_extract.py（deep）から使う。パースの仕様が1か所に
しか無いようにするためのモジュールで、単体では何もしない。

入力（youtube-archive/_raw/ 配下。youtube_extract.py --unpack で zip から取り出す）:

    watch-history.json … 視聴履歴。[{"header":"YouTube"|"YouTube Music",
        "title":"<動画タイトル> を視聴しました", "titleUrl":".../watch?v=<ID>",
        "subtitles":[{"name":"<チャンネル名>","url":".../channel/<チャンネルID>"}],
        "time":"2026-09-23T...Z", ...}, ...]
        ※ YouTube 側の自動削除設定により **直近5か月ほどしか残っていない**。
    登録チャンネル.csv … チャンネル ID, チャンネルの URL, チャンネルのタイトル（日付なし）
    再生リスト/再生リスト.csv   … 再生リストのメタ（タイトル・作成日時など）
    再生リスト/<名前> の動画.csv … 動画 ID, 再生リストの動画の作成タイムスタンプ
        ※ **動画IDしか無い**。タイトル・チャンネルは youtube_resolve.py が
          YouTube Data API で引いて .cache/video_meta.tsv に貯める。

単位は「チャンネル」。動画タイトルは1回きりが多いので、誰を追いかけてきたかで束ねる。

二段フィルタ（検索履歴 google_activity_parse.py と同じ考え方）:
  A-1a 機械式NG … scripts/ng_words.txt に**動画タイトルかチャンネル名**が当たれば、その
                 視聴/保存（1件）を捨てる。
  A-1b 意味判定 … search-query-screener が判定したチャンネル名・再生リスト名の drop を
                 youtube-archive/verdicts.tsv に永続化し、ここで捨てる。
このモジュールは照合だけを担い、LLM は呼ばない。
"""
import os
import csv
import json
import glob
import datetime as dt
from urllib.parse import urlparse, parse_qs

from google_activity_parse import load_ng_patterns, is_blocked, load_verdicts

BASE = "youtube-archive/_raw"
WATCH_JSON = f"{BASE}/watch-history.json"
SUBS_CSV = f"{BASE}/登録チャンネル.csv"
PLAYLIST_DIR = f"{BASE}/再生リスト"
PLAYLIST_META = f"{PLAYLIST_DIR}/再生リスト.csv"
VIDEO_META = "youtube-archive/.cache/video_meta.tsv"
VERDICTS_PATH = "youtube-archive/verdicts.tsv"

_WATCHED_SUFFIX = " を視聴しました"
_PLAYLIST_SUFFIX = " の動画.csv"
# 「後で見る」系の再生リスト名。好み（保存）ではなく“見たかった”という意図なので区別する。
_LATER_NAMES = ("後で見る", "watch later")


class Event:
    """視聴1回 or 再生リストへの保存1件。地図ではチャンネルごとに畳み込む。"""

    __slots__ = ("video_id", "channel_id", "channel", "title", "ts", "source", "product", "category")

    def __init__(self, video_id, channel_id, channel, title, ts, source, product, category=""):
        self.video_id = video_id
        self.channel_id = channel_id   # 無ければ channel 名で代用
        self.channel = channel
        self.title = title
        self.ts = ts                   # UNIX 秒（無ければ 0）
        self.source = source           # "watch" / "later" / "playlist"
        self.product = product         # "YouTube" / "YouTube Music"
        self.category = category       # YouTube のカテゴリ名（resolve 済みの動画のみ）


def _ts(iso):
    if not iso:
        return 0
    try:
        return int(dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def video_id_of(url):
    """watch?v=<ID> の URL から動画IDを取り出す。取れなければ ""。"""
    if not url:
        return ""
    q = parse_qs(urlparse(url).query)
    return (q.get("v") or [""])[0]


def playlist_kind(name):
    low = name.lower()
    return "later" if any(low.startswith(n) for n in _LATER_NAMES) else "playlist"


def playlist_files():
    """(再生リスト名, パス) を返す。メタの 再生リスト.csv は除く。"""
    out = []
    for path in sorted(glob.glob(f"{PLAYLIST_DIR}/*{_PLAYLIST_SUFFIX}")):
        name = os.path.basename(path)[: -len(_PLAYLIST_SUFFIX)]
        out.append((name, path))
    return out


def playlist_video_ids():
    """全再生リストの動画IDの集合（resolve の対象）。"""
    ids = set()
    for _, path in playlist_files():
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                vid = (row.get("動画 ID") or "").strip()
                if vid:
                    ids.add(vid)
    return ids


def load_video_meta(path=VIDEO_META):
    """resolve 済みのメタを {video_id: dict} で読む。status=missing は削除/非公開。"""
    meta = {}
    if not os.path.exists(path):
        return meta
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            meta[row["video_id"]] = row
    return meta


def load_subscriptions(path=SUBS_CSV):
    """登録チャンネルを [(channel_id, channel_name)] で返す。"""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        return [
            ((r.get("チャンネル ID") or "").strip(), (r.get("チャンネルのタイトル") or "").strip())
            for r in csv.DictReader(f)
            if (r.get("チャンネルのタイトル") or "").strip()
        ]


def iter_watch():
    """視聴履歴を Event で返す。チャンネルの無いもの（削除動画・広告等）は捨てる。"""
    if not os.path.exists(WATCH_JSON):
        return
    with open(WATCH_JSON, encoding="utf-8") as f:
        records = json.load(f)
    for rec in records:
        title = rec.get("title", "")
        if not title.endswith(_WATCHED_SUFFIX) or not rec.get("subtitles"):
            continue  # 「〜を表示しました」（投稿閲覧など）やチャンネル不明
        sub = rec["subtitles"][0]
        ch_url = sub.get("url", "")
        ch_id = ch_url.rsplit("/", 1)[-1] if "/channel/" in ch_url else ""
        yield Event(
            video_id=video_id_of(rec.get("titleUrl", "")),
            channel_id=ch_id,
            channel=sub.get("name", "").strip(),
            title=title[: -len(_WATCHED_SUFFIX)].strip(),
            ts=_ts(rec.get("time")),
            source="watch",
            product=rec.get("header", "YouTube"),
        )


def iter_playlists(meta, dropped_playlists=frozenset()):
    """再生リストの保存を Event で返す。resolve できていない動画は捨てる（件数は stats で数える）。

    戻り値はジェネレータではなく (events, unresolved, missing, dropped) の組。
    意味判定で drop された再生リスト名は、中身ごと読まない（dropped に件数を数える）。
    """
    events, unresolved, missing, dropped = [], 0, 0, 0
    for name, path in playlist_files():
        if name in dropped_playlists:
            with open(path, encoding="utf-8-sig") as f:
                dropped += sum(1 for _ in csv.DictReader(f))
            continue
        kind = playlist_kind(name)
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                vid = (row.get("動画 ID") or "").strip()
                if not vid:
                    continue
                m = meta.get(vid)
                if m is None:
                    unresolved += 1
                    continue
                if m.get("status") != "ok":
                    missing += 1
                    continue
                events.append(Event(
                    video_id=vid,
                    channel_id=m.get("channel_id", ""),
                    channel=m.get("channel_title", "").strip(),
                    title=m.get("title", ""),
                    ts=_ts(row.get("再生リストの動画の作成タイムスタンプ")),
                    source=kind,
                    product="YouTube",
                    category=m.get("category", ""),
                ))
    return events, unresolved, missing, dropped


def parse(ng_patterns=None, dropped=None):
    """視聴履歴＋再生リスト → 機械式NG除外 → 意味判定 drop 除外 のパイプライン。

    戻り値: (events, stats)
    意味判定の drop は「チャンネル名」と「再生リスト名」の2種類を同じ verdicts で持つ。
    """
    if ng_patterns is None:
        ng_patterns = load_ng_patterns()
    if dropped is None:
        dropped = load_verdicts(VERDICTS_PATH)
    meta = load_video_meta()

    watch = list(iter_watch())
    # 再生リスト名も二段フィルタに掛ける（名前が NG / drop なら中身ごと読まない）
    bad_lists = {n for n, _ in playlist_files() if n in dropped or is_blocked(n, ng_patterns)}
    pl_events, unresolved, missing, pl_dropped = iter_playlists(meta, bad_lists)

    stats = {
        "watch": len(watch),
        "playlist": len(pl_events) + unresolved + missing + pl_dropped,
        "unresolved": unresolved,
        "missing": missing,
        "ng_removed": 0,
        "verdict_removed": pl_dropped,
    }
    kept = []
    for e in watch + pl_events:
        if not e.channel:
            continue
        if is_blocked(e.channel, ng_patterns) or is_blocked(e.title, ng_patterns):
            stats["ng_removed"] += 1
            continue
        if e.channel in dropped:
            stats["verdict_removed"] += 1
            continue
        kept.append(e)
    stats["kept"] = len(kept)
    return kept, stats


def aggregate(events):
    """Event 列をチャンネルごとに畳み込む。

    戻り値: {channel_key: {"name", "count", "watch", "later", "playlist", "music",
                           "first", "last", "years"(Counter of "YYYY"), "categories"(Counter)}}
    channel_key はチャンネルID（無ければ名前）。name は最後に見えた名前。
    """
    from collections import Counter
    agg = {}
    for e in events:
        key = e.channel_id or e.channel
        a = agg.get(key)
        if a is None:
            a = agg[key] = {"name": e.channel, "count": 0, "watch": 0, "later": 0,
                            "playlist": 0, "music": 0, "first": 0, "last": 0,
                            "years": Counter(), "categories": Counter()}
        a["count"] += 1
        a[e.source] += 1
        if e.product == "YouTube Music":
            a["music"] += 1
        if e.category:
            a["categories"][e.category] += 1
        if e.ts:
            if a["first"] == 0 or e.ts < a["first"]:
                a["first"] = e.ts
            if e.ts >= a["last"]:
                a["last"] = e.ts
                a["name"] = e.channel
            a["years"][dt.datetime.fromtimestamp(e.ts).strftime("%Y")] += 1
    return agg
