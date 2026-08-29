#!/usr/bin/env bash
#
# Run the Wochenplan tooling locally, using a local service-account key
# instead of AWS SSM.
#
#   bash run-local.sh              # fetch latest PDFs, then DRY-RUN sync (writes nothing)
#   bash run-local.sh --apply      # fetch, then actually create/update events
#   bash run-local.sh list         # fetch, then write the event preview to events.txt
#   SKIP_FETCH=1 bash run-local.sh # skip the download step, use what's on disk
#
# Invoke it with `bash run-local.sh` - this directory is a noexec mount, so
# executing it directly (./run-local.sh) is blocked.
#
# The service-account JSON is read from .google-service-account.json in this
# directory (gitignored), or from $GOOGLE_SERVICE_ACCOUNT_FILE if set. The
# `list` mode needs no key (it never touches Google Calendar).
set -euo pipefail

cd "$(dirname "$0")"

MODE="sync"
if [[ "${1:-}" == "list" || "${1:-}" == "--list" ]]; then
  MODE="list"
  shift
fi

# This project directory is a noexec mount that breaks mmap-loading of compiled
# .so files, so the venv must live on a normal filesystem.
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$HOME/.venvs/ehcw-trainings}"

if [[ "${SKIP_FETCH:-}" != "1" ]]; then
  echo "Fetching latest Wochenplan PDFs..."
  uv run python fetch_plans.py
fi

if [[ "$MODE" == "list" ]]; then
  uv run python list_events.py "$@"
  echo "Wrote events.txt"
  exit 0
fi

KEY_FILE="${GOOGLE_SERVICE_ACCOUNT_FILE:-$PWD/.google-service-account.json}"
if [[ ! -f "$KEY_FILE" ]]; then
  echo "ERROR: service-account key not found at: $KEY_FILE" >&2
  echo "Save your Google service-account JSON there, or set" >&2
  echo "GOOGLE_SERVICE_ACCOUNT_FILE to point at it." >&2
  exit 1
fi
export GOOGLE_SERVICE_ACCOUNT_FILE="$KEY_FILE"

uv run python sync.py "$@"
