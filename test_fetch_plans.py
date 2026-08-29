"""Unit tests for fetch_plans: week-number parsing, current/future filtering
(incl. new-year wraparound), and latest-revision-per-week local selection."""

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from fetch_plans import (
    _week_is_current_or_future,
    latest_local_pdfs,
    week_key_from_name,
)


class WeekKeyTest(unittest.TestCase):
    def test_extracts_week_number(self):
        self.assertEqual(week_key_from_name("Wochenplan-34.pdf"), "34")
        self.assertEqual(week_key_from_name("Wochenplan-34_NEU.pdf"), "34")
        self.assertEqual(week_key_from_name("Wochenplan-34_Neu_1.pdf"), "34")
        self.assertEqual(week_key_from_name("Wochenplan-01.pdf"), "01")

    def test_unparseable_falls_back_to_name(self):
        self.assertEqual(week_key_from_name("Sommerplan.pdf"), "Sommerplan.pdf")


class CurrentOrFutureWeekTest(unittest.TestCase):
    def test_midyear_drops_past_keeps_future(self):
        today = date(2026, 8, 29)  # ISO week 35
        self.assertFalse(_week_is_current_or_future(32, today))
        self.assertFalse(_week_is_current_or_future(34, today))
        self.assertTrue(_week_is_current_or_future(35, today))  # current week
        self.assertTrue(_week_is_current_or_future(39, today))

    def test_year_end_keeps_january_weeks(self):
        today = date(2026, 12, 30)  # ISO week 53
        self.assertFalse(_week_is_current_or_future(52, today))
        self.assertTrue(_week_is_current_or_future(53, today))
        # Weeks 1-3 are next January -> future, despite the smaller number.
        self.assertTrue(_week_is_current_or_future(1, today))
        self.assertTrue(_week_is_current_or_future(3, today))

    def test_early_january_drops_previous_year_weeks(self):
        today = date(2027, 1, 5)  # ISO week 1
        self.assertFalse(_week_is_current_or_future(51, today))
        self.assertFalse(_week_is_current_or_future(52, today))
        self.assertTrue(_week_is_current_or_future(1, today))
        self.assertTrue(_week_is_current_or_future(2, today))


class LatestLocalPdfsTest(unittest.TestCase):
    def test_keeps_newest_revision_per_week(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            old = d / "Wochenplan-34.pdf"
            new = d / "Wochenplan-34_Neu_1.pdf"
            other = d / "Wochenplan-35.pdf"
            for p in (old, new, other):
                p.write_bytes(b"%PDF-1.4")
            # Make the revised file the most recently modified for week 34.
            os.utime(old, (1000, 1000))
            os.utime(new, (2000, 2000))
            os.utime(other, (1500, 1500))

            result = latest_local_pdfs(d)
            names = {p.name for p in result}
            self.assertEqual(names, {"Wochenplan-34_Neu_1.pdf", "Wochenplan-35.pdf"})


if __name__ == "__main__":
    unittest.main()
