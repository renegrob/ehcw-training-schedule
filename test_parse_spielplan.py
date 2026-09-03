"""Unit tests for parse_spielplan: column bucketing (incl. the boundary
tolerance), team splitting, game-type detection, and full-row assembly with
the round-glued-to-date quirk."""

import unittest
from datetime import date

from parse_spielplan import (
    _bucket,
    _column_starts,
    _game_type,
    _parse_row,
    _split_team,
)

# One row's worth of already-bucketed columns (the 13-column layout), as it
# comes out of _bucket. Round is glued to the date in the Spielrunde column.
HOME_ROW = [
    "9254240", "Ja", "OS", "U14-A", "U14-A | OS", "Gruppe 2", "Sat",
    "103.10.2026", "09:00", "#106189 | EHC Winterthur",
    "#106406 | HC Eisbären St. Gallen U14-A", "Eishalle Deutweg", "Winterthur ZH",
]
AWAY_ZC_ROW = [
    "9263333", "Ja", "OS", "U14-A", "U14-A | OS", "Züricup Gruppe 1", "Sun",
    "120.09.2026", "10:00", "#104212 | EHC Thalwil",
    "#106189 | EHC Winterthur", "Swiss Life Arena", "Zürich ZH",
]


def _word(text, x0):
    return {"text": text, "x0": x0, "x1": x0 + 5, "top": 100}


class SplitTeamTest(unittest.TestCase):
    def test_id_and_name(self):
        self.assertEqual(
            _split_team("#106189 | EHC Winterthur"), ("106189", "EHC Winterthur")
        )

    def test_name_with_suffix(self):
        self.assertEqual(
            _split_team("#106406 | HC Eisbären St. Gallen U14-A"),
            ("106406", "HC Eisbären St. Gallen U14-A"),
        )

    def test_no_marker_is_passthrough(self):
        self.assertEqual(_split_team("just text"), ("", "just text"))


class GameTypeTest(unittest.TestCase):
    def test_meisterschaft_default(self):
        self.assertEqual(_game_type("... OS Gruppe 2 ..."), "MS")

    def test_zuericup(self):
        self.assertEqual(_game_type("... OS Züricup Gruppe 1 ..."), "ZC")
        self.assertEqual(_game_type("... some Cup ..."), "ZC")

    def test_playoff(self):
        self.assertEqual(_game_type("... Playoff Final ..."), "PO")


class ColumnStartsTest(unittest.TestCase):
    def test_matches_labels_in_order(self):
        header = [
            _word("#", 41), _word("Spiel", 46), _word("Publiziert", 63),
            _word("Region", 92), _word("Spielklasse", 119), _word("Liga", 157),
            _word("Gruppe", 216), _word("Wochentag", 252), _word("Spielrunde", 287),
            _word("Datum/Anspielzeit", 325), _word("Heimteam", 385),
            _word("Gastteam", 509), _word("Eisbahn", 642), _word("Ort", 744),
            _word("Eisbahn", 754),
        ]
        starts = _column_starts(header)
        self.assertEqual(len(starts), 13)
        self.assertEqual(starts[0], 46)  # "Spiel", not the bare "#"
        self.assertEqual(starts[-1], 744)  # "Ort", not the trailing "Eisbahn"


class BucketTest(unittest.TestCase):
    starts = [46.0, 63.0, 92.0, 119.0, 157.0, 216.0, 252.0, 287.0, 325.0, 385.0]

    def test_word_at_exact_boundary_lands_in_its_column(self):
        # A word whose x0 equals a column start (or a hair under) must land in
        # that column, not the one to its left - the whole reason for tolerance.
        cells = _bucket([_word("#106189", 385.0)], self.starts)
        self.assertEqual(cells[9], "#106189")

    def test_word_just_left_of_start_still_snaps_right(self):
        cells = _bucket([_word("val", 384.5)], self.starts)
        self.assertEqual(cells[9], "val")

    def test_word_far_left_clamps_to_first_column(self):
        cells = _bucket([_word("id", 30.0)], self.starts)
        self.assertEqual(cells[0], "id")


class ParseRowTest(unittest.TestCase):
    def test_home_meisterschaft(self):
        g = _parse_row(HOME_ROW, "EHC Winterthur", "Spielplan U14 A.pdf")
        self.assertEqual(g.game_id, "9254240")
        self.assertEqual(g.date, date(2026, 10, 3))  # round "1" split off
        self.assertEqual(g.round, "1")
        self.assertEqual(g.time, "09:00")
        self.assertTrue(g.is_home)
        self.assertEqual(g.opponent, "HC Eisbären St. Gallen U14-A")
        self.assertEqual(g.game_type, "MS")
        self.assertEqual(g.rink, "Eishalle Deutweg")
        self.assertEqual(g.place, "Winterthur ZH")

    def test_away_zuericup_round_two_digits(self):
        row = list(AWAY_ZC_ROW)
        row[7] = "1012.12.2026"  # round "10", date 12.12.2026
        g = _parse_row(row, "EHC Winterthur", "src.pdf")
        self.assertEqual(g.round, "10")
        self.assertEqual(g.date, date(2026, 12, 12))

    def test_away_zuericup_home_away_and_opponent(self):
        g = _parse_row(AWAY_ZC_ROW, "EHC Winterthur", "src.pdf")
        self.assertFalse(g.is_home)
        self.assertEqual(g.opponent, "EHC Thalwil")
        self.assertEqual(g.game_type, "ZC")

    def test_non_data_row_is_ignored(self):
        row = ["header", "", "", "", "", "", "", "", "", "", "", "", ""]
        self.assertIsNone(_parse_row(row, "EHC Winterthur", "src.pdf"))


if __name__ == "__main__":
    unittest.main()
