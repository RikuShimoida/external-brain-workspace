#!/usr/bin/env python3
"""Google マイアクティビティ（検索カテゴリ）の Takeout JSON を読む共通パーサー。

google_activity_map.py（地図づくり）と google_activity_extract.py（本文抽出）の
両方から使う。パースの仕様が1か所にしか無いようにするためのモジュールで、単体では
何もしない。line / messenger / instagram の *_parse.py と同じ考え方。

エクスポートの形式（google-activity-archive/_raw/ 配下・検索カテゴリの1 JSON）:

    マイアクティビティ.json … [
        {"header":"検索", "title":"「<検索語>」を検索しました",
         "titleUrl":"...", "time":"2020-01-02T03:04:05.678Z",
         "products":["検索"], "activityControls":[...]},
        {"header":"検索", "title":"http://example.com/ にアクセスしました", ...},
        ...
    ]

固有の要件（このソースの本体はフィルタ設計）:
  - **接頭辞/接尾辞の正規化**: title は「「<検索語>」を検索しました」の形。接頭辞「と
    接尾辞「を検索しました」を剥がして純粋な検索語だけにする（normalize_title）。
    「〜にアクセスしました」（遷移ログ）と「〜を表示しました」は検索語ではないので捨てる。
  - **二段フィルタ（センシティブ検索の漏洩防止が最優先）**:
      A-1a 機械式NG … scripts/ng_words.txt のキーワード/ドメインに1つでも当たれば捨てる。
      A-1b 意味判定 … 別途 search-query-screener（隔離サブエージェント）が判定した結果を
                     verdicts.tsv に永続化し、そこで drop になった語をここで捨てる。
    このモジュールは NG リストと verdicts の「照合」だけを担い、LLM は呼ばない
    （map/extract を純粋関数に保ち、再現性とコストと漏洩面積を守るため）。
  - **文字化け対策は不要**: Takeout の JSON は正しい UTF-8。fix_mojibake は要らない。
"""
import os
import re
import json
import glob
from collections import Counter


# 検索語だけを取り出す正規表現。接頭辞「と接尾辞「を検索しました」を剥がす。
_SEARCHED = re.compile(r"^「(?P<q>.*)」を検索しました$", re.DOTALL)

# パスの既定値（google-activity-archive リンク経由で見える相対 glob）。
BASE = "google-activity-archive/_raw"
GLOB_SEARCH = [
    f"{BASE}/マイアクティビティ.json",
    f"{BASE}/*検索*/マイアクティビティ.json",
]
NG_WORDS_PATH = "scripts/ng_words.txt"
VERDICTS_PATH = "google-activity-archive/verdicts.tsv"


class Query:
    """取り込んだ1回ぶんの検索。map では回数に畳み込む。"""

    __slots__ = ("text", "ts")

    def __init__(self, text, ts):
        self.text = text    # 正規化済みの純粋な検索語
        self.ts = ts        # UNIX 秒（int, 無ければ 0）

    def __repr__(self):
        return f"<query {self.ts} {self.text[:20]}...>"


def normalize_title(title):
    """title から純粋な検索語を取り出す。検索語でなければ None。

    「「X」を検索しました」→ X。「〜にアクセスしました」「〜を表示しました」等は None。
    """
    if not isinstance(title, str):
        return None
    m = _SEARCHED.match(title.strip())
    if not m:
        return None
    q = m.group("q").strip()
    return q or None


def load_ng_patterns(path=NG_WORDS_PATH):
    """機械式NG（A-1a）のパターンを読む。1行1パターン、#コメント・空行は無視。

    ファイルが無ければ空リスト（NG 無し）で動く。パターンは小文字で保持し、
    検索語も小文字化して部分一致で照合する。
    """
    if not os.path.exists(path):
        return []
    pats = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            pats.append(s.lower())
    return pats


def is_blocked(text, ng_patterns):
    """検索語が機械式NGに1つでも当たるか。当たれば True（＝捨てる）。"""
    low = text.lower()
    return any(p in low for p in ng_patterns)


def load_verdicts(path=VERDICTS_PATH):
    """意味判定（A-1b）の永続結果を読み、drop 判定の検索語の集合を返す。

    verdicts.tsv の列: query<TAB>verdict(drop/keep)<TAB>reason<TAB>judged_at。
    ファイルが無ければ空集合（判定まだ）で動く。keep はここでは使わない
    （NG に当たらず drop でもない語は残るため）。
    """
    dropped = set()
    if not os.path.exists(path):
        return dropped
    with open(path, encoding="utf-8") as f:
        header = f.readline()  # 1行目はヘッダ
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) >= 2 and cols[1] == "drop":
                dropped.add(cols[0])
    return dropped


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _expand(globs):
    paths = []
    for g in globs:
        paths.extend(glob.glob(g))
    return sorted(set(paths))


def _ts_of(rec):
    """レコードの time（ISO8601, 末尾 Z）を UNIX 秒に。失敗時 0。"""
    t = rec.get("time")
    if not t:
        return 0
    try:
        # 例: 2020-01-02T03:04:05.678Z → +00:00 に直して parse
        return int(dt_fromiso(t).timestamp())
    except Exception:
        return 0


def dt_fromiso(t):
    import datetime as _dt
    return _dt.datetime.fromisoformat(t.replace("Z", "+00:00"))


def iter_raw():
    """検索カテゴリ JSON の全レコードを header=検索 のものだけ順に返す。"""
    for path in _expand(GLOB_SEARCH):
        data = _load(path)
        records = data if isinstance(data, list) else data.get("activity", [])
        for rec in records:
            if rec.get("header") == "検索":
                yield rec


def parse(ng_patterns=None, dropped=None):
    """全件 → 純検索語 → 機械式NG除外 → 意味判定 drop 除外 のパイプライン。

    戻り値: (queries, stats)
      queries … 除外を通過した Query のリスト（1回=1件。回数畳み込みは呼び出し側）
      stats   … 件数の内訳 dict（総件数・純クエリ・NG除外・意味判定除外・残存）
    ng_patterns / dropped を渡さなければファイルから読む（本番）。テストで差し込める。
    """
    if ng_patterns is None:
        ng_patterns = load_ng_patterns()
    if dropped is None:
        dropped = load_verdicts()

    total = 0
    pure = 0
    ng_removed = 0
    verdict_removed = 0
    queries = []

    for rec in iter_raw():
        total += 1
        q = normalize_title(rec.get("title", ""))
        if q is None:
            continue  # 遷移ログ・表示ログ等
        pure += 1
        if is_blocked(q, ng_patterns):
            ng_removed += 1
            continue
        if q in dropped:
            verdict_removed += 1
            continue
        queries.append(Query(q, _ts_of(rec)))

    stats = {
        "total": total,
        "pure": pure,
        "ng_removed": ng_removed,
        "verdict_removed": verdict_removed,
        "kept": len(queries),
    }
    return queries, stats


def aggregate(queries):
    """Query 列を検索語ごとに畳み込む。

    戻り値: {text: {"count", "first"(UNIX秒), "last", "years"(set of "YYYY")}}
    """
    import datetime as _dt
    agg = {}
    for q in queries:
        a = agg.get(q.text)
        if a is None:
            a = agg[q.text] = {"count": 0, "first": 0, "last": 0, "years": set()}
        a["count"] += 1
        if q.ts:
            if a["first"] == 0 or q.ts < a["first"]:
                a["first"] = q.ts
            if q.ts > a["last"]:
                a["last"] = q.ts
            a["years"].add(_dt.datetime.fromtimestamp(q.ts).strftime("%Y"))
    return agg
