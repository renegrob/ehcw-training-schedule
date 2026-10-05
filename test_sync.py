"""Unit tests for sync: UID stability, Google body construction, past-event
detection, and the create/update/delete/keep-past reconciliation."""

import unittest
from dataclasses import replace
from unittest import mock
from datetime import date, datetime

from extract_events import Event, extract_events
from overlap import REMOVE, resolve_mih_overlap
from test_helpers import CONFIG, build_week, u14a_week39
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

    def test_stable_across_a_reissued_plan(self):
        # The club republishes a corrected week under a new filename rather
        # than overwriting the old one (Wochenplan-39.pdf -> Wochenplan-39_Neu.pdf).
        # An unchanged event's UID must survive that rename, or a tombstoned
        # (hand-deleted) event reappears and every event in the week churns as
        # a spurious delete+create.
        original = extract_events(u14a_week39(), CONFIG)[0]
        reissued = extract_events(
            build_week(u14a_week39().teams, source_name="Wochenplan-39_Neu.pdf"),
            CONFIG,
        )[0]
        self.assertEqual(
            sync._uid(original, "ehc-wp-"), sync._uid(reissued, "ehc-wp-")
        )

    def test_spielplan_source_unaffected_by_week_normalisation(self):
        # Spielplan filenames ("Spielplan U14 A.pdf") don't match the
        # Wochenplan week-number pattern, so week_key_from_name() falls back
        # to returning them unchanged - the UID must still be stable and,
        # unlike Wochenplan sources, unaffected by this normalisation step.
        e = replace(
            extract_events(u14a_week39(), CONFIG)[0],
            source="Spielplan U14 A.pdf/U14-A",
        )
        self.assertEqual(sync._uid(e, "ehc-wp-"), sync._uid(e, "ehc-wp-"))
        renamed = replace(e, source="Spielplan U14 A_v2.pdf/U14-A")
        self.assertNotEqual(
            sync._uid(e, "ehc-wp-"), sync._uid(renamed, "ehc-wp-"),
            "a non-Wochenplan filename change must still change the UID",
        )


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


