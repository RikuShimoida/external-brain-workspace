#!/usr/bin/env python3
"""Kindle のハイライト JSON を読むための共通パーサ。

docs/kindle-export.md の手順でブラウザから吸い出した kindle-archive/highlights.json を
Book / Highlight に均して返す。kindle_map.py / kindle_extract.py / kindle_match.py が共有する。

JSON の形（docs/kindle-export.md の JS が吐くもの）:
    {
      "exported_at": "2026-08-26T12:34:56.000Z",
      "books": [
        {"asin": "B01N...", "title": "...", "author": "...",
         "highlights": [{"text": "...", "note": "...", "location": "123", "page": "45", "color": "yellow"}]}
      ],
      "failed": [{"asin": "...", "title": "...", "reason": "..."}]
    }

取りこぼしを黙って捨てないため、failed（取得に失敗した本）もそのまま持ち回る。
"""
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field

INPUT = "kindle-archive/highlights.json"


@dataclass
class Highlight:
    text: str
    note: str = ""
    location: str = ""
    page: str = ""
    color: str = ""


@dataclass
class Book:
    asin: str
    title: str
    author: str = ""
    highlights: list = field(default_factory=list)

    @property
    def num_notes(self):
        """自分でメモを書き添えたハイライトの数。"""
        return sum(1 for h in self.highlights if h.note)

    @property
    def chars(self):
        return sum(len(h.text) for h in self.highlights)

    @property
    def longest(self):
        return max((len(h.text) for h in self.highlights), default=0)


def clean(s):
    """TSV と Markdown を壊さないよう、タブと改行と前後空白を潰す。"""
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def normalize_title(s):
    """書名の突き合わせ用に正規化する。

    Kindle の書名は volumes/ 側（Evernote 由来）と表記が揺れる。
    全半角・記号・副題・巻数表記を落として、比較できる形に均す。
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = s.lower()
    # 副題・シリーズ表記（括弧内、コロン以降、ハイフン以降）を落とす
    s = re.sub(r"[（(\[【].*?[）)\]】]", "", s)
    s = re.split(r"[:：]|\s[-–—]\s", s)[0]
    # 版・巻・出版社の付記
    s = re.sub(r"(新版|改訂版|完全版|文庫版|増補版|決定版|第\d+版|\d+巻|上|下|前編|後編)$", "", s)
    # 記号と空白を全部落とす（残った文字だけで比較する）
    s = re.sub(r"[\s\W_]+", "", s)
    return s


def load(path=INPUT):
    """JSON を読んで (books, failed, exported_at) を返す。

    ハイライトが 0 件の本は落とす（notebook には本棚の全書籍が並ぶが、
    線を引いていない本はこのアーカイブに用が無いため）。
    """
    if not os.path.exists(path):
        raise SystemExit(
            f"ハイライトが見つかりません: {path}\n"
            f"docs/kindle-export.md の手順でブラウザから吸い出してください。"
        )
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    books = []
    for b in data.get("books", []):
        hs = []
        for h in b.get("highlights", []):
            text = clean(h.get("text"))
            if not text:
                continue
            hs.append(
                Highlight(
                    text=text,
                    note=clean(h.get("note")),
                    location=clean(h.get("location")),
                    page=clean(h.get("page")),
                    color=clean(h.get("color")),
                )
            )
        if not hs:
            continue
        books.append(
            Book(
                asin=clean(b.get("asin")),
                title=clean(b.get("title")) or "無題",
                author=clean(b.get("author")),
                highlights=hs,
            )
        )

    books.sort(key=lambda b: len(b.highlights), reverse=True)
    return books, data.get("failed", []), clean(data.get("exported_at"))


def safe_name(s):
    """ファイル名に使える形に均す（claude_log_extract.py と同じ作法）。"""
    s = re.sub(r"[^\w぀-ヿ一-鿿 ー-]", "", s)
    return s.strip().replace(" ", "_")[:40] or "無題"


def filename(book):
    """1冊ぶんの Markdown のファイル名。ASIN を付けて衝突を防ぐ。"""
    return f"{safe_name(book.title)}_{book.asin}.md"
