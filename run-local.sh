#!/usr/bin/env bash
#
# Run the Wochenplan tooling locally, reading the Google service-account key
# from a local file instead of AWS SSM. See --help for usage.
set -euo pipefail

cd "$(dirname "$0")"

usage() {
  cat <<'USAGE'
Run the Wochenplan tooling locally, using a local service-account key
instead of AWS SSM.

Usage:
  ./run-local.sh            Fetch latest PDFs, then a DRY-RUN sync (writes nothing)
  ./run-local.sh --apply    Fetch, then actually create/update calendar events
  ./run-local.sh --list     Fetch, then write the event preview to events.txt
  ./run-local.sh --help     Show this help

Environment:
  SKIP_FETCH=1                 Skip the download; use the PDFs already on disk
  GOOGLE_SERVICE_ACCOUNT_FILE  Path to the service-account JSON
                               (default: ./.google-service-account.json)

--list needs no key (it never touches Google Calendar); the sync modes read
the key from the file above.
USAGE
}

MODE="sync"
case "${1:-}" in
  -h | --help)
    usage
    exit 0
    ;;
  --list | list)
    MODE="list"
    shift
    ;;
esac

# Reuse a dedicated venv outside the project tree (its original reason - a
# noexec mount - is gone now that the project lives on ext4, but keeping it
# avoids rebuilding the heavy venv). Override by exporting UV_PROJECT_ENVIRONMENT.
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
