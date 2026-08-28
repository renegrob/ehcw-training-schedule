"""
Sync the PDF-derived events into Google Calendar.

Same idempotent approach as aws-ical-sync: every event is pushed via
events.import() keyed on a namespaced iCalUID, so Google creates it if new or
updates it in place if the UID already exists - no database needed. Our events
are tagged with a private extendedProperty ("source=ehcw-trainings") so the
reconciliation only ever touches events *we* created and never the myice
("mih-ehc-") ones. Events that disappear from the plans are deleted.

Dry-run is the default: it reads the calendar and reports exactly what it
would create/update/delete, but writes nothing. Pass --apply to actually
write. (list_events.py remains the offline, no-credentials preview.)
"""

import argparse
import hashlib
import json
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from extract_events import Event, safe_extract
from fetch_plans import latest_local_pdfs
from google_calendar import get_calendar_service, list_event_intervals
from overlap import DEFAULT_MIH_UID_PREFIX, KEEP, resolve_mih_overlap, validate_policy

try:
    from sync_configs import CONFIGS
except ImportError:
    from sync_configs_example import CONFIGS

SOURCE_TAG = "ehcw-trainings"
DEFAULT_TIMEZONE = os.environ.get("DEFAULT_TIMEZONE", "Europe/Zurich")
# Events already ended are neither created nor deleted - just left alone.
SKIP_PAST_EVENTS = os.environ.get("SKIP_PAST_EVENTS", "true").lower() != "false"
ERROR_COLOR_ID = "11"  # Tomato - loud, for fail-loud markers

_COMPARE_FIELDS = ("summary", "location", "description", "colorId", "start", "end", "status")


# ---------------------------------------------------------------------------
# Building Google event bodies
# ---------------------------------------------------------------------------

def _uid(event: Event, uid_prefix: str) -> str:
    """Stable, namespaced iCalUID. Encodes the event's identity (source, day,
    time, type) so a re-run upserts the same event; a changed time yields a new
    UID (old one is then reconciled away, never duplicated)."""
    identity = "|".join(
        [
            event.source,
            event.day_date.isoformat(),
            event.time_start or "allday",
            event.type,
            "ERR" if event.is_error else "",
        ]
    )
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:20]
    return f"{uid_prefix}{digest}"


def _description(event: Event) -> str:
    lines = []
    if event.type_full and event.type_full != event.type:
        lines.append(f"Art: {event.type_full}")
    if event.garderobe:
        lines.append(f"Garderobe: {event.garderobe}")
    if event.transport:
        lines.append(f"Transport: {event.transport}")
    lines.extend(event.notes)
    lines.append(f"Quelle: {event.source}")
    return "\n".join(lines)


def event_to_body(event: Event, config: dict, uid_prefix: str) -> dict:
    tzname = config.get("timezone", DEFAULT_TIMEZONE)
    color_id = (
        ERROR_COLOR_ID if event.is_error else (event.color_id or config.get("color_id"))
    )

    body = {
        "iCalUID": _uid(event, uid_prefix),
        "summary": event.summary,
        # Games are a heads-up, not a confirmed call-up.
        "status": "tentative" if event.is_game else "confirmed",
        "extendedProperties": {"private": {"source": SOURCE_TAG}},
        "reminders": {"useDefault": True},
    }
    if event.place:
        body["location"] = event.place
    description = _description(event)
    if description:
        body["description"] = description
    if color_id:
        body["colorId"] = str(color_id)

    if event.all_day:
        start = event.day_date
        body["start"] = {"date": start.isoformat()}
        body["end"] = {"date": (start + timedelta(days=1)).isoformat()}
    else:
        body["start"] = {"dateTime": event.start_datetime().isoformat(), "timeZone": tzname}
        body["end"] = {"dateTime": event.end_datetime().isoformat(), "timeZone": tzname}

    return body


def _is_past(event: Event, tzname: str) -> bool:
    now = datetime.now(ZoneInfo(tzname)).replace(tzinfo=None)
    return event.end_datetime() < now


def _existing_is_past(existing_event: dict, tzname: str) -> bool:
    """Whether an event already on the calendar has already ended."""
    end = existing_event.get("end", {})
    if "dateTime" in end:
        ended = datetime.fromisoformat(end["dateTime"]).replace(tzinfo=None)
    elif "date" in end:
        ended = datetime.combine(date.fromisoformat(end["date"]), datetime.min.time())
    else:
        return False
    return ended < datetime.now(ZoneInfo(tzname)).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Reconciliation (create / update / delete)
# ---------------------------------------------------------------------------

