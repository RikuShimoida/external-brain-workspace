#!/usr/bin/env python3
"""Instagram の公式データエクスポート（JSON）を読むための共通パーサー。

instagram_map.py（地図づくり）と instagram_extract.py（本文抽出）の両方から使う。
パースの仕様が1か所にしか無いようにするためのモジュールで、単体では何もしない。
Messenger の messenger_parse.py と同じ考え方（文字化け復元・相手の匿名化）。

エクスポートの形式（instagram-archive/_raw/your_instagram_activity/ 配下）:

    media/stories.json       … {"ig_stories": [{"title": "キャプション", "creation_timestamp": ...}, ...]}
    media/posts_1.json       … [{"title": "...", "media": [{"title": "...", "creation_timestamp": ...}], "creation_timestamp": ...}, ...]
    media/other_content.json … posts と同型
    comments/post_comments_1.json … [{"string_map_data": {"Comment": {"value": "..."}, "Time": {"timestamp": ...}}}, ...]
    messages/inbox/<相手ID>/message_1.json … {"participants": [...], "messages": [{"sender_name","timestamp_ms","content"}, ...]}
    story_interactions/questions.json … {"label_values": [...]}（自分の質問箱への回答）

固有の要件:
  - **文字化け**: Instagram も Facebook 同様、UTF-8 の各バイトを Latin-1 の1文字として
    JSON に書く。そのまま読むと "ã\x81\x82..." になるので、latin-1 で encode し直して
    utf-8 で decode すると元の日本語・絵文字に戻る（fix_mojibake）。
  - **EXIF**: 画像には media_metadata.photo_metadata.exif_data に端末ID・緯度経度・ISO 等が
    入るが、このパーサーは title（キャプション）しか読まないので混入しない。
  - **匿名化**: DM の相手の実名は成果物に出さない。スレッドのフォルダ ID を匿名キーとして使う。
    自分（OWNER）の発言だけは sender をそのまま残す。
"""
import os
import json
import glob


OWNER = "Riku Shimoida"

# 取り込み対象のソース。相対 glob（instagram-archive リンク経由で見える）。
BASE = "instagram-archive/_raw/your_instagram_activity"
GLOB_CAPTIONS = [
    f"{BASE}/media/stories.json",
    f"{BASE}/media/posts.json",
    f"{BASE}/media/posts_1.json",
    f"{BASE}/media/other_content.json",
    f"{BASE}/media/archived_posts.json",
]
GLOB_COMMENTS = [
    f"{BASE}/comments/post_comments_1.json",
    f"{BASE}/comments/reels_comments.json",
]
GLOB_DM = [
    f"{BASE}/messages/inbox/*/message_*.json",
    f"{BASE}/messages/message_requests/*/message_*.json",
]
GLOB_QUESTIONS = [
    f"{BASE}/story_interactions/questions.json",
    f"{BASE}/story_interactions/polls.json",
]


def fix_mojibake(s):
    """Instagram JSON の Latin-1 経由の文字化けを元の UTF-8 に戻す。

    直せないもの（元から ASCII 等）はそのまま返す。
    """
    if not isinstance(s, str):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


class Item:
    """取り込んだ1件の「自分の言葉」。種別をまたいで同じ形で扱う。"""

    __slots__ = ("kind", "ts", "room", "sender", "body")

    def __init__(self, kind, ts, room, sender, body):
        self.kind = kind        # "story" / "post" / "comment" / "dm" / "question"
        self.ts = ts            # UNIX 秒（int, 無ければ 0）
        self.room = room        # DM のスレッド ID。DM 以外は ""（匿名キー）
        self.sender = sender    # 発言者（自分=OWNER。DM 以外は OWNER 固定）
        self.body = body        # 文字化け復元済みの本文

    def __repr__(self):
        return f"<{self.kind} {self.ts} {self.sender}: {self.body[:20]}...>"


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _expand(globs):
    paths = []
    for g in globs:
        paths.extend(glob.glob(g))
    return sorted(set(paths))


