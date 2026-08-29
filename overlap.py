"""
Reconcile PDF-derived events against events already on the calendar from the
myice.hockey feed (aws-ical-sync, uid_prefix "mih-ehc-").

When a PDF event overlaps a myice event in time, the myice one is the
authoritative entry, so the PDF one is redundant. What to do about the PDF
event is configurable per team via the "mih_overlap" config key:

  REMOVE  drop the PDF event (myice covers it)
  KEEP    keep both (no change)
  SHADOW  keep the PDF event but recolour it (Graphite, colorId 8) so it reads
          as a secondary/shadow copy

Error events are never touched - a fail-loud marker must always survive. Nor
are events myice never carries (Förder trainings, free-skates): those have
Event.myice_replaceable=False and pass through regardless of the policy.
"""

from datetime import datetime

from extract_events import Event

REMOVE = "REMOVE"
KEEP = "KEEP"
SHADOW = "SHADOW"
VALID_POLICIES = (REMOVE, KEEP, SHADOW)

# SHADOW recolours the kept PDF event to Graphite.
SHADOW_COLOR_ID = "8"

# Default myice uid prefix (matches aws-ical-sync's EHC feeds).
DEFAULT_MIH_UID_PREFIX = "mih-ehc-"


def validate_policy(policy: str) -> str:
    if policy not in VALID_POLICIES:
        raise ValueError(
            f"mih_overlap must be one of {VALID_POLICIES}, got {policy!r}"
        )
    return policy


def _overlaps(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> bool:
    return a_start < b_end and b_start < a_end


def resolve_mih_overlap(
    events: list[Event],
    mih_intervals: list[tuple[datetime, datetime]],
    policy: str,
    shadow_color_id: str = SHADOW_COLOR_ID,
) -> list[Event]:
    """Apply the overlap policy to `events` given the busy `mih_intervals`
    (start, end) of existing myice events on the same calendar."""
    validate_policy(policy)
    if policy == KEEP or not mih_intervals:
        return events

    resolved: list[Event] = []
    for event in events:
        # Error markers must always survive, and Förder trainings / free-skates
        # (myice_replaceable=False) are never on the myice feed, so a time
        # collision there is a coincidence, not a duplicate - leave them be.
        if event.is_error or not event.myice_replaceable:
            resolved.append(event)
            continue

        start, end = event.start_datetime(), event.end_datetime()
        overlaps = any(_overlaps(start, end, m0, m1) for m0, m1 in mih_intervals)
        if not overlaps:
            resolved.append(event)
            continue

        if policy == REMOVE:
            continue  # drop - myice already has it
        # SHADOW: keep but recolour and annotate.
        event.color_id = shadow_color_id
        event.notes.append("Überschneidung mit myice-Eintrag (Shadow)")
        resolved.append(event)

    return resolved
