"""Unit tests for manual cancellations."""

import unittest
from datetime import date

from cancellations import apply_cancellations
from extract_events import Event


def make_event(day=(2026, 9, 25), start="16:15", type_="ET", is_error=False):
    return Event(
        source="Wochenplan-39.pdf/U14-A",
        day_date=date(*day),
        weekday="Freitag",
        type=type_,
        type_full="Eistraining",
        place="",
        opponent="",
        time_start=None if is_error else start,
        time_end=None if is_error else "17:15",
        garderobe="",
        transport="",
        summary="training",
        all_day=is_error,
        is_error=is_error,
    )


class ApplyCancellationsTest(unittest.TestCase):
    def test_no_specs_is_noop(self):
        events = [make_event()]
        self.assertEqual(apply_cancellations(events, []), events)

    def test_date_only_cancels_whole_day(self):
        keep = make_event(day=(2026, 9, 26))
        drop = make_event(day=(2026, 9, 25))
        out = apply_cancellations([keep, drop], [{"date": "2026-09-25"}])
        self.assertEqual(out, [keep])

    def test_date_and_time_cancels_one_session(self):
        drop = make_event(start="16:15")
        keep = make_event(start="06:30")
        out = apply_cancellations([keep, drop], [{"date": "2026-09-25", "time": "16:15"}])
        self.assertEqual(out, [keep])

    def test_date_and_type(self):
        drop = make_event(type_="ET")
        keep = make_event(type_="TT")
        out = apply_cancellations([keep, drop], [{"date": "2026-09-25", "type": "ET"}])
        self.assertEqual(out, [keep])

    def test_date_range_cancels_the_span_inclusive(self):
        before = make_event(day=(2026, 12, 21))
        first = make_event(day=(2026, 12, 22))
        last = make_event(day=(2026, 12, 28))
        after = make_event(day=(2026, 12, 29))
        out = apply_cancellations(
            [before, first, last, after], [{"from": "2026-12-22", "to": "2026-12-28"}]
        )
        self.assertEqual(out, [before, after])

    def test_open_ended_from_cancels_everything_after(self):
        keep = make_event(day=(2026, 12, 21))
        drop = make_event(day=(2026, 12, 24))
        out = apply_cancellations([keep, drop], [{"from": "2026-12-22"}])
        self.assertEqual(out, [keep])

    def test_spec_without_any_date_scope_matches_nothing(self):
        events = [make_event()]
        self.assertEqual(apply_cancellations(events, [{"time": "16:15"}]), events)

    def test_error_events_are_never_cancelled(self):
        err = make_event(is_error=True)
        # A date-only spec covering that day still must not drop the marker.
        self.assertEqual(apply_cancellations([err], [{"date": "2026-09-25"}]), [err])


if __name__ == "__main__":
    unittest.main()
