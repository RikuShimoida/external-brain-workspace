#!/usr/bin/env python3
"""音声・動画をローカルで文字起こしし、本人のセリフだけを話し言葉に合流させる。

voice_parse.py の話し言葉はもともと「音声入力のテキスト」だけで、人を笑わせにいくときの話し方
（ネタの間・言い回し・ボケ方）が分からない。ここで録音（文化祭のコント動画・ボイスメモなど）を
文字起こしして、voice_parse.iter_audio() から読める形にする。

- **音声を外部に送らない。** macOS 標準の afconvert で 16kHz モノラル WAV にし、whisper-cpp
  （brew の whisper-cli・Apple Silicon の Metal で動く）で日本語の文字起こしをする。ffmpeg は使わない。
- **本人のセリフだけを取り込む。** 録音には共演者・家族の声が入る。話者の自動分離はせず、
  オーナーが --show の番号を見て自分のセリフを選び、--keep で <名前>.self.txt に書く。
  **.self.txt が無い録音は voice_parse に読まれない**（確認前の第三者発話を持ち込まない既定）。

置き場所（すべて voice-archive/ 配下・Git 管理外）:
    _raw/audio/<名前>.<mp4|m4a|wav|...>   … 元の録音
    _raw/transcripts/<名前>.srt           … whisper の出力（全セグメント）
    _raw/transcripts/<名前>.self.txt      … オーナーが選んだ本人のセリフだけ（1行1セグメント）
    .models/ggml-large-v3-turbo.bin        … モデル（約1.6GB。不要になれば消してよい）

使い方:
    python3 scripts/voice_transcribe.py [--dry-run]         # 未処理の録音を文字起こし（済みはスキップ）
    python3 scripts/voice_transcribe.py --show <名前>        # セグメントを番号・時刻つきで表示
    python3 scripts/voice_transcribe.py --keep <名前> 1,3,5  # 本人のセリフを選んで .self.txt に
    python3 scripts/voice_transcribe.py --keep <名前> all    # 独り語りなら全部
    python3 scripts/voice_transcribe.py --keep <名前> - < 訂正済み.txt
        # オーナーが自分のセリフを正しい言葉で書き直して渡す（1行1セリフ）。自動の文字起こしは
        # 固有名詞・掛け声・早口を聞き違えやすく、取りこぼしもある（実例: 文化祭のコントで
        # 「ショートコント」→「ソートボット」、1セリフまるごと欠落）。本人の訂正を正とする。
"""
import os
import re
import sys
import glob
import shutil
import subprocess

AUDIO_DIR = "voice-archive/_raw/audio"
TRANS_DIR = "voice-archive/_raw/transcripts"
CACHE_DIR = "voice-archive/.cache"
MODEL = "voice-archive/.models/ggml-large-v3-turbo.bin"
EXTS = (".mp4", ".m4a", ".mov", ".wav", ".aac", ".caf", ".mp3")

_SRT_BLOCK = re.compile(
    r"(\d+)\s*\n(\d\d:\d\d:\d\d[,.]\d+)\s*-->\s*(\d\d:\d\d:\d\d[,.]\d+)\s*\n(.*?)(?:\n\s*\n|\Z)",
    re.DOTALL,
)


def _name(path):
    return os.path.splitext(os.path.basename(path))[0]


def pending():
    """文字起こしが未処理の録音。"""
    out = []
    for path in sorted(glob.glob(f"{AUDIO_DIR}/*")):
        if not path.lower().endswith(EXTS):
            continue
        if not os.path.exists(f"{TRANS_DIR}/{_name(path)}.srt"):
            out.append(path)
    return out


def transcribe(path):
    name = _name(path)
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(TRANS_DIR, exist_ok=True)
    wav = f"{CACHE_DIR}/{name}.wav"
    try:
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", path, wav],
                       check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"  × {name}: afconvert で読めません（{e.stderr.decode(errors='ignore').strip()[:80]}）。"
              "形式によっては ffmpeg が要る。", file=sys.stderr)
        return False
    try:
        subprocess.run(["whisper-cli", "-m", MODEL, "-l", "ja", "-osrt",
                        "-of", f"{TRANS_DIR}/{name}", "-f", wav],
                       check=True, capture_output=True)
    finally:
        os.remove(wav)  # WAV は大きいので残さない
    return True


def segments(name):
    """[(番号, 開始, 終了, 本文)]。番号は1始まり。"""
    path = f"{TRANS_DIR}/{name}.srt"
    if not os.path.exists(path):
        sys.exit(f"{path} がありません（先に文字起こしを実行）")
    with open(path, encoding="utf-8") as f:
        text = f.read().replace("\r", "")
    out = []
    for m in _SRT_BLOCK.finditer(text):
        body = " ".join(m.group(4).split())
        if body:
            out.append((int(m.group(1)), m.group(2)[:8], m.group(3)[:8], body))
    return out


def show(name):
    for i, start, end, body in segments(name):
        print(f"{i:>3}  {start}-{end}  {body}")


def keep(name, spec):
    if spec == "-":
        lines = [l.strip() for l in sys.stdin.read().splitlines() if l.strip()]
        with open(f"{TRANS_DIR}/{name}.self.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"オーナーが訂正したセリフ {len(lines)} 行を {TRANS_DIR}/{name}.self.txt に書きました。")
        return
    segs = segments(name)
    if spec == "all":
        chosen = segs
    else:
        want = {int(x) for x in spec.split(",") if x.strip()}
        chosen = [s for s in segs if s[0] in want]
        missing = want - {s[0] for s in chosen}
        if missing:
            sys.exit(f"存在しない番号: {sorted(missing)}")
    with open(f"{TRANS_DIR}/{name}.self.txt", "w", encoding="utf-8") as f:
        for _, _, _, body in chosen:
            f.write(body + "\n")
    print(f"{len(chosen)}/{len(segs)} セグメントを {TRANS_DIR}/{name}.self.txt に書きました。")


def main():
    argv = sys.argv[1:]
    if "--show" in argv:
        show(argv[argv.index("--show") + 1])
        return
    if "--keep" in argv:
        i = argv.index("--keep")
        keep(argv[i + 1], argv[i + 2])
        return

    todo = pending()
    print(f"未処理の録音: {len(todo)} 件")
    for p in todo:
        print(f"  - {os.path.basename(p)}")
    if "--dry-run" in argv or not todo:
        return
    if not shutil.which("whisper-cli") or not os.path.exists(MODEL):
        sys.exit("whisper-cli かモデルがありません（brew install whisper-cpp / モデルの置き場所は docs 参照）")
    ok = sum(1 for p in todo if transcribe(p))
    print(f"文字起こし: {ok}/{len(todo)} 件 → {TRANS_DIR}/")
    print("次: --show <名前> で本人のセリフの番号を確認し、--keep <名前> <番号> で取り込む。")


if __name__ == "__main__":
    main()
