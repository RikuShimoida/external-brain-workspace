#!/usr/bin/env python3
"""Facebook Messenger のエクスポート（JSON）を読むための共通パーサー。

messenger_map.py（地図づくり）と messenger_extract.py（本文抽出）の両方から使う。
パースの仕様が1か所にしか無いようにするためのモジュールで、単体では何もしない。

エクスポートの形式:

    messenger-archive/_raw/your_facebook_activity/messages/
      inbox/<相手ID>/message_1.json   … 1スレッド=1ファイル
      message_requests/<相手ID>/message_1.json
    それぞれの JSON は:
      {
        "participants": [{"name": "..."}, ...],
        "messages": [
          {"sender_name": "...", "timestamp_ms": 1553701386824,
           "content": "本文", "photos": [...], "files": [...], "reactions": [...]},
          ...   # 新しい順（降順）で並ぶ
        ],
        "title": "スレッド名",
        "thread_path": "inbox/<相手ID>",
        ...
      }

  - **文字化け**: Facebook は UTF-8 の各バイトを Latin-1 の1文字として JSON に書く。
    そのまま読むと "ã\x81\x82..." になるので、latin-1 で encode し直して utf-8 で
    decode すると元の日本語に戻る（fix_mojibake）。
  - content が無いメッセージは添付（photos / files / gifs / sticker / share）や
    通話・リアクションのみ。件数は数えるが本文としては空。
  - messages は新しい順なので、時系列で見たいときは timestamp で昇順に並べ直す。
"""
import json
import os


def fix_mojibake(s):
    """Facebook JSON の Latin-1 経由の文字化けを元の UTF-8 に戻す。

    直せないもの（元から ASCII 等）はそのまま返す。
    """
    if not isinstance(s, str):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


# 本文が取れない添付・イベントの種類。件数は数えるが、テキストとしては中身が無い。
ATTACHMENT_KEYS = ("photos", "videos", "gifs", "audio_files", "files", "sticker", "share")


class Message:
    """1件のメッセージ。"""

    __slots__ = ("ts_ms", "sender", "body", "attachments")

    def __init__(self, ts_ms, sender, body, attachments):
        self.ts_ms = ts_ms              # timestamp_ms（int）
        self.sender = sender            # 文字化け復元済みの送信者名
        self.body = body                # 文字化け復元済みの本文（無ければ ""）
        self.attachments = attachments  # このメッセージに付いた添付の数（int）

    @property
    def is_attachment(self):
        """本文が無く添付・スタンプ等だけのメッセージか。"""
        return not self.body and self.attachments > 0

    def __repr__(self):
        return f"<{self.ts_ms} {self.sender}: {self.body[:20]}...>"


def _count_attachments(raw):
    """1メッセージに含まれる添付・共有の数を数える。"""
    n = 0
    for key in ATTACHMENT_KEYS:
        v = raw.get(key)
        if isinstance(v, list):
            n += len(v)
        elif v:  # sticker / share は dict 1個
            n += 1
    return n


def thread_id(path):
    """スレッドのフォルダ名（<ローマ字名>_<数字ID> か 数字ID だけ）を返す。

    地図では相手の実名を出さないため、この ID を「room」の匿名キーとして使う。
    """
    d = os.path.dirname(path)
    return os.path.basename(d)


def parse(path):
    """message_1.json を読み、(タイトル, Message のリスト) を返す。

    タイトルと本文は文字化けを復元する。Message は時系列（昇順）に並べ直す。
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    title = fix_mojibake(data.get("title", "")) or thread_id(path)

    messages = []
    for raw in data.get("messages", []):
        body = fix_mojibake(raw.get("content", "") or "")
        messages.append(
            Message(
                ts_ms=raw.get("timestamp_ms", 0),
                sender=fix_mojibake(raw.get("sender_name", "") or ""),
                body=body,
                attachments=_count_attachments(raw),
            )
        )

    messages.sort(key=lambda m: m.ts_ms)  # エクスポートは降順なので昇順へ
    return title, messages
