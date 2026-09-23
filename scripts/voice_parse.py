#!/usr/bin/env python3
"""オーナーの「話し言葉」を集める共通パーサー。

外部脳はほぼ全部「書いた言葉」なので、しゃべるときの陸（口癖・語尾・間・話の組み立て）が
分からない。ただしオーナーは Claude / ChatGPT への指示を**音声入力**しているので、フィラー
（「えー」「まあ」など）が残った話し言葉が既にテキストで存在する。ここではそれを拾う。
音声ファイルの文字起こし（iPhone ボイスメモ・Evernote の音声添付・YouTube の自作動画）は
別 Issue。そちらで作ったテキストも同じ Utterance に乗せれば合流できる作りにしてある。

ソース（source 列）:
  claude    … Claude Code の元ログ（~/.claude/projects）。claude_log_parse で本人の自筆
              （kind=self）の発言だけを取り、その中から話し言葉を判定する
  chatgpt   … ChatGPT エクスポート zip（chatgpt-archive/*.zip）の user 発言。同じく判定する
  evernote  … ポストモーテムの「ボイスメモ」欄（voice-archive/_raw/evernote/*.txt）。
              もともと口頭の文字起こしなので**判定せず全部**話し言葉として扱う。
              第三者が話しているノートは吸い出しの時点で除外済み（docs/data-sources.md）

話し言葉の判定（音声入力かどうかはログに残らないため、フィラーで推定する）:
  フィラーが FILLER_MIN 回以上 **かつ** 1,000字あたり FILLER_DENSITY_MIN 回以上。
  回数だけだと、貼り付けた長文（議事録・資料など）にたまたま「まあ」が混ざったものまで拾う。
  実測（2026-09-23）: 回数だけで拾った309件のうち1,000字以上の73件（約150万字）は密度の中央値が
  0.3〜1.2/千字、300字未満は21.5/千字。密度で切ると貼り付けがほぼ落ちる。
"""
import os
import re
import sys
import glob
import json
import zipfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claude_log_parse import iter_sessions  # noqa: E402

CHATGPT_ZIP_GLOB = "chatgpt-archive/*.zip"
EVERNOTE_GLOB = "voice-archive/_raw/evernote/*.txt"

# 話し言葉の目印。長い方から並べる（「えーと」を「えー」より先に数えるため）。
FILLERS = ["えーっと", "えーと", "えっと", "えー", "あのー", "あの、", "うーん", "んー",
           "まあ", "なんか", "ほんとに", "とりあえず", "ちょっと"]
FILLER_RE = re.compile("|".join(map(re.escape, FILLERS)))
FILLER_MIN = 2
FILLER_DENSITY_MIN = 5.0  # 1,000字あたり
MIN_CHARS = 30  # 短すぎる発言は特徴が出ないので捨てる


class Utterance:
    __slots__ = ("source", "date", "ref", "text", "spoken")

    def __init__(self, source, date, ref, text, spoken):
        self.source = source   # claude / chatgpt / evernote
        self.date = date       # YYYY-MM-DD
        self.ref = ref         # 出どころの ID（セッションUUID先頭8 / 会話ID先頭8 / ファイル名）
        self.text = text
        self.spoken = spoken   # 話し言葉と判定したか

    @property
    def fillers(self):
        return len(FILLER_RE.findall(self.text))


def filler_count(text):
    return len(FILLER_RE.findall(text))


def is_spoken(text):
    n = filler_count(text)
    return n >= FILLER_MIN and n * 1000 / max(len(text), 1) >= FILLER_DENSITY_MIN


def iter_claude():
    for s in iter_sessions():
        for u in s.utterances:
            if not u.is_self or len(u.text) < MIN_CHARS:
                continue
            yield Utterance("claude", u.date, s.session_id[:8], u.text, is_spoken(u.text))


def _date(ts):
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%Y-%m-%d")


def iter_chatgpt():
    paths = sorted(glob.glob(CHATGPT_ZIP_GLOB))
    if not paths:
        return
    with zipfile.ZipFile(paths[0]) as zf:
        for m in sorted(n for n in zf.namelist()
                        if n.startswith("conversations-") and n.endswith(".json")):
            with zf.open(m) as f:
                convs = json.load(f)
            for c in convs:
                cid = (c.get("id") or c.get("conversation_id") or "")[:8]
                for node in (c.get("mapping") or {}).values():
                    msg = node.get("message") or {}
                    if (msg.get("author") or {}).get("role") != "user":
                        continue
                    parts = (msg.get("content") or {}).get("parts") or []
                    text = "".join(p for p in parts if isinstance(p, str)).strip()
                    if len(text) < MIN_CHARS:
                        continue
                    yield Utterance("chatgpt", _date(msg.get("create_time") or c.get("create_time")),
                                    cid, text, is_spoken(text))


def iter_evernote():
    for path in sorted(glob.glob(EVERNOTE_GLOB)):
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        body = "\n".join(l for l in lines[1:]).strip()  # 1行目はタイトル
        if len(body) < MIN_CHARS:
            continue
        name = os.path.basename(path).removesuffix(".txt")
        yield Utterance("evernote", name[:10], name, body, True)


def iter_all():
    yield from iter_claude()
    yield from iter_chatgpt()
    yield from iter_evernote()


def one_line(text):
    return text.replace("\t", " ").replace("\r", "").replace("\n", " / ").strip()