class SupersededByMyiceTest(unittest.TestCase):
    """An event the myice feed took over (mih_overlap=REMOVE) must stay gone
    when the myice entry itself later disappears - that happens when the player
    is reported absent, so re-creating the plan event would be wrong."""

    def setUp(self):
        self.event = Event(
            source="Wochenplan-39.pdf/U14-A",
            day_date=date(2099, 1, 1),
            weekday="Freitag",
            type="ET",
            type_full="Eistraining",
            place="Wallrüti",
            opponent="",
            time_start="09:00",
            time_end="10:00",
            garderobe="",
            transport="",
            summary="🏒 EHC ET",
            all_day=False,
            is_error=False,
            myice_replaceable=True,
        )
        self.uid = sync._uid(self.event, "ehc-wp-")
        self.body = sync.event_to_body(self.event, CONFIG, "ehc-wp-")
        # A myice booking covering exactly the training slot.
        self.mih = [(datetime(2099, 1, 1, 9, 0), datetime(2099, 1, 1, 10, 0))]
        self.state = {"synced": {}, "tombstones": {}, "superseded": {}}
        self.team_config = {**CONFIG, "calendar_id": "cal", "mih_overlap": "REMOVE"}

    def test_drop_is_recorded_with_date_and_summary(self):
        sync._record_superseded(self.state, [self.event], "ehc-wp-")
        self.assertEqual(
            self.state["superseded"][self.uid],
            {"date": "2099-01-01", "summary": self.event.summary},
        )

    def test_recorded_event_is_dropped_from_later_runs(self):
        self.state["superseded"][self.uid] = {"date": "2099-01-01"}
        kept, dropped = sync._drop_superseded([self.event], self.state, "ehc-wp-")
        self.assertEqual(kept, [])
        self.assertEqual(dropped, 1)

    def test_unrecorded_events_pass_through(self):
        other = replace(self.event, time_start="11:00", time_end="12:00")
        self.state["superseded"][self.uid] = {"date": "2099-01-01"}
        kept, dropped = sync._drop_superseded([self.event, other], self.state, "ehc-wp-")
        self.assertEqual(kept, [other])
        self.assertEqual(dropped, 1)

    def _sync_team(self, mih_intervals, on_calendar, config=None):
        """One sync_team run with a stubbed plan and myice feed."""
        svc = FakeService(list(on_calendar))
        with mock.patch.object(sync, "safe_extract", lambda pdf, cfg: [self.event]), \
             mock.patch.object(sync, "spielplan_supplement",
                               lambda cfg, events, covered, today: ([], {})), \
             mock.patch.object(sync, "covered_dates", lambda pdfs: set()), \
             mock.patch.object(sync, "_mih_intervals",
                               lambda service, cfg, events: mih_intervals):
            res = sync.sync_team(
                svc, config or self.team_config, ["Wochenplan-39.pdf"],
                dry_run=False, state=self.state,
            )
        return res, svc

    def test_sync_team_does_not_resurrect_it_when_myice_entry_disappears(self):
        """The regression, through sync_team: only the myice feed changes."""
        # Run 1: no myice booking yet -> we create the plan event.
        res, svc = self._sync_team([], [])
        self.assertEqual(res["created"], 1)
        self.assertIn(self.uid, self.state["synced"])

        # Run 2: the myice booking appears -> it supersedes our copy.
        res, svc = self._sync_team(self.mih, [{**self.body, "id": "x"}])
        self.assertEqual(res["deleted"], 1, "our copy must come off the calendar")
        self.assertEqual(svc.deleted, ["x"])
        self.assertIn(self.uid, self.state["superseded"])

        # Run 3: the player is reported absent, so the myice booking is gone.
        # The plan still lists the training - it must not come back.
        res, svc = self._sync_team([], [])
        self.assertEqual(res["created"], 0)
        self.assertEqual(res["superseded"], 1)
        self.assertEqual(svc.imported, [])

        # Run 4: and it stays away.
        res, svc = self._sync_team([], [])
        self.assertEqual(res["created"], 0)
        self.assertEqual(svc.imported, [])

    def test_shadow_team_ignores_the_superseded_bucket(self):
        """The bucket is REMOVE's bookkeeping. Under SHADOW the event lives on
        the calendar anyway, so a stale entry must not suppress it."""
        self.state["superseded"][self.uid] = {"date": "2099-01-01"}
        res, svc = self._sync_team(
            [], [], config={**self.team_config, "mih_overlap": "SHADOW"}
        )
        self.assertEqual(res["created"], 1)
        self.assertEqual(len(svc.imported), 1)

    def test_myice_entry_disappearing_does_not_resurrect_the_event(self):
        tz = "Europe/Zurich"
        # Run 1: no myice booking yet - we create the plan event.
        svc = FakeService([])
        sync.reconcile(svc, "cal", "ehc-wp-", [(self.uid, dict(self.body))],
                       tz, False, self.state)
        self.assertEqual(len(svc.imported), 1)
        self.assertIn(self.uid, self.state["synced"])

        # Run 2: the myice booking appears and supersedes it.
        removed = []
        kept = resolve_mih_overlap([self.event], self.mih, REMOVE, removed=removed)
        sync._record_superseded(self.state, removed, "ehc-wp-")
        svc = FakeService([{**self.body, "id": "x"}])
        res = sync.reconcile(svc, "cal", "ehc-wp-", [], tz, False, self.state)
        self.assertEqual(kept, [])
        self.assertEqual(res["deleted"], 1, "our copy must come off the calendar")
        self.assertIn(self.uid, self.state["superseded"])

        # Run 3: the player is reported absent, so the myice booking is gone.
        # The plan still lists the training, but it must not come back.
        kept = resolve_mih_overlap([self.event], [], REMOVE, removed=[])
        kept, dropped = sync._drop_superseded(kept, self.state, "ehc-wp-")
        pairs = [(sync._uid(e, "ehc-wp-"), sync.event_to_body(e, CONFIG, "ehc-wp-"))
                 for e in kept]
        svc = FakeService([])
        res = sync.reconcile(svc, "cal", "ehc-wp-", pairs, tz, False, self.state)
        self.assertEqual(dropped, 1)
        self.assertEqual(res["created"], 0)
        self.assertEqual(svc.imported, [])


if __name__ == "__main__":
    unittest.main()
