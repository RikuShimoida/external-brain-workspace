#!/usr/bin/env python3
"""freee 会計 API のクライアント（読み取り＋自動登録ルールの作成だけ）。

旧リポジトリ freee-transaction-agent の lib/freee.mjs を移植したもの（#75）。
freee MCP は「ちょっと聞く」読み取り用。こちらは /freee スキルが使う、件数の多い取得と
ルール作成のための経路。

書き込みのガードレール（7/13 に 578件の取引を誤削除した事故の教訓）:
  - 書けるのは自動登録ルールの作成（POST /api/1/user_matchers）だけ。削除・更新・取引登録は
    このクライアントからは一切できない（request() が GET 以外を弾く）。
  - ルールを作る前に、作成前の状態を保存したスナップショットのパスを渡さないと例外になる。
  - 口座で絞って取った明細は、本当にその口座のものかを1件ずつ検算する
    （deals は walletable_id の絞り込みを黙って無視した。同じ落とし穴を踏まない）。

認証:
  - クライアント ID / シークレットは .env の FREEE_CLIENT_ID / FREEE_CLIENT_SECRET。
  - トークンは freee-archive/_secrets/tokens.json（権限600・Git 管理外）。初回は freee_token.py。
  - アクセストークンは6時間で切れる。401 を受けたら1回だけ更新して再試行する。
    リフレッシュトークンは1回使い捨てなので、更新したら必ず保存し直す。

標準ライブラリのみ。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_BASE = "https://api.freee.co.jp"
TOKEN_URL = "https://accounts.secure.freee.co.jp/public_api/token"
AUTHORIZE_URL = "https://accounts.secure.freee.co.jp/public_api/authorize"
API_VERSION = "2020-06-15"

ARCHIVE_REL = "freee-archive"
TOKENS_REL = "freee-archive/_secrets/tokens.json"

# このクライアントが許す唯一の書き込み
USER_MATCHERS_PATH = "/api/1/user_matchers"


class WriteGuardError(RuntimeError):
    """書き込みのガードレールに引っかかった（スナップショット無し・許可外の書き込みなど）。"""


class FreeeApiError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, body):
        super().__init__(f"freee API {method} {path} → {status}: {json.dumps(body, ensure_ascii=False)[:500]}")
        self.status = status
        self.body = body


def load_env(root: Path) -> dict[str, str]:
    """環境変数を優先し、無ければ <root>/.env から FREEE_* を読む。"""
    env: dict[str, str] = {}
    path = root / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("'\"")
    for k, v in os.environ.items():
        if k.startswith("FREEE_") and v:
            env[k] = v
    return env


def save_tokens(root: Path, tokens: dict) -> Path:
    path = root / TOKENS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def load_tokens(root: Path) -> dict:
    path = root / TOKENS_REL
    if not path.exists():
        raise SystemExit(f"{TOKENS_REL} がありません。先に python3 scripts/freee_token.py で認証してください。")
    return json.loads(path.read_text(encoding="utf-8"))


def post_form(url: str, form: dict) -> dict:
    """トークン発行・更新用（application/x-www-form-urlencoded）。"""
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise FreeeApiError("POST", url, e.code, e.read().decode(errors="replace")) from None


def check_snapshot(snapshot: Path | None) -> None:
    """書き込み前のスナップショットが実在し、作成前のルール一覧を含むことを確かめる。"""
    if snapshot is None:
        raise WriteGuardError("スナップショット無しでは書き込めません（書く前に作成前の状態を保存すること）")
    p = Path(snapshot)
    if not p.is_file():
        raise WriteGuardError(f"スナップショットが見つかりません: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise WriteGuardError(f"スナップショットが読めません: {p} ({e})") from None
    if not isinstance(data, dict) or "user_matchers" not in data:
        raise WriteGuardError(f"スナップショットに作成前のルール一覧（user_matchers）がありません: {p}")


def check_same_wallet(txns: list[dict], walletable_type: str, walletable_id: int) -> None:
    """口座で絞って取った明細が、本当にその口座のものかを検算する（7/13 の教訓）。"""
    wrong = [t for t in txns
             if t.get("walletable_id") != walletable_id or t.get("walletable_type") != walletable_type]
    if wrong:
        raise RuntimeError(
            f"口座 {walletable_type}:{walletable_id} で絞ったのに、別口座の明細が {len(wrong)} 件混ざっています。"
            " API が絞り込みを無視している可能性があるため中断します。"
        )


class FreeeClient:
    def __init__(self, root: Path):
        self.root = Path(root)
        env = load_env(self.root)
        self.client_id = env.get("FREEE_CLIENT_ID", "")
        self.client_secret = env.get("FREEE_CLIENT_SECRET", "")
        if not self.client_id or not self.client_secret:
            raise SystemExit("FREEE_CLIENT_ID / FREEE_CLIENT_SECRET が .env にありません（README の freee 節）")
        self._company_id = int(env["FREEE_COMPANY_ID"]) if env.get("FREEE_COMPANY_ID") else None
        self._tokens = load_tokens(self.root)

    # --- 低レベル ---

    def _refresh(self) -> None:
        data = post_form(TOKEN_URL, {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self._tokens["refresh_token"],
        })
        self._tokens = {"access_token": data["access_token"], "refresh_token": data["refresh_token"]}
        save_tokens(self.root, self._tokens)  # 使い捨てなので必ず保存し直す

    def _send(self, method: str, path: str, params: dict | None, body: dict | None, retried: bool = False):
        url = API_BASE + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        headers = {
            "Authorization": f"Bearer {self._tokens['access_token']}",
            "X-Api-Version": API_VERSION,
            "Accept": "application/json",
        }
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                text = res.read().decode()
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as e:
            if e.code == 401 and not retried:
                self._refresh()
                return self._send(method, path, params, body, retried=True)
            text = e.read().decode(errors="replace")
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = text
            raise FreeeApiError(method, path, e.code, parsed) from None

    def request(self, path: str, params: dict | None = None):
        """読み取り専用の API 呼び出し。GET 以外はここからは送れない。"""
        return self._send("GET", path, params, None)

    # --- 読み取り ---

    @property
    def company_id(self) -> int:
        if self._company_id is None:
            companies = self.request("/api/1/companies").get("companies", [])
            if not companies:
                raise SystemExit("freee の事業所が見つかりません")
            self._company_id = companies[0]["id"]
        return self._company_id

    def get_companies(self) -> list[dict]:
        return self.request("/api/1/companies").get("companies", [])

    def get_walletables(self) -> list[dict]:
        return self.request("/api/1/walletables", {"company_id": self.company_id}).get("walletables", [])

    def get_account_items(self) -> list[dict]:
        return self.request("/api/1/account_items", {"company_id": self.company_id}).get("account_items", [])

    def get_taxes(self) -> list[dict]:
        return self.request(f"/api/1/taxes/companies/{self.company_id}").get("taxes", [])

    def get_wallet_txns(self, walletable_type: str, walletable_id: int) -> list[dict]:
        """指定口座の全明細（ページング）。取得後に口座の一致を検算する。"""
        out: list[dict] = []
        offset = 0
        while True:
            page = self.request("/api/1/wallet_txns", {
                "company_id": self.company_id,
                "walletable_type": walletable_type,
                "walletable_id": walletable_id,
                "limit": 100,
                "offset": offset,
            }).get("wallet_txns", [])
            out.extend(page)
            if len(page) < 100:
                break
            offset += 100
        check_same_wallet(out, walletable_type, walletable_id)
        return out

    def get_unprocessed_txns(self) -> list[dict]:
        """全口座の未処理明細（status=1＝消込待ち）。口座名・種別を _wallet_name / _wallet_type に付ける。"""
        result: list[dict] = []
        for w in self.get_walletables():
            for t in self.get_wallet_txns(w["type"], w["id"]):
                if t.get("status") == 1:
                    result.append({**t, "_wallet_name": w["name"], "_wallet_type": w["type"]})
        return result

    def get_user_matchers(self) -> list[dict]:
        """自動登録ルールの全件（ページング）。"""
        out: list[dict] = []
        offset = 0
        while True:
            page = self.request(USER_MATCHERS_PATH, {
                "company_id": self.company_id, "limit": 100, "offset": offset,
            }).get("data", [])
            out.extend(page)
            if len(page) < 100:
                break
            offset += 100
        return out

    # --- 書き込み（これだけ） ---

    def create_user_matcher(self, payload: dict, *, snapshot: Path | None) -> dict:
        """自動登録ルールを1件作る。作成前の状態を保存したスナップショットが必須。"""
        check_snapshot(snapshot)
        body = {"company_id": self.company_id, **payload}
        return self._send("POST", USER_MATCHERS_PATH, {"company_id": self.company_id}, body)