def list_existing(service, calendar_id: str, uid_prefix: str) -> dict:
    """{iCalUID: event} for events we previously synced under this prefix."""
    existing = {}
    page_token = None
    while True:
        resp = (
            service.events()
            .list(
                calendarId=calendar_id,
                privateExtendedProperty=f"source={SOURCE_TAG}",
                pageToken=page_token,
                maxResults=250,
                showDeleted=False,
            )
            .execute()
        )
        for ev in resp.get("items", []):
            uid = ev.get("iCalUID")
            if uid and uid.startswith(uid_prefix):
                existing[uid] = ev
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return existing


def _unchanged(existing_event: dict, body: dict) -> bool:
    return all(existing_event.get(f) == body.get(f) for f in _COMPARE_FIELDS)


def reconcile(service, calendar_id, uid_prefix, pairs, tzname, dry_run: bool) -> dict:
    """pairs: list of (uid, body|None). None body = skipped-past event that
    should still count as 'current' so it isn't deleted."""
    existing = list_existing(service, calendar_id, uid_prefix)
    current_uids = set()
    created = updated = unchanged = skipped_past = deleted = kept_past = 0

    for uid, body in pairs:
        current_uids.add(uid)
        if body is None:
            skipped_past += 1
            continue
        existing_event = existing.get(uid)
        if existing_event is None:
            if not dry_run:
                service.events().import_(calendarId=calendar_id, body=body).execute(num_retries=3)
            created += 1
        elif _unchanged(existing_event, body):
            unchanged += 1
        else:
            if not dry_run:
                service.events().import_(calendarId=calendar_id, body=body).execute(num_retries=3)
            updated += 1

    for uid, existing_event in existing.items():
        if uid not in current_uids:
            # Past events are historical - never delete them, even if their
            # plan has aged out of the download set.
            if _existing_is_past(existing_event, tzname):
                kept_past += 1
                continue
            if not dry_run:
                service.events().delete(calendarId=calendar_id, eventId=existing_event["id"]).execute(num_retries=3)
            deleted += 1

    return {
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "deleted": deleted,
        "skipped_past": skipped_past,
        "kept_past": kept_past,
        "total": len(current_uids),
    }


# ---------------------------------------------------------------------------
# Per-team sync
# ---------------------------------------------------------------------------

def _mih_intervals(service, config, events):
    """Busy intervals of existing myice events overlapping the plan window."""
    prefix = config.get("mih_uid_prefix", DEFAULT_MIH_UID_PREFIX)
    starts = [e.start_datetime() for e in events]
    ends = [e.end_datetime() for e in events]
    if not starts:
        return []
    return list_event_intervals(
        service, config["calendar_id"], prefix, min(starts), max(ends)
    )


def sync_team(service, config: dict, pdfs, dry_run: bool) -> dict:
    events: list[Event] = []
    for pdf in pdfs:
        events.extend(safe_extract(pdf, config))

    # Resolve overlaps with the authoritative myice feed.
    policy = validate_policy(config.get("mih_overlap", KEEP))
    if policy != KEEP:
        try:
            intervals = _mih_intervals(service, config, events)
            events = resolve_mih_overlap(events, intervals, policy)
        except Exception as exc:  # never abort a sync over overlap lookup
            print(f"  WARN: myice overlap check failed: {exc}")

    tzname = config.get("timezone", DEFAULT_TIMEZONE)
    uid_prefix = config.get("uid_prefix", "ehc-")
    pairs = []
    for event in events:
        # Never skip a fail-loud error marker.
        if SKIP_PAST_EVENTS and not event.is_error and _is_past(event, tzname):
            pairs.append((_uid(event, uid_prefix), None))
        else:
            pairs.append((_uid(event, uid_prefix), event_to_body(event, config, uid_prefix)))

    result = reconcile(
        service, config["calendar_id"], uid_prefix, pairs, tzname, dry_run
    )
    result["team"] = config["team"]
    result["errors"] = sum(1 for e in events if e.is_error)
    return result


def main():
    parser = argparse.ArgumentParser(description="Sync Wochenplan events to Google Calendar.")
    parser.add_argument(
        "--apply", action="store_true",
        help="actually write to the calendar (default: dry-run, writes nothing)",
    )
    args = parser.parse_args()
    dry_run = not args.apply

    pdfs = latest_local_pdfs()
    print(f"{'DRY-RUN' if dry_run else 'APPLY'}: {len(pdfs)} weeks, {len(CONFIGS)} team(s)\n")

    service = get_calendar_service()
    for config in CONFIGS:
        try:
            result = sync_team(service, config, pdfs, dry_run)
            print(json.dumps(result, ensure_ascii=False))
        except Exception as exc:
            print(json.dumps({"team": config.get("team"), "error": str(exc)}))

    if dry_run:
        print("\nDry-run only - nothing was written. Re-run with --apply to sync.")


if __name__ == "__main__":
    main()
