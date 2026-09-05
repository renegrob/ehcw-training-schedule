"""Unit tests for extract_events: activity parsing, field helpers, the
training/game/second-session/Förder assembly, and fail-loud error handling."""

import unittest
from datetime import date

from extract_events import (
    _age_group,
    _combine_garderobe,
    _normalise_transport,
    _parse_activity,
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

    def test_away_game_when_code_in_away_cell(self):
        # Halle holds the venue, Away holds the game code+time -> away.
        e = self._one(date(2026, 9, 26), lambda e: e.is_game)
        self.assertFalse(e.is_home)

    def test_game_default_90_minute_duration(self):
        e = self._one(date(2026, 9, 26), lambda e: e.is_game)
        self.assertEqual((e.time_start, e.time_end), ("14:30", "16:00"))

    def test_forder_training_pulled_in_for_age_group(self):
        e = self._one(date(2026, 9, 25), lambda e: "Förder" in e.type)
        self.assertEqual((e.time_start, e.time_end), ("06:30", "07:30"))
        self.assertTrue(any("Fördertraining" in n for n in e.notes))

    def test_no_error_events_on_clean_week(self):
        self.assertFalse(any(e.is_error for e in self.events))


class HomeAwayGameTest(unittest.TestCase):
    CFG = {**CONFIG, "game_summary_format": "{home_away} {type} vs {opponent} {place}"}

    def _game(self, day_cells):
        week = build_week({"U14 A": {0: day_cells}})
        games = [e for e in extract_events(week, self.CFG) if e.is_game]
        self.assertEqual(len(games), 1)
        return games[0]

    def test_home_game_code_in_halle(self):
        # Halle = "FS 1715" (code+time), Feld = opponent, Away empty.
        e = self._game(cells(0, ("FS 1715", "", ""), ("EVDN", "", ""), ("", "", "")))
        self.assertTrue(e.is_home)
        self.assertEqual(e.place, "")  # played at home, no away venue
        self.assertEqual(e.summary, "🏠 FS vs EVDN")

    def test_away_game_private_car_icon_from_transport(self):
        # Halle = venue, Away = "ZC 1000" (code+time), trsp "Pw" -> private car.
        e = self._game(cells(0, ("SLA Zürich", "", ""), ("Thalwil", "", ""), ("ZC 1000", "", "Pw")))
        self.assertFalse(e.is_home)
        self.assertEqual(e.place, "SLA Zürich")
        self.assertEqual(e.summary, "🚗 ZC vs Thalwil SLA Zürich")

    def test_away_game_coach_icon_for_swiss_car(self):
        # "Car" is a coach in Swiss usage -> bus icon (normalised to "Bus").
        e = self._game(cells(0, ("Chur", "", ""), ("Bündner", "", ""), ("MS 1400", "", "Car")))
        self.assertEqual(e.summary, "🚌 MS vs Bündner Chur")

    def test_away_game_unknown_transport_falls_back(self):
        e = self._game(cells(0, ("Chur", "", ""), ("Bündner", "", ""), ("MS 1400", "", "")))
        self.assertEqual(e.summary, "🚗 MS vs Bündner Chur")  # away_label fallback

    def test_custom_labels_and_icons(self):
        cfg = {**self.CFG, "home_label": "H", "transport_icons": {"pw": "AUTO"}}
        week = build_week({"U14 A": {0: cells(0, ("Chur", "", ""), ("X", "", ""), ("MS 1400", "", "Pw"))}})
        e = [x for x in extract_events(week, cfg) if x.is_game][0]
        self.assertTrue(e.summary.startswith("AUTO "))


class CodeInAnyRowTest(unittest.TestCase):
    """Wochenplan-40 puts the activity code+time in whichever of the three
    Halle/Feld/Away slots the scheduler picked - often Feld, sometimes two
    coded sessions in one day. The code+time must be found in any row, and
    every timed session must yield its own event."""

    def _events(self, day_cells):
        week = build_week({"U14 A": {0: day_cells}})
        return [e for e in extract_events(week, CONFIG) if not e.is_error]

    def test_training_code_in_feld_row(self):
        # Halle empty, the only training sits in Feld (the common wp40 case).
        events = self._events(cells(0, ("", "", ""), ("ET 1730-1845", "", ""), ("", "", "")))
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual(e.type, "ET")
        self.assertEqual((e.time_start, e.time_end), ("17:30", "18:45"))
        self.assertFalse(e.all_day)
        self.assertFalse(e.is_game)

    def test_two_trainings_in_feld_and_away(self):
        # ET in Feld + TT in Away -> two separate training events, both timed.
        events = self._events(cells(0, ("", "", ""), ("ET 2030-2145", "", ""), ("TT 1930", "", "")))
        by_type = {e.type: e for e in events}
        self.assertIn("ET", by_type)
        self.assertIn("TT", by_type)
        self.assertEqual(
            (by_type["ET"].time_start, by_type["ET"].time_end), ("20:30", "21:45")
        )
        self.assertEqual(by_type["TT"].time_start, "19:30")
        self.assertFalse(any(e.is_game for e in events))

    def test_training_in_feld_plus_named_session_in_away(self):
        # ET in Feld + a written-out "Torhüter 1630-1730 Aussen" in Away.
        events = self._events(
            cells(0, ("", "", ""), ("ET 1915-2015", "", ""), ("Torhüter 1630-1730 Aussen", "", ""))
        )
        et = next(e for e in events if e.type == "ET")
        self.assertEqual((et.time_start, et.time_end), ("19:15", "20:15"))
        torhueter = next(e for e in events if "Torhüter" in e.type)
        self.assertEqual((torhueter.time_start, torhueter.time_end), ("16:30", "17:30"))

    def test_training_names_place_in_feld(self):
        # Halle carries the code+time; an unused plain Feld cell names the rink.
        events = self._events(cells(0, ("ET 1715-1815", "", ""), ("Wallrüti", "", ""), ("", "", "")))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].place, "Wallrüti")
        self.assertEqual(events[0].type, "ET")

    def test_training_and_game_same_day(self):
        # Halle ET training + Away MS game (opponent in Feld) -> both emitted.
        events = self._events(cells(0, ("ET 1000-1130", "", ""), ("Wetzikon", "", ""), ("MS 2015", "", "")))
        training = next(e for e in events if not e.is_game)
        self.assertEqual(training.type, "ET")
        self.assertEqual((training.time_start, training.time_end), ("10:00", "11:30"))
        game = next(e for e in events if e.is_game)
        self.assertEqual(game.type, "MS")
        self.assertEqual(game.time_start, "20:15")
        self.assertEqual(game.opponent, "Wetzikon")


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
