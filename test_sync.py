"""Unit tests for sync: UID stability, Google body construction, past-event
detection, and the create/update/delete/keep-past reconciliation."""

import unittest
from datetime import date

from extract_events import extract_events
from test_helpers import CONFIG, u14a_week39
import sync


def events_by_predicate(predicate):
    return [e for e in extract_events(u14a_week39(), CONFIG) if predicate(e)]


class UidTest(unittest.TestCase):
    def test_unique_per_event_and_stable(self):
        events = extract_events(u14a_week39(), CONFIG)
        uids = [sync._uid(e, "ehc-wp-") for e in events]
        self.assertEqual(len(uids), len(set(uids)), "UIDs must be unique")
        # Re-computing the same event yields the same UID.
        self.assertEqual(sync._uid(events[0], "ehc-wp-"), sync._uid(events[0], "ehc-wp-"))

    def test_prefix_applied(self):
        e = extract_events(u14a_week39(), CONFIG)[0]
        self.assertTrue(sync._uid(e, "ehc-wp-").startswith("ehc-wp-"))


class EventToBodyTest(unittest.TestCase):
    def test_training_body(self):
        # A regular team-row ET is myice-replaceable, so it is tentative.
        e = events_by_predicate(
            lambda e: e.type == "ET" and not e.all_day and e.myice_replaceable
        )[0]
        body = sync.event_to_body(e, CONFIG, "ehc-wp-")
        self.assertEqual(body["status"], "tentative")
        self.assertEqual(body["colorId"], "11")
        self.assertIn("dateTime", body["start"])
        self.assertEqual(body["start"]["timeZone"], "Europe/Zurich")
        self.assertIn("Quelle:", body["description"])

    def test_game_body_is_tentative_with_venue_location(self):
        e = events_by_predicate(lambda e: e.is_game)[0]
        body = sync.event_to_body(e, CONFIG, "ehc-wp-")
        self.assertEqual(body["status"], "tentative")
        self.assertEqual(body["location"], e.place)

    def test_forder_body_stays_confirmed(self):
        # Förder trainings are not on myice, so they are confirmed, not tentative.
        e = events_by_predicate(lambda e: e.type.startswith("Förder"))[0]
        self.assertFalse(e.myice_replaceable)
        self.assertEqual(sync.event_to_body(e, CONFIG, "ehc-wp-")["status"], "confirmed")

    def test_free_skate_stays_confirmed(self):
        # A named free-skate ("freies Chneblä") is EHC-only and stays confirmed.
        e = events_by_predicate(lambda e: "Chneblä" in e.type)[0]
        self.assertFalse(e.myice_replaceable)
        self.assertEqual(sync.event_to_body(e, CONFIG, "ehc-wp-")["status"], "confirmed")

    def test_all_day_body_uses_dates(self):
        e = events_by_predicate(lambda e: e.all_day)[0]
        body = sync.event_to_body(e, CONFIG, "ehc-wp-")
        self.assertIn("date", body["start"])
        self.assertIn("date", body["end"])
        # Google's all-day end is exclusive (next day).
        self.assertGreater(body["end"]["date"], body["start"]["date"])

    def test_error_event_is_red(self):
        err = extract_events(u14a_week39(), {**CONFIG, "team": "U99 Z"})[0]
        body = sync.event_to_body(err, CONFIG, "ehc-wp-")
        self.assertEqual(body["colorId"], sync.ERROR_COLOR_ID)


class PastDetectionTest(unittest.TestCase):
    def test_existing_is_past(self):
        past = {"end": {"dateTime": "2020-01-01T10:00:00"}}
        future = {"end": {"dateTime": "2099-01-01T10:00:00"}}
        self.assertTrue(sync._existing_is_past(past, "Europe/Zurich"))
        self.assertFalse(sync._existing_is_past(future, "Europe/Zurich"))

    def test_existing_is_past_all_day(self):
        self.assertTrue(sync._existing_is_past({"end": {"date": "2020-01-02"}}, "Europe/Zurich"))


class _Exec:
    def execute(self, **kwargs):
        return {}


