"""Unit tests for extract_events: activity parsing, field helpers, the
training/game/second-session/Förder assembly, and fail-loud error handling."""

import unittest
from datetime import date

from parse_plan import Cell
from extract_events import (
    _age_group,
    _combine_garderobe,
    _normalise_transport,
    _parse_activity,
    _place_from_feld,
    extract_events,
    safe_extract,
)
from test_helpers import CONFIG, u14a_week39, build_week, cells


class ParseActivityTest(unittest.TestCase):
    def test_type_and_time_range(self):
        a = _parse_activity("ET 1715-1815")
        self.assertEqual((a.type_code, a.start, a.end, a.leftover), ("ET", "1715", "1815", ""))

    def test_type_and_single_time(self):
        a = _parse_activity("MS 1900")
        self.assertEqual((a.type_code, a.start, a.end), ("MS", "1900", None))

    def test_name_only(self):
        a = _parse_activity("Küssnacht")
        self.assertEqual((a.type_code, a.start, a.leftover), (None, None, "Küssnacht"))

    def test_bare_time_range(self):
        a = _parse_activity("1600-1615")
        self.assertEqual((a.type_code, a.start, a.end), (None, "1600", "1615"))


class HelperTest(unittest.TestCase):
    def test_car_becomes_bus(self):
        self.assertEqual(_normalise_transport("Car"), "Bus")
        self.assertEqual(_normalise_transport("Car", "Pw"), "Bus, Pw")
        self.assertEqual(_normalise_transport("Bus 1", "Car"), "Bus 1, Bus")

    def test_combine_garderobe_dedups(self):
        self.assertEqual(_combine_garderobe("5/6", "s2"), "5/6, s2")
        self.assertEqual(_combine_garderobe("3", "3", ""), "3")

    def test_place_vs_note(self):
        self.assertEqual(_place_from_feld(Cell("Wetzikon")), ("Wetzikon", ""))
        self.assertEqual(_place_from_feld(Cell("freies Chneblä")), ("", "freies Chneblä"))
        self.assertEqual(_place_from_feld(Cell("")), ("", ""))

    def test_age_group(self):
        self.assertEqual(_age_group("U14 A"), "U14")
        self.assertEqual(_age_group("U16 Elit"), "U16")
        self.assertIsNone(_age_group("MHL"))


class ExtractEventsTest(unittest.TestCase):
    def setUp(self):
        self.events = extract_events(u14a_week39(), CONFIG)
        self.by_day = {}
        for e in self.events:
            self.by_day.setdefault(e.day_date, []).append(e)

    def _one(self, day, predicate):
        matches = [e for e in self.by_day.get(day, []) if predicate(e)]
        self.assertEqual(len(matches), 1, f"expected exactly one match on {day}")
        return matches[0]

    def test_training_summary_and_times(self):
        e = self._one(date(2026, 9, 22), lambda e: e.type == "ET")
        self.assertEqual(e.summary, "🏒 EHC ET 17:15-18:15")
        self.assertEqual((e.time_start, e.time_end), ("17:15", "18:15"))
        self.assertFalse(e.is_game)

    def test_all_day_when_no_time(self):
        e = self._one(date(2026, 9, 23), lambda e: True)
        self.assertTrue(e.all_day)
        self.assertEqual(e.summary, "🏒 EHC Bäretswil")

    def test_second_session_from_away_time(self):
        e = self._one(date(2026, 9, 25), lambda e: e.type == "freies Chneblä")
        self.assertEqual((e.time_start, e.time_end), ("16:00", "16:15"))
        self.assertEqual(e.garderobe, "s1")

    def test_game_place_is_venue_opponent_is_feld(self):
        e = self._one(date(2026, 9, 26), lambda e: e.is_game)
        self.assertEqual(e.place, "Bäretswil")  # Halle = venue
        self.assertEqual(e.opponent, "Wetzikon")  # Feld = opponent
        self.assertEqual(e.summary, "❓ EHC ZC vs Wetzikon 14:30-16:00")

    def test_game_default_90_minute_duration(self):
        e = self._one(date(2026, 9, 26), lambda e: e.is_game)
        self.assertEqual((e.time_start, e.time_end), ("14:30", "16:00"))

    def test_forder_training_pulled_in_for_age_group(self):
        e = self._one(date(2026, 9, 25), lambda e: "Förder" in e.type)
        self.assertEqual((e.time_start, e.time_end), ("06:30", "07:30"))
        self.assertTrue(any("Fördertraining" in n for n in e.notes))

    def test_no_error_events_on_clean_week(self):
        self.assertFalse(any(e.is_error for e in self.events))


class ErrorHandlingTest(unittest.TestCase):
    def test_team_not_found_yields_error_event(self):
        week = u14a_week39()
        events = extract_events(week, {**CONFIG, "team": "U99 Z"})
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].is_error)

    def test_day_with_content_but_no_time_is_all_day_not_dropped(self):
        week = build_week({"U14 A": {0: cells(0, ("", "", ""), ("Info", "", ""), ("", "", ""))}})
        events = extract_events(week, CONFIG)
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].all_day)

    def test_safe_extract_on_corrupt_pdf(self):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"not a real pdf")
            path = f.name
        events = safe_extract(path, CONFIG)
        self.assertTrue(events and all(e.is_error for e in events))


if __name__ == "__main__":
    unittest.main()
