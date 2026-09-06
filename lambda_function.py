"""
AWS Lambda entry point for the daily EHC Winterthur schedule sync.

The daily EventBridge Scheduler invocation runs this handler, which assembles
the same inputs `sync.py` uses locally - but from Lambda-appropriate locations -
and then runs the identical extract -> supplement -> reconcile -> sync chain in
*apply* mode (dry_run=False). Nothing in that chain changes here; the handler
only sources its inputs differently:

  * The package dir under /var/task is read-only, so PDFs are fetched into
    /tmp/downloads (DOWNLOAD_DIR, the only writable path on Lambda). fetch_plans
    and spielplan_events both key off that one env var.
  * The season Spielplan PDFs are static per season; they live in S3 (uploaded
    once via `aws s3 cp`) and are pulled into DOWNLOAD_DIR at the start of each
    invocation. Locally SPIELPLAN_S3_PREFIX is unset, so this is a no-op and the
    local downloads/ dir is used unchanged.
  * Sync state persists in S3 (SYNC_STATE_URI), handled transparently by
    sync_state.

See docs/deploy.md for the deployment and IAM details.
"""

import json
import os
from pathlib import Path

DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", "/tmp/downloads"))
# s3://bucket/prefix/ holding the season Spielplan PDFs. Unset locally.
SPIELPLAN_S3_PREFIX = os.environ.get("SPIELPLAN_S3_PREFIX")


def _pull_spielplans(prefix: str, dest: Path) -> list[str]:
    """Download every *.pdf under an s3://bucket/prefix/ into `dest`.

    Returns the filenames pulled. The Lambda role grants s3:ListBucket (scoped
    to this prefix) and s3:GetObject; find_spielplan then discovers them in
    `dest` exactly as it would a local downloads/ dir."""
    import boto3

    bucket, _, key_prefix = prefix[len("s3://"):].partition("/")
    if not bucket:
        raise ValueError(f"malformed S3 prefix (need s3://bucket/prefix): {prefix!r}")
    s3 = boto3.client("s3")
    dest.mkdir(parents=True, exist_ok=True)
    pulled: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=key_prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.lower().endswith(".pdf"):
                name = Path(key).name
                s3.download_file(bucket, key, str(dest / name))
                pulled.append(name)
    return pulled


def handler(event, context):
    # Imported inside the handler so a cold start reads the env-configured
    # DOWNLOAD_DIR before fetch_plans binds its module-level default.
    from fetch_plans import fetch_all, latest_local_pdfs
    from google_calendar import get_calendar_service
    from sync import sync_team
    import sync_state

    try:
        from sync_configs import CONFIGS
    except ImportError:
        from sync_configs_example import CONFIGS

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Fetch the current/future Wochenplan PDFs (fetch_all warns loudly and
    # continues past any single download failure, so a missing week is never
    # silent), then pull the static season Spielplans from S3.
    fetch_all(DOWNLOAD_DIR)
    if SPIELPLAN_S3_PREFIX:
        pulled = _pull_spielplans(SPIELPLAN_S3_PREFIX, DOWNLOAD_DIR)
        print(f"Pulled {len(pulled)} Spielplan PDF(s) from {SPIELPLAN_S3_PREFIX}")

    pdfs = latest_local_pdfs(DOWNLOAD_DIR)
    print(f"APPLY: {len(pdfs)} weeks, {len(CONFIGS)} team(s)")

    service = get_calendar_service()
    state = sync_state.load(sync_state.DEFAULT_STATE_URI)
    results = []
    for config in CONFIGS:
        try:
            result = sync_team(service, config, pdfs, dry_run=False, state=state)
        except Exception as exc:  # one team's failure must not sink the rest
            result = {"team": config.get("team"), "error": str(exc)}
        print(json.dumps(result, ensure_ascii=False))
        results.append(result)

    # Persist state (S3 on Lambda) so manual deletions stay honored next run.
    sync_state.save(sync_state.DEFAULT_STATE_URI, state)

    return {"weeks": len(pdfs), "teams": results}