def parse_captions():
    """ストーリー・投稿・その他コンテンツのキャプションを Item 列で返す。

    stories は {"ig_stories": [...]}、posts は [...] か {"...": [...]}。
    投稿は複数画像が media[] にぶら下がるが、キャプションは投稿単位の title か
    先頭 media の title に入る。空 title（画像だけの投稿）は捨てる。
    """
    items = []
    for path in _expand(GLOB_CAPTIONS):
        data = _load(path)
        base = os.path.basename(path)
        kind = "story" if base.startswith("stories") else "post"

        if isinstance(data, dict):
            # stories.json は "ig_stories"、他も念のため最初のリスト値を拾う
            records = data.get("ig_stories")
            if records is None:
                for v in data.values():
                    if isinstance(v, list):
                        records = v
                        break
            records = records or []
        else:
            records = data

        for rec in records:
            title = fix_mojibake(rec.get("title", "") or "").strip()
            ts = rec.get("creation_timestamp", 0)
            # 投稿単位で title が空なら、束ねられた media の先頭 title を見る
            if not title and isinstance(rec.get("media"), list) and rec["media"]:
                m0 = rec["media"][0]
                title = fix_mojibake(m0.get("title", "") or "").strip()
                ts = ts or m0.get("creation_timestamp", 0)
            if title:
                items.append(Item(kind, ts, "", OWNER, title))
    return items


def parse_comments():
    """自分が書いたコメントを Item 列で返す。"""
    items = []
    for path in _expand(GLOB_COMMENTS):
        data = _load(path)
        records = data if isinstance(data, list) else next(
            (v for v in data.values() if isinstance(v, list)), []
        )
        for rec in records:
            smd = rec.get("string_map_data", {})
            body = fix_mojibake(smd.get("Comment", {}).get("value", "") or "").strip()
            ts = smd.get("Time", {}).get("timestamp", 0)
            if body:
                items.append(Item("comment", ts, "", OWNER, body))
    return items


def thread_id(path):
    """DM スレッドのフォルダ名（<ローマ字名>_<数字ID> か 数字ID だけ）を返す。

    地図では相手の実名を出さないため、この ID を匿名キーとして使う。
    """
    return os.path.basename(os.path.dirname(path))


def parse_dms(owner=OWNER):
    """DM を Item 列で返す。相手の実名は出さず、room に匿名スレッド ID を入れる。

    自分・相手の両方の発言を保存する（文脈を残すため）が、sender は自分だけ実名、
    相手は "相手" に正規化する。本文の文字化けは復元する。
    """
    items = []
    for path in _expand(GLOB_DM):
        data = _load(path)
        tid = thread_id(path)
        for raw in data.get("messages", []):
            body = fix_mojibake(raw.get("content", "") or "").strip()
            if not body:
                continue  # 添付・スタンプ・通話のみ
            sender_raw = fix_mojibake(raw.get("sender_name", "") or "")
            sender = owner if sender_raw == owner else "相手"
            ts_ms = raw.get("timestamp_ms", 0)
            items.append(Item("dm", ts_ms // 1000 if ts_ms else 0, tid, sender, body))
    return items


def parse_questions():
    """ストーリーの質問箱・投票への自分の回答を Item 列で返す。

    questions.json / polls.json の構造は label_values に入る。回答テキストだけ拾う。
    """
    items = []
    for path in _expand(GLOB_QUESTIONS):
        data = _load(path)
        records = data if isinstance(data, list) else [data]
        for rec in records:
            ts = rec.get("timestamp", 0)
            for lv in rec.get("label_values", []):
                val = fix_mojibake(lv.get("value", "") or "").strip()
                if val:
                    items.append(Item("question", ts, "", OWNER, val))
    return items


def parse_all(owner=OWNER):
    """全種別を Item 列で返す（DM は自分・相手とも含む）。"""
    return (
        parse_captions()
        + parse_comments()
        + parse_dms(owner)
        + parse_questions()
    )
