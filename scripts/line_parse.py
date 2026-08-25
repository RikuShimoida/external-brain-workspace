#!/usr/bin/env python3
"""LINE のトーク履歴エクスポート（.txt）を読むための共通パーサー。

line_map.py（地図づくり）と line_extract.py（本文抽出）の両方から使う。
パースの仕様が1か所にしか無いようにするためのモジュールで、単体では何もしない。

エクスポートの形式:

    [LINE] とがあとのトーク履歴
    保存日時：2026/08/21 13:05

    2023/05/16(火)
    21:12<TAB>とがあ<TAB>[スタンプ]
    22:12<TAB>とがあ<TAB>"今日は有難うございました！
    またご飯でも行きましょう😃"

  - 日付は `YYYY/MM/DD(曜)` の行で切り替わる
  - メッセージは `時刻<TAB>話者<TAB>本文`
  - 本文が複数行のときは全体が `"` で囲まれ、閉じる `"` まで後続行が続く
  - 話者が空の行はシステム通知（「〜がアナウンスしました」等）なので捨てる
"""
import re

DATE_RE = re.compile(r"^(\d{4})/(\d{2})/(\d{2})\(.\)$")
MSG_RE = re.compile(r"^(\d{2}:\d{2})\t([^\t]*)\t(.*)$")
# 1対1は「[LINE] 相手とのトーク履歴」、グループは「[LINE] グループ名のトーク履歴」。
# 「と」を任意にして両方を1つの式で拾う。
ROOM_RE = re.compile(r"^\[LINE\]\s*(.+?)と?の(?:トーク|会話)履歴")

# 本文が取れない添付。件数は数えるが、テキストとしては中身が無い。
ATTACHMENT_RE = re.compile(r"^\[[^\]]+\]$")

# 名前の前後に混ざる方向制御文字（U+2066〜U+2069）。表示上は見えない。
ISOLATE_RE = re.compile(r"[⁦-⁩]")


class Message:
    """1件のメッセージ。"""

    __slots__ = ("date", "time", "speaker", "body")

    def __init__(self, date, time, speaker, body):
        self.date = date          # "2023/05/16"
        self.time = time          # "21:12"
        self.speaker = speaker    # "下井田　陸"
        self.body = body          # 囲みの " を外した本文

    @property
    def is_attachment(self):
        """[写真] [スタンプ] のような、本文の無い添付か。"""
        return bool(ATTACHMENT_RE.match(self.body))

    def __repr__(self):
        return f"<{self.date} {self.time} {self.speaker}: {self.body[:20]}...>"


def strip_isolates(s):
    """LINE が名前の前後に入れる方向制御の不可視文字を取り除く。"""
    return ISOLATE_RE.sub("", s)


def room_name(path, header):
    """トークルーム名を決める。先頭行から取り、駄目ならファイル名で代用する。

    ファイル名はグループ名が長いと LINE 側で切り詰められる（「〜下井田　...のトーク」）ため、
    先頭行を優先する。
    """
    m = ROOM_RE.match(strip_isolates(header or ""))
    if m:
        return m.group(1)
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return stem.replace("[LINE] ", "").replace("とのトーク", "").replace("のトーク", "")


def parse(path):
    """トーク履歴ファイルを読み、(ルーム名, Message のリスト) を返す。

    複数行メッセージは1件に結合する。システム通知は捨てる。
    """
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")

    room = room_name(path, lines[0] if lines else "")
    messages = []
    date = None
    open_quote = False  # 複数行メッセージの途中か

    for line in lines:
        if open_quote:
            # 閉じる " が来るまでは、何が書いてあっても直前の本文の続き
            messages[-1].body += "\n" + line
            if line.endswith('"'):
                open_quote = False
                messages[-1].body = messages[-1].body[1:-1]  # 囲みの " を外す
            continue

        m = DATE_RE.match(line)
        if m:
            date = f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
            continue

        m = MSG_RE.match(line)
        if not m:
            # 引用符で囲まれずに複数行になるもの（[ノート] の中身など）の続き。
            # 先頭のヘッダー2行と空行は、まだメッセージが無い or 構造なので入らない。
            if messages and line:
                messages[-1].body += "\n" + line
            continue
        time, speaker, body = m.groups()
        if not speaker:
            continue  # システム通知

        messages.append(Message(date, time, speaker, body))
        if body.startswith('"'):
            if len(body) > 1 and body.endswith('"'):
                messages[-1].body = body[1:-1]  # 1行で閉じている
            else:
                open_quote = True

    return room, messages
