"""Shared fixtures for the tests: build synthetic WeekPlans in memory so the
extraction/sync logic can be tested without parsing a real PDF."""

from datetime import date, timedelta

from parse_plan import Cell, DayCells, WeekPlan

# Monday-based week starting 2026-09-21 (the real Wochenplan 39).
WEEK_DATES = [date(2026, 9, 21) + timedelta(days=i) for i in range(7)]

CONFIG = {
    "team": "U14 A",
    "summary_format": "🏒 EHC {type} {place} {time}",
    "game_summary_format": "❓ EHC {type} vs {opponent} {time}",
    "color_id": "11",
    "uid_prefix": "ehc-wp-",
}


def cells(day_index, halle, feld, away):
    """(art, g, trsp) triples -> a DayCells for the given weekday index."""
    return DayCells(
        day_date=WEEK_DATES[day_index],
        halle=Cell(*halle),
        feld=Cell(*feld),
        away=Cell(*away),
    )


def build_week(teams: dict, source_name="Wochenplan-39.pdf") -> WeekPlan:
    return WeekPlan(
        source_name=source_name, dates=list(WEEK_DATES), teams=teams, legend={}
    )


def u14a_week39() -> WeekPlan:
    """The real U14 A + Förder rows from Wochenplan 39."""
    empty = ("", "", "")
    u14a = {
        1: cells(1, ("ET 1715-1815", "5/6", ""), ("", "s2", ""), empty),  # Tue
        2: cells(2, empty, ("mit U12", "", ""), ("Bäretswil", "", "")),  # Wed (all-day)
        4: cells(  # Fri: ET + free-skate (time in Away)
            4, ("ET 1615-1715", "3/4", ""), ("freies Chneblä", "s1", ""),
            ("1600-1615", "", ""),
        ),
        5: cells(5, ("Bäretswil", "", ""), ("Wetzikon", "", ""), ("ZC 1430", "", "Pw")),  # Sat game
        6: cells(6, ("Dielsdorf", "", ""), ("Urdorf", "", ""), ("FS 1445", "", "Pw")),  # Sun game
    }
    forder = {
        4: cells(4, ("ET 0630-0730", "3", ""), ("Training", "s2", ""), ("für U14/U16", "", "")),
    }
    return build_week({"U14 A": u14a, "Förder- trainings": forder})
