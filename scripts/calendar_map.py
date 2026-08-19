#!/usr/bin/env python3
"""Google カレンダーのエクスポート ZIP から「行動ログ」の一覧を作る。

外部脳のうち X / Evernote / ChatGPT はすべて「自分が言ったこと」の記録だが、
カレンダーだけは「実際に何に時間を使ったか」が残る。その行動ログを TSV にする。

ZIP の入手方法:
    Google カレンダー → 設定 → インポート/エクスポート → エクスポート
    → 全カレンダーの .ics が入った ZIP がダウンロードされるので calendar-archive/ に置く

ZIP を全展開せず、中の *.ics を1つずつ読み、各予定の
(日付・開始時刻・所要分・カレンダー名・タイトル・場所) だけを抜き出す。
本文（DESCRIPTION）は拾わない。ノイズと個人情報が多く、行動ログには不要なため。

繰り返し予定（RRULE）は展開せず、1行のまま recurring 列に印をつける。
「週報忘れるな」のような繰り返しリマインダは行動ログとしてはノイズなので、
集計側でこの列を見て落とせればよい。

使い方:
    python3 scripts/calendar_map.py                     # 個人カレンダーのみ（既定）
    python3 scripts/calendar_map.py --all               # 祝日以外の全カレンダー
    python3 scripts/calendar_map.py --calendar xiajing  # 名前に含む文字列で絞る
    python3 scripts/calendar_map.py --dry-run           # 書き出さずサマリだけ
出力:
    calendar-archive/events.tsv  … 全予定の一覧（日付順）
    標準出力に件数・期間・年別・カレンダー別のサマリ
"""
import sys
import glob
import re
import zipfile
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
OUT = "calendar-archive/events.tsv"
WANTED = ("DTSTART", "DTEND", "DURATION", "SUMMARY", "LOCATION", "RRULE", "STATUS")
DUR_RE = re.compile(r"^P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def unfold(text):
    """ICS の折り返し行（先頭が空白/タブの継続行）を1行に結合する。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in text.split("\n"):
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def split_prop(line):
    """'NAME;PARAM=X:VALUE' を (NAME, {params}, VALUE) に分解する。"""
    in_quote = False
    head = value = None
    for i, ch in enumerate(line):
        if ch == '"':
            in_quote = not in_quote
        elif ch == ":" and not in_quote:
            head, value = line[:i], line[i + 1:]
            break
    if head is None:
        return None
    parts = head.split(";")
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v.strip('"')
    return parts[0].upper(), params, value


def unescape(v):
    """ICS のバックスラッシュエスケープ（改行・カンマ・セミコロン）を戻す。"""
    table = {"n": "\n", "N": "\n", ",": ",", ";": ";", "\\": "\\"}
    out = []
    i = 0
    while i < len(v):
        if v[i] == "\\" and i + 1 < len(v):
            out.append(table.get(v[i + 1], v[i + 1]))
            i += 2
        else:
            out.append(v[i])
            i += 1
    return "".join(out)


def flat(s):
    """TSV に入れられるよう、改行・タブを潰して1行にする（全角スペースは残す）。"""
    s = s.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    while "  " in s:
        s = s.replace("  ", " ")
    return s.strip(" ")


def parse_dt(params, value):
    """(日時, 終日か) を返す。時刻ありは JST に正規化する。"""
    v = value.strip()
    if params.get("VALUE") == "DATE" or "T" not in v:
        return datetime.strptime(v, "%Y%m%d").replace(tzinfo=JST), True
    if v.endswith("Z"):
        dt = datetime.strptime(v[:-1], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    else:
        try:
            tz = ZoneInfo(params.get("TZID") or "Asia/Tokyo")
        except Exception:
            tz = JST
        dt = datetime.strptime(v, "%Y%m%dT%H%M%S").replace(tzinfo=tz)
    return dt.astimezone(JST), False


def parse_duration_min(v):
    m = DUR_RE.match(v.strip().lstrip("+"))
    if not m:
        return None
    w, d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return w * 10080 + d * 1440 + h * 60 + mi + s // 60


def build_row(props, calname):
    """VEVENT の生プロパティから TSV 1行分のタプルを作る。捨てる予定は None。"""
    if "DTSTART" not in props:
        return None
    if "STATUS" in props and props["STATUS"][1].strip().upper() == "CANCELLED":
        return None
    try:
        start, all_day = parse_dt(*props["DTSTART"])
    except ValueError:
        return None

    time_s, dur = "", ""
    if not all_day:
        time_s = start.strftime("%H:%M")
        if "DTEND" in props:
            try:
                end, end_all_day = parse_dt(*props["DTEND"])
                if not end_all_day:
                    dur = str(int((end - start).total_seconds() // 60))
            except ValueError:
                pass
        elif "DURATION" in props:
            m = parse_duration_min(props["DURATION"][1])
            if m is not None:
                dur = str(m)

    def val(key):
        return flat(unescape(props[key][1])) if key in props else ""

    return (
        start.strftime("%Y-%m-%d"), time_s, dur, calname,
        val("SUMMARY"), val("LOCATION"), "y" if "RRULE" in props else "",
    )


def calendar_name(lines, fallback):
    """X-WR-CALNAME（Google が入れる表示名）を拾う。無ければファイル名を使う。"""
    for line in lines:
        if line.strip() == "BEGIN:VEVENT":
            break
        p = split_prop(line)
        if p and p[0] == "X-WR-CALNAME":
            name = flat(unescape(p[2]))
            if name:
                return name
    return fallback


def read_calendar(lines, calname):
    rows, props = [], None
    for line in lines:
        stripped = line.strip()
        if stripped == "BEGIN:VEVENT":
            props = {}
            continue
        if stripped == "END:VEVENT":
            if props is not None:
                row = build_row(props, calname)
                if row:
                    rows.append(row)
            props = None
            continue
        if props is None:
            continue
        p = split_prop(line)
        if p and p[0] in WANTED:
            props.setdefault(p[0], (p[1], p[2]))
    return rows


def is_holiday(stem):
    return "#holiday" in stem or "holiday@group.v.calendar.google.com" in stem


def selected(stem, name, opts):
    """このカレンダーを出力対象にするか。祝日カレンダーは常に除外。"""
    if is_holiday(stem):
        return False
    if opts["needle"]:
        return opts["needle"] in stem or opts["needle"] in name
    if opts["all"]:
        return True
    return "@group." not in stem  # 既定は個人アカウントのカレンダーだけ


def parse_args(argv):
    opts = {"zip_glob": "calendar-archive/*.zip", "dry": False, "all": False, "needle": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--dry-run":
            opts["dry"] = True
        elif a == "--all":
            opts["all"] = True
        elif a == "--calendar":
            i += 1
            opts["needle"] = argv[i] if i < len(argv) else None
        elif a.startswith("--calendar="):
            opts["needle"] = a.split("=", 1)[1]
        elif not a.startswith("--"):
            opts["zip_glob"] = a
        i += 1
    return opts


def main():
    opts = parse_args(sys.argv[1:])
    zips = sorted(glob.glob(opts["zip_glob"]))
    if not zips:
        sys.exit(
            f"ZIP が見つかりません: {opts['zip_glob']}\n"
            "Google カレンダー → 設定 → インポート/エクスポート → エクスポート で\n"
            "ダウンロードした ZIP を calendar-archive/ に置いてください。"
        )
    zip_path = zips[0]

    rows, skipped = [], []
    with zipfile.ZipFile(zip_path) as zf:
        for member in sorted(m for m in zf.namelist() if m.lower().endswith(".ics")):
            stem = member.rsplit("/", 1)[-1][:-4]
            lines = unfold(zf.read(member).decode("utf-8", errors="replace"))
            name = calendar_name(lines, stem)
            if not selected(stem, name, opts):
                skipped.append(name)
                continue
            rows.extend(read_calendar(lines, name))

    rows.sort(key=lambda r: (r[0], r[1]))

    print(f"読み込み: {zip_path}")
    print(f"予定の総数: {len(rows)} 件")
    if rows:
        print(f"期間: {rows[0][0]} 〜 {rows[-1][0]}")
        print(f"うち終日: {sum(1 for r in rows if not r[1])} 件 / "
              f"繰り返し: {sum(1 for r in rows if r[6])} 件")
        print("年ごとの件数:")
        by_year = Counter(r[0][:4] for r in rows)
        for y in sorted(by_year):
            print(f"  {y}: {by_year[y]} 件")
        print("カレンダーごとの件数:")
        for cal, n in Counter(r[3] for r in rows).most_common():
            print(f"  {cal}: {n} 件")
    if skipped:
        print(f"対象外にしたカレンダー: {', '.join(sorted(set(skipped)))}")

    if opts["dry"]:
        print("\n--dry-run のため書き出していません。")
        return

    with open(OUT, "w", encoding="utf-8") as w:
        w.write("date\tstart\tduration_min\tcalendar\ttitle\tlocation\trecurring\n")
        for row in rows:
            w.write("\t".join(row) + "\n")
    print(f"\n一覧を書き出しました: {OUT}")


if __name__ == "__main__":
    main()
