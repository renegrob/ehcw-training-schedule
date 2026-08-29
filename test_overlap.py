"""Unit tests for the myice-overlap resolution policy."""

import unittest
from datetime import date, datetime

from extract_events import Event
from overlap import KEEP, REMOVE, SHADOW, resolve_mih_overlap, validate_policy


def make_event(start="14:30", end="16:00", is_error=False, all_day=False):
    return Event(
        source="Wochenplan-39.pdf/U14-A",
        day_date=date(2026, 9, 26),
        weekday="Samstag",
        type="ZC",
        type_full="Züri-Cup",
        place="Bäretswil",
        opponent="Wetzikon",
        time_start=None if all_day else start,
        time_end=None if all_day else end,
        garderobe="",
        transport="",
        summary="game",
        all_day=all_day,
        is_error=is_error,
    )


# A myice event that overlaps the 14:30-16:00 game.
OVERLAP = [(datetime(2026, 9, 26, 14, 30), datetime(2026, 9, 26, 16, 0))]
# A myice event on the same day but at a different time (no overlap).
NO_OVERLAP = [(datetime(2026, 9, 26, 9, 0), datetime(2026, 9, 26, 10, 0))]


class ValidatePolicyTest(unittest.TestCase):
    def test_valid(self):
        for p in (REMOVE, KEEP, SHADOW):
            self.assertEqual(validate_policy(p), p)

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            validate_policy("MAYBE")


class ResolveOverlapTest(unittest.TestCase):
    def test_keep_leaves_everything(self):
        events = [make_event()]
        out = resolve_mih_overlap(events, OVERLAP, KEEP)
        self.assertEqual(len(out), 1)
        self.assertIsNone(out[0].color_id)

    def test_remove_drops_overlapping(self):
        out = resolve_mih_overlap([make_event()], OVERLAP, REMOVE)
        self.assertEqual(out, [])

    def test_remove_keeps_non_overlapping(self):
        out = resolve_mih_overlap([make_event()], NO_OVERLAP, REMOVE)
        self.assertEqual(len(out), 1)

    def test_shadow_recolours_and_notes(self):
        out = resolve_mih_overlap([make_event()], OVERLAP, SHADOW)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].color_id, "8")
        self.assertTrue(any("myice" in n.lower() for n in out[0].notes))

    def test_error_events_never_touched(self):
        err = make_event(is_error=True)
        out = resolve_mih_overlap([err], OVERLAP, REMOVE)
        self.assertEqual(out, [err])

    def test_no_intervals_is_noop(self):
        events = [make_event()]
        self.assertEqual(resolve_mih_overlap(events, [], REMOVE), events)


if __name__ == "__main__":
    unittest.main()
