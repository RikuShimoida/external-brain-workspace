#!/usr/bin/env bash
# .env を読み込んでから Claude Code を起動するヘルパー。
# X (Twitter) MCP に必要な環境変数を .mcp.json へ渡すために使う。
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
else
  echo "警告: .env が見つかりません。.env.example をコピーして作成してください。" >&2
fi

exec claude "$@"
