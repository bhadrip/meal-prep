#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "Install backend dependencies first: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
  exit 1
fi

supabase start >/dev/null
supabase_env="$(supabase status -o env)"
supabase_url="$(printf '%s\n' "$supabase_env" | sed -n 's/^API_URL="\([^"]*\)"$/\1/p')"
supabase_anon_key="$(printf '%s\n' "$supabase_env" | sed -n 's/^ANON_KEY="\([^"]*\)"$/\1/p')"
supabase_secret_key="$(printf '%s\n' "$supabase_env" | sed -n 's/^SECRET_KEY="\([^"]*\)"$/\1/p')"

if [[ -z "$supabase_url" || -z "$supabase_anon_key" || -z "$supabase_secret_key" ]]; then
  echo "Could not read the local Supabase URL and keys from 'supabase status -o env'." >&2
  exit 1
fi

export APP_BASE_URL="http://127.0.0.1:8000"
export SUPABASE_URL="$supabase_url"
export SUPABASE_ANON_KEY="$supabase_anon_key"
export SUPABASE_SECRET_KEY="$supabase_secret_key"
export AUTH_REQUIRED=true

exec .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
