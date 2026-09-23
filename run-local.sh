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
  SYNC_STATE_URI               Explicit sync-state location (s3://... or a path).
                               Default: the same S3 object the deployed Lambda
                               uses, so local runs cannot diverge from it.
  LOCAL_STATE=1                Deliberately use the local ./sync-state.json.
  AWS_PROFILE                  Profile used to locate the S3 state
                               (default: workload).

--list needs no key (it never touches Google Calendar); the sync modes read
the key from the file above.

The sync state records which events we created and which ones you deleted by
hand. The deployed Lambda keeps it in S3, so a local --apply that wrote to a
local file instead would drift out of sync and could resurrect events you
deleted. --apply therefore requires the shared S3 state; a dry-run falls back
to the local file (with a loud warning) when AWS is unavailable.
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

# --- Shared sync state -------------------------------------------------------
# The sync state holds the tombstones ("you deleted this event, stay away") and
# the list of events we created. The deployed Lambda keeps it in S3; if a local
# run kept its own copy the two would diverge and each would undo the other's
# deletions. So default to the same S3 object the Lambda uses.
APPLY=0
for arg in "$@"; do
  [[ "$arg" == "--apply" ]] && APPLY=1
done

if [[ -z "${SYNC_STATE_URI:-}" && "${LOCAL_STATE:-}" != "1" ]]; then
  AWS_PROFILE="${AWS_PROFILE:-workload}"
  export AWS_PROFILE
  if ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)"; then
    export SYNC_STATE_URI="s3://ehcw-trainings-${ACCOUNT_ID}/ehcw-trainings/sync-state.json"
    # The SSO profile's credential provider needs botocore[crt], which the
    # project venv does not ship. Let the AWS CLI resolve the credentials and
    # hand them to boto3 as environment variables instead. botocore ignores
    # those when AWS_PROFILE is set explicitly, so drop it once they are set.
    if CREDS="$(aws configure export-credentials --format env-no-export 2>/dev/null)"; then
      set -a; eval "$CREDS"; set +a
      unset CREDS AWS_PROFILE
    fi
  elif [[ "$APPLY" == "1" ]]; then
    echo "ERROR: no valid AWS credentials for profile '$AWS_PROFILE'." >&2
    echo "       --apply needs the shared S3 sync state: writing the calendar" >&2
    echo "       while keeping state locally would diverge from the deployed" >&2
    echo "       Lambda and could re-create events you deleted by hand." >&2
    echo "       Run 'source ./aws-login.sh' first, or - if you really mean" >&2
    echo "       to use ./sync-state.json - re-run with LOCAL_STATE=1." >&2
    exit 1
  else
    echo "***************************************************************" >&2
    echo "WARNING: not logged in to AWS (profile '$AWS_PROFILE')."          >&2
    echo "         Falling back to the LOCAL ./sync-state.json, which may"  >&2
    echo "         be stale or ahead of the state the Lambda actually uses.">&2
    echo "         This dry-run's created/deleted counts can therefore be"  >&2
    echo "         wrong. Run 'source ./aws-login.sh' for a true preview."  >&2
    echo "***************************************************************" >&2
  fi
fi
echo "Sync state: ${SYNC_STATE_URI:-./sync-state.json (local)}"

uv run python sync.py "$@"
