"""Unit tests for calendar helpers (interval listing / prefix exclusion)."""

import unittest
from datetime import datetime

from google_calendar import list_event_intervals


class FakeEvents:
    def __init__(self, items):
        self._items = items

    def list(self, **kwargs):
        items = self._items

        class R:
            def execute(self_inner):
                return {"items": items}

        return R()


class FakeService:
    def __init__(self, items):
        self._events = FakeEvents(items)

    def events(self):
        return self._events


def _ev(uid, start, end):
    return {
        "iCalUID": uid,
        "start": {"dateTime": f"2026-09-02T{start}:00"},
        "end": {"dateTime": f"2026-09-02T{end}:00"},
    }


class ListEventIntervalsTest(unittest.TestCase):
    def setUp(self):
        self.items = [
            _ev("ehc-PP818426", "16:30", "17:30"),   # myice
            _ev("ehc-wp-abc123", "16:30", "17:30"),  # our own (must be excluded)
            _ev("other@google.com", "16:30", "17:30"),  # unrelated
        ]
        self.t0 = datetime(2026, 9, 2, 0, 0)
        self.t1 = datetime(2026, 9, 3, 0, 0)

    def test_prefix_match_without_exclusion_catches_own_events(self):
        # "ehc-" alone would wrongly include our own "ehc-wp-" events.
        iv = list_event_intervals(FakeService(self.items), "cal", "ehc-", self.t0, self.t1)
        self.assertEqual(len(iv), 2)

    def test_exclude_prefix_drops_own_events(self):
        iv = list_event_intervals(
            FakeService(self.items), "cal", "ehc-", self.t0, self.t1,
            exclude_prefix="ehc-wp-",
        )
        self.assertEqual(len(iv), 1)  # only the myice ehc-PP event survives
        self.assertEqual(iv[0], (datetime(2026, 9, 2, 16, 30), datetime(2026, 9, 2, 17, 30)))


if __name__ == "__main__":
    unittest.main()
