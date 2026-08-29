"""
Google Calendar auth, reusing the same AWS SSM-backed service account secret
as the aws-ical-sync project (same Google service account, already shared
with the target calendars).
"""

import json
import os
from datetime import date, datetime
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build

SSM_PARAM_NAME = os.environ.get("SSM_PARAM_NAME", "/ical-sync/google-service-account")
# For local test runs: a service-account JSON key on disk is used if present,
# so no AWS access is needed. Defaults to a gitignored file in the project root.
SERVICE_ACCOUNT_FILE = os.environ.get(
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    str(Path(__file__).parent / ".google-service-account.json"),
)


def get_service_account_info() -> dict:
    path = Path(SERVICE_ACCOUNT_FILE)
    if path.is_file():
        return json.loads(path.read_text())
    # Fall back to AWS SSM Parameter Store (how the deployed job reads it).
    import boto3

    ssm = boto3.client("ssm")
    resp = ssm.get_parameter(Name=SSM_PARAM_NAME, WithDecryption=True)
    return json.loads(resp["Parameter"]["Value"])


def get_calendar_service():
    info = get_service_account_info()
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/calendar"]
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _parse_edge(edge: dict) -> datetime:
    """A Google event start/end is either {"dateTime": ...} or {"date": ...}."""
    if "dateTime" in edge:
        # Drop tz-awareness so it compares with the naive PDF event datetimes.
        return datetime.fromisoformat(edge["dateTime"]).replace(tzinfo=None)
    return datetime.combine(date.fromisoformat(edge["date"]), datetime.min.time())


def list_event_intervals(
    service, calendar_id: str, uid_prefix: str, time_min: datetime, time_max: datetime
) -> list[tuple[datetime, datetime]]:
    """Returns (start, end) intervals of events on `calendar_id` whose iCalUID
    starts with `uid_prefix` (e.g. the myice "mih-ehc-" feed), within the given
    window. Used to detect overlaps with PDF-derived events."""
    intervals: list[tuple[datetime, datetime]] = []
    page_token = None
    while True:
        resp = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min.isoformat() + "Z",
                timeMax=time_max.isoformat() + "Z",
                singleEvents=True,
                showDeleted=False,
                maxResults=2500,
                pageToken=page_token,
            )
            .execute()
        )
        for event in resp.get("items", []):
            if not event.get("iCalUID", "").startswith(uid_prefix):
                continue
            intervals.append((_parse_edge(event["start"]), _parse_edge(event["end"])))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return intervals
