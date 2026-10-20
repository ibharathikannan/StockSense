#!/usr/bin/env bash
#
# Nightly StockSense data refresh (the 4 steps in docs/ai/OPERATIONAL_MODEL.md):
#   1. collect the day's Marketaux news for the 90-ticker universe (dedup by document_id)
#   2. embed only the new news chunks into the evidence index (incremental)
#   3. aggregate sentiment + assemble recommendation snapshots (reads saved forecasts if present)
#   4. load the snapshots into the application database the backend serves
#
# It is idempotent: re-running a day appends only new news and overwrites that day's snapshots.
# Marketaux free tier is 100 requests/day; the universe is 90 tickers (1 request each), so one
# run/night fits. Run it AFTER US market close.
#
# Usage:   data/run_nightly.sh
# Cron:    0 2 * * *  /abs/path/to/worktrees/rag/data/run_nightly.sh >> /abs/path/to/nightly.log 2>&1
#
# Override these with env vars if your layout differs:
#   DATA_PY            python with the data deps   (default: the ai worktree's .venv-data)
#   BACKEND_PY         python with the backend deps (default: backend/.venv)
#   DATA_ENV_FILE      data API keys + research DB  (default: data/.env)
#   FORECAST_RESULTS_DIR  dir holding forecasts.csv + report.json (optional; placeholder if unset)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # the rag worktree root
DATA_PY="${DATA_PY:-$REPO/../ai/.venv-data/bin/python}"
BACKEND_PY="${BACKEND_PY:-$REPO/backend/.venv/bin/python}"
# The data API keys live in the ai worktree's data/.env by default (that is where collection set
# them up); override DATA_ENV_FILE if you keep them elsewhere.
DATA_ENV_FILE="${DATA_ENV_FILE:-$REPO/../ai/data/.env}"

# A lock so two nights (or a slow run) never overlap. flock is Linux-only; on macOS, fall back
# to an atomic mkdir lock that is cleaned up on exit.
if command -v flock >/dev/null 2>&1; then
  exec 9>"$REPO/data/.nightly.lock"
  flock -n 9 || { echo "$(date -u +%FT%TZ) another nightly run is in progress; exiting"; exit 0; }
else
  LOCK_DIR="$REPO/data/.nightly.lock.d"
  mkdir "$LOCK_DIR" 2>/dev/null || { echo "$(date -u +%FT%TZ) another nightly run is in progress; exiting"; exit 0; }
  trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
fi

cd "$REPO"
echo "=== $(date -u +%FT%TZ) nightly refresh starting ==="

echo "[1/4] collecting Marketaux news"
"$DATA_PY" -m data.collect_marketaux_news --env-file "$DATA_ENV_FILE"

echo "[2/4] embedding new news evidence"
"$DATA_PY" -m data.rag.embed_marketaux_evidence --env-file "$DATA_ENV_FILE" \
    --artifact data/artifacts/marketaux/documents.jsonl

echo "[3/4] assembling snapshots"
if [ -n "${FORECAST_RESULTS_DIR:-}" ]; then
  "$DATA_PY" -m data.rag.assemble_snapshots --env-file "$DATA_ENV_FILE" --forecasts "$FORECAST_RESULTS_DIR"
else
  "$DATA_PY" -m data.rag.assemble_snapshots --env-file "$DATA_ENV_FILE"
fi

echo "[4/4] loading snapshots into the app database"
cd "$REPO/backend"
"$BACKEND_PY" -m scripts.load_snapshots \
    --snapshots ../data/artifacts/snapshots/snapshots.jsonl \
    --profiles ../data/processed/asset_profiles.json

echo "=== $(date -u +%FT%TZ) nightly refresh done ==="
