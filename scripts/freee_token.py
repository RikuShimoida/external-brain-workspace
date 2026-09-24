#!/usr/bin/env python3
"""freee の初回認証（OAuth）。トークンを freee-archive/_secrets/tokens.json に保存する。

旧リポジトリ freee-transaction-agent の scripts/get-token.mjs を移植したもの（#75）。
オーナーがターミナルで対話的に実行する（認可コードをチャットに貼らない）。

前提:
  - .env に FREEE_CLIENT_ID / FREEE_CLIENT_SECRET（freee アプリストアの自分用アプリ）
  - そのアプリのコールバック URL が urn:ietf:wg:oauth:2.0:oob
  - 旧リポジトリの Vercel Cron を止めてあること。リフレッシュトークンは1回使い捨てなので、
    旧 Cron が動いていると新旧で取り合い、どちらかが認証切れになる。

使い方:
    python3 scripts/freee_token.py            … 認証して保存し、事業所一覧で疎通確認
    python3 scripts/freee_token.py --check    … 保存済みトークンで疎通確認だけ
      --root パス   … リポジトリのルート（既定: カレント）
"""
import argparse
import sys
import urllib.parse
from pathlib import Path

from freee_client import AUTHORIZE_URL, TOKEN_URL, TOKENS_REL, FreeeClient, load_env, post_form, save_tokens

REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"


def authorize(root: Path) -> None:
    env = load_env(root)
    client_id = env.get("FREEE_CLIENT_ID", "")
    client_secret = env.get("FREEE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        sys.exit("FREEE_CLIENT_ID / FREEE_CLIENT_SECRET が .env にありません（README の freee 節）")

    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": REDIRECT_URI, "response_type": "code",
    })
    print("1. 次の URL をブラウザで開いて「許可する」を押してください:\n")
    print(url + "\n")
    code = input("2. 表示された認可コードを貼り付けて Enter ▶ ").strip()
    if not code:
        sys.exit("認可コードが空です")

    data = post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": REDIRECT_URI,
    })
    path = save_tokens(root, {"access_token": data["access_token"], "refresh_token": data["refresh_token"]})
    print(f"保存しました: {path.relative_to(root)}（権限600・Git 管理外）", file=sys.stderr)


def check(root: Path) -> None:
    client = FreeeClient(root)
    companies = client.get_companies()
    print(f"疎通OK: 事業所 {len(companies)} 件（使う事業所 ID: {client.company_id}）", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--check", action="store_true", help="保存済みトークンで疎通確認だけ")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    if not args.check:
        authorize(root)
    elif not (root / TOKENS_REL).exists():
        sys.exit(f"{TOKENS_REL} がありません。まず --check なしで実行してください。")
    check(root)


if __name__ == "__main__":
    main()