class FakeService:
    def __init__(self, items):
        self._items = items
        self.imported = []
        self.deleted = []

    def events(self):
        return self

    def list(self, **kwargs):
        items = self._items

        class R:
            def execute(self_inner):
                return {"items": items}

        return R()

    def import_(self, calendarId, body):
        self.imported.append(body)
        return _Exec()

    def delete(self, calendarId, eventId):
        self.deleted.append(eventId)
        return _Exec()


class ReconcileTest(unittest.TestCase):
    def setUp(self):
        start = {"dateTime": "2099-01-01T09:00:00"}
        end = {"dateTime": "2099-01-01T10:00:00"}
        # Existing events already on the calendar (all under our prefix).
        self.existing_items = [
            {"iCalUID": "ehc-wp-same", "id": "s", "summary": "same",
             "status": "confirmed", "start": start, "end": end},
            {"iCalUID": "ehc-wp-diff", "id": "d", "summary": "OLD",
             "status": "confirmed", "start": start, "end": end},
            {"iCalUID": "ehc-wp-orphan-future", "id": "of", "summary": "x", "end": end},
            {"iCalUID": "ehc-wp-orphan-past", "id": "op", "summary": "x",
             "end": {"dateTime": "2020-01-01T10:00:00"}},
        ]
        self.pairs = [
            ("ehc-wp-new", {"summary": "new"}),  # created
            # identical to existing -> unchanged
            ("ehc-wp-same", {"summary": "same", "status": "confirmed", "start": start, "end": end}),
            # only the summary differs -> updated
            ("ehc-wp-diff", {"summary": "NEW", "status": "confirmed", "start": start, "end": end}),
            ("ehc-wp-pastskip", None),  # skipped_past
        ]

    def test_apply_counts_and_writes(self):
        svc = FakeService(self.existing_items)
        res = sync.reconcile(svc, "cal", "ehc-wp-", self.pairs, "Europe/Zurich", dry_run=False)
        self.assertEqual(res["created"], 1)
        self.assertEqual(res["updated"], 1)
        self.assertEqual(res["unchanged"], 1)
        self.assertEqual(res["skipped_past"], 1)
        self.assertEqual(res["deleted"], 1)  # future orphan
        self.assertEqual(res["kept_past"], 1)  # past orphan protected
        self.assertEqual(len(svc.imported), 2)  # created + updated
        self.assertEqual(svc.deleted, ["of"])  # only the future orphan

    def test_dry_run_writes_nothing(self):
        svc = FakeService(self.existing_items)
        res = sync.reconcile(svc, "cal", "ehc-wp-", self.pairs, "Europe/Zurich", dry_run=True)
        self.assertEqual(res["created"], 1)
        self.assertEqual(res["deleted"], 1)
        self.assertEqual(svc.imported, [])
        self.assertEqual(svc.deleted, [])

    def test_update_carries_existing_sequence(self):
        """events.import() rejects an update whose sequence is below the
        existing event's current sequence ('Invalid sequence value'). An update
        must therefore carry the existing event's sequence forward."""
        start = {"dateTime": "2099-01-01T09:00:00"}
        end = {"dateTime": "2099-01-01T10:00:00"}
        existing = [
            {"iCalUID": "ehc-wp-seq", "id": "sq", "summary": "OLD", "sequence": 3,
             "status": "confirmed", "start": start, "end": end},
        ]
        # Body differs (summary) -> update; it carries no sequence of its own.
        pairs = [("ehc-wp-seq", {"summary": "NEW", "status": "confirmed",
                                 "start": start, "end": end})]
        svc = FakeService(existing)
        sync.reconcile(svc, "cal", "ehc-wp-", pairs, "Europe/Zurich", dry_run=False)
        self.assertEqual(len(svc.imported), 1)
        self.assertEqual(svc.imported[0].get("sequence"), 3)

    def test_create_sets_no_sequence(self):
        """A brand-new event has no existing counterpart, so no sequence is set
        (Google assigns it)."""
        svc = FakeService([])
        sync.reconcile(svc, "cal", "ehc-wp-", [("ehc-wp-new", {"summary": "new"})],
                       "Europe/Zurich", dry_run=False)
        self.assertEqual(len(svc.imported), 1)
        self.assertNotIn("sequence", svc.imported[0])

    def test_no_churn_when_only_offset_differs(self):
        """Google returns dateTime with a UTC offset; our body emits the naive
        local time plus a timeZone. Same instant -> must be 'unchanged', not
        rewritten every run."""
        existing = [{
            "iCalUID": "ehc-wp-tz", "id": "tz", "summary": "ET", "colorId": "11",
            "status": "confirmed",
            "start": {"dateTime": "2026-09-04T06:30:00+02:00", "timeZone": "Europe/Zurich"},
            "end":   {"dateTime": "2026-09-04T07:30:00+02:00", "timeZone": "Europe/Zurich"},
        }]
        body = {"summary": "ET", "colorId": "11", "status": "confirmed",
                "start": {"dateTime": "2026-09-04T06:30:00", "timeZone": "Europe/Zurich"},
                "end":   {"dateTime": "2026-09-04T07:30:00", "timeZone": "Europe/Zurich"}}
        svc = FakeService(existing)
        res = sync.reconcile(svc, "cal", "ehc-wp-", [("ehc-wp-tz", body)],
                             "Europe/Zurich", dry_run=False)
        self.assertEqual(res["unchanged"], 1)
        self.assertEqual(res["updated"], 0)
        self.assertEqual(svc.imported, [])

    def test_real_time_change_is_still_updated(self):
        """A genuine time difference (different instant) must still update."""
        existing = [{
            "iCalUID": "ehc-wp-t", "id": "t", "summary": "ET", "status": "confirmed",
            "start": {"dateTime": "2026-09-04T06:30:00+02:00", "timeZone": "Europe/Zurich"},
            "end":   {"dateTime": "2026-09-04T07:30:00+02:00", "timeZone": "Europe/Zurich"},
        }]
        body = {"summary": "ET", "status": "confirmed",
                "start": {"dateTime": "2026-09-04T08:30:00", "timeZone": "Europe/Zurich"},
                "end":   {"dateTime": "2026-09-04T09:30:00", "timeZone": "Europe/Zurich"}}
        svc = FakeService(existing)
        res = sync.reconcile(svc, "cal", "ehc-wp-", [("ehc-wp-t", body)],
                             "Europe/Zurich", dry_run=False)
        self.assertEqual(res["updated"], 1)
        self.assertEqual(len(svc.imported), 1)


