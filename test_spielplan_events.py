"""Unit tests for spielplan_events: the future-game / cancellation-marker
classification and its fail-loud handling. Drives the branches against the real
Spielplan PDF with controlled Wochenplan coverage."""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from extract_events import Event
from spielplan_events import _town, spielplan_supplement

SPIELPLAN = Path("downloads/Spielplan U14 A.pdf")
CONFIG = {
    "team": "U14 A",
    "spielplan": str(SPIELPLAN),
    "game_summary_format": "❓ {home_away} {type} vs {opponent} {time}",
}
FIRST_GAME = date(2026, 9, 20)  # earliest game in the U14 A Spielplan


def _wp_game(day: date) -> Event:
    """A minimal Wochenplan game event on a given day."""
    return Event(
        source="wp", day_date=day, weekday="", type="ZC", type_full="Züri-Cup",
        place="", opponent="X", time_start="10:00", time_end="11:30",
        garderobe="", transport="", summary="game", is_game=True,
    )


@unittest.skipUnless(SPIELPLAN.exists(), "real Spielplan PDF required")
class SupplementTest(unittest.TestCase):
    def test_all_future_when_nothing_covered(self):
        extra, stats = spielplan_supplement(
            CONFIG, [], covered=set(), today=date(2026, 1, 1)
        )
        self.assertEqual(stats["spielplan_future"], 22)
        self.assertEqual(stats["spielplan_cancelled"], 0)
        self.assertTrue(all(e.is_game for e in extra))

    def test_wochenplan_game_wins(self):
        # A Wochenplan game on the first game's day -> that game is skipped.
        extra, stats = spielplan_supplement(
            CONFIG, [_wp_game(FIRST_GAME)], covered={FIRST_GAME},
            today=date(2026, 1, 1),
        )
        self.assertEqual(stats["spielplan_covered"], 1)
        self.assertFalse(any(e.day_date == FIRST_GAME for e in extra))

    def test_missing_from_covered_week_is_marked(self):
        # Covered week, no Wochenplan game that day, still upcoming -> marker.
        extra, stats = spielplan_supplement(
            CONFIG, [], covered={FIRST_GAME}, today=date(2026, 9, 1)
        )
        self.assertEqual(stats["spielplan_cancelled"], 1)
        markers = [e for e in extra if e.type == "ABSAGE?"]
        self.assertEqual(len(markers), 1)
        m = markers[0]
        self.assertEqual(m.day_date, FIRST_GAME)
        self.assertTrue(m.all_day)
        self.assertFalse(m.myice_replaceable)
        self.assertIn("abgesagt", m.summary.lower())

    def test_past_missing_game_is_not_marked(self):
        # Same as above but the game is already in the past -> no marker.
        extra, stats = spielplan_supplement(
            CONFIG, [], covered={FIRST_GAME}, today=date(2026, 10, 1)
        )
        self.assertEqual(stats["spielplan_cancelled"], 0)
        self.assertFalse(any(e.type == "ABSAGE?" for e in extra))

    def test_missing_spielplan_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            extra, stats = spielplan_supplement(
                {"team": "No Such Team"}, [], covered=set(),
                today=date(2026, 1, 1), download_dir=Path(tmp),
            )
        self.assertEqual(extra, [])
        self.assertIsNone(stats["spielplan"])

    def test_ignore_mode_skips_supplement(self):
        cfg = {**CONFIG, "spielplan_mode": "IGNORE"}
        extra, stats = spielplan_supplement(
            cfg, [], covered=set(), today=date(2026, 1, 1)
        )
        self.assertEqual(extra, [])
        self.assertIsNone(stats["spielplan"])
        self.assertEqual(stats["spielplan_mode"], "IGNORE")

    def test_require_mode_errors_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            extra, stats = spielplan_supplement(
                {"team": "No Such Team", "spielplan_mode": "REQUIRE"}, [],
                covered=set(), today=date(2026, 1, 1), download_dir=Path(tmp),
            )
        self.assertEqual(len(extra), 1)
        self.assertTrue(extra[0].is_error)
        self.assertEqual(stats["error"], "missing")

    def test_invalid_mode_errors(self):
        extra, stats = spielplan_supplement(
            {"team": "U14 A", "spielplan_mode": "bogus"}, [], covered=set(),
            today=date(2026, 1, 1),
        )
        self.assertEqual(len(extra), 1)
        self.assertTrue(extra[0].is_error)
        self.assertIn("mode", stats["error"])

    def test_broken_spielplan_yields_error_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "Spielplan Bad.pdf"
            bad.write_text("not a pdf")
            extra, stats = spielplan_supplement(
                {"team": "Bad", "spielplan": str(bad)}, [], covered=set(),
                today=date(2026, 1, 1),
            )
        self.assertEqual(len(extra), 1)
        self.assertTrue(extra[0].is_error)
        self.assertIn("error", stats)


class TownTest(unittest.TestCase):
    def test_strips_canton(self):
        self.assertEqual(_town("Rapperswil SG"), "Rapperswil")
        self.assertEqual(_town("St. Gallen SG"), "St. Gallen")

    def test_keeps_plain_town(self):
        self.assertEqual(_town("Winterthur"), "Winterthur")


if __name__ == "__main__":
    unittest.main()
