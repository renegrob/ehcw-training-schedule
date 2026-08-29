"""
Manually cancelled events - the supported way to remove a plan-derived event
(e.g. a training you had to cancel) so it stays gone.

Deleting an event by hand in Google Calendar is not enough: the next `--apply`
re-imports it, because it is still in the plan. A cancellation instead tells the
sync to drop the event *before* reconciliation, so the sync deletes it if it is
still on the calendar and never re-creates it - whether or not you already
removed it by hand.

Each cancellation must scope a date, either a single `date` or an inclusive
`from`/`to` range (either bound optional, e.g. a "from" with no "to" cancels
everything from then on), and may further narrow it with an optional `time`
(matches the event's start "HH:MM") and/or `type` (the activity code, e.g.
"ET"). A whole-day / whole-range spec (no time, no type) cancels every event in
scope - handy for a week away. Error markers are never cancellable - a
fail-loud marker must always survive.

Configure them per team via a "cancellations" list in sync_configs.py, e.g.:

    "cancellations": [
        {"date": "2026-09-02"},                       # every event that day
        {"date": "2026-09-25", "time": "16:15"},      # one session
        {"date": "2026-10-01", "type": "ET"},         # all ET that day
        {"from": "2026-12-22", "to": "2026-12-28"},   # a week away
    ],
"""

from datetime import date

from extract_events import Event


def _date_in_scope(event: Event, spec: dict) -> bool:
    exact = spec.get("date")
    if exact:
        return event.day_date == date.fromisoformat(exact)
    lo, hi = spec.get("from"), spec.get("to")
    if not (lo or hi):
        return False  # a spec that names no date scope matches nothing
    if lo and event.day_date < date.fromisoformat(lo):
        return False
    if hi and event.day_date > date.fromisoformat(hi):
        return False
    return True


def _matches(event: Event, spec: dict) -> bool:
    if event.is_error:
        return False  # a fail-loud marker is never cancellable
    if not _date_in_scope(event, spec):
        return False
    want_time = spec.get("time")
    if want_time and event.time_start != want_time:
        return False
    want_type = spec.get("type")
    if want_type and event.type != want_type:
        return False
    return True


def apply_cancellations(
    events: list[Event], cancellations: list[dict]
) -> list[Event]:
    """Drop events matched by any cancellation spec. Returns the survivors."""
    if not cancellations:
        return events
    return [e for e in events if not any(_matches(e, c) for c in cancellations)]