class ManualDeletionStateTest(unittest.TestCase):
    """A previously-synced event that vanished from the calendar was deleted by
    the user: tombstone it and never re-import it."""

    def setUp(self):
        # The plan still wants this event, but it is not on the calendar.
        self.body = {"summary": "ET", "start": {"dateTime": "2099-01-01T09:00:00"}}
        self.pairs = [("ehc-wp-gone", self.body)]

    def test_detects_deletion_and_does_not_recreate(self):
        svc = FakeService([])  # nothing on the calendar
        state = {"synced": {"ehc-wp-gone": {"date": "2099-01-01"}}, "tombstones": {}}
        res = sync.reconcile(svc, "cal", "ehc-wp-", self.pairs, "Europe/Zurich", False, state)
        self.assertEqual(res["created"], 0)
        self.assertEqual(res["honored_deletions"], 1)
        self.assertEqual(svc.imported, [])
        self.assertIn("ehc-wp-gone", state["tombstones"])
        self.assertNotIn("ehc-wp-gone", state["synced"])

    def test_tombstone_is_honored_on_later_runs(self):
        svc = FakeService([])
        state = {"synced": {}, "tombstones": {"ehc-wp-gone": {"date": "2099-01-01"}}}
        res = sync.reconcile(svc, "cal", "ehc-wp-", self.pairs, "Europe/Zurich", False, state)
        self.assertEqual(res["honored_deletions"], 1)
        self.assertEqual(svc.imported, [])

    def test_new_event_not_in_prior_state_is_created(self):
        svc = FakeService([])
        state = {"synced": {}, "tombstones": {}}
        res = sync.reconcile(svc, "cal", "ehc-wp-", self.pairs, "Europe/Zurich", False, state)
        self.assertEqual(res["created"], 1)
        self.assertEqual(res["honored_deletions"], 0)
        self.assertEqual(len(svc.imported), 1)
        self.assertIn("ehc-wp-gone", state["synced"])


if __name__ == "__main__":
    unittest.main()
