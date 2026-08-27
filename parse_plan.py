"""
Parses a Wochenplan PDF into a structured WeekPlan: the week's dates plus,
per team, each weekday's three sub-cells (Halle / Feld / Away), each holding
an "Art / Zeit" activity string, a "G" (Garderobe) value and a "Trsp"
(transport) value.

The grid is a real vector-lined PDF table, so pdfplumber reads it directly
(see convert_to_markdown.py for why docling was not used).
"""

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pdfplumber

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

# Column layout of the extracted table:
#   col 0 = team ("Was"), col 1 = row kind ("Wo": Halle/Feld/Away),
#   then 7 weekday blocks of 3 columns each: Art/Zeit, G, Trsp.
_COL_TEAM = 0
_COL_KIND = 1
_FIRST_DAY_COL = 2
_COLS_PER_DAY = 3

_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
# Legend lines look like "ET = Eistraining" (one per line in a merged cell).
_LEGEND_RE = re.compile(r"([A-Za-zÄÖÜ0-9. ]+?)\s*=\s*(.+)")


@dataclass
class Cell:
    art: str = ""
    g: str = ""
    trsp: str = ""


@dataclass
class DayCells:
    day_date: date | None = None
    halle: Cell = field(default_factory=Cell)
    feld: Cell = field(default_factory=Cell)
    away: Cell = field(default_factory=Cell)


@dataclass
class WeekPlan:
    source_name: str
    dates: list[date | None]
    teams: dict[str, dict[int, DayCells]]
    legend: dict[str, str]


def extract_tables(pdf_path: Path) -> list[list[list[str | None]]]:
    """Returns the raw pdfplumber cell grid for every table on every page."""
    tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.find_tables():
                tables.append(table.extract())
    return tables


def _clean(value: str | None) -> str:
    if value is None:
        return ""
    return value.replace("\n", " ").strip()


def _parse_legend(rows: list[list[str | None]]) -> dict[str, str]:
    legend: dict[str, str] = {}
    # The legend lives in the merged cells of the very first row.
    for cell in rows[0] if rows else []:
        if not cell:
            continue
        for line in str(cell).split("\n"):
            match = _LEGEND_RE.match(line.strip())
            if match:
                legend[match.group(1).strip()] = match.group(2).strip()
    return legend


def _day_cell(row: list[str | None], day: int) -> Cell:
    base = _FIRST_DAY_COL + day * _COLS_PER_DAY
    return Cell(
        art=_clean(row[base]),
        g=_clean(row[base + 1]),
        trsp=_clean(row[base + 2]),
    )


def parse_week(pdf_path: Path) -> WeekPlan:
    pdf_path = Path(pdf_path)
    tables = extract_tables(pdf_path)
    rows = tables[0] if tables else []

    legend = _parse_legend(rows)

    # Week dates come from the "Dat" row (col 1 == "Dat").
    dates: list[date | None] = [None] * len(WEEKDAYS)
    for row in rows:
        if _clean(row[_COL_KIND]) == "Dat":
            for day in range(len(WEEKDAYS)):
                match = _DATE_RE.search(_day_cell(row, day).art)
                if match:
                    d, m, y = (int(g) for g in match.groups())
                    dates[day] = date(y, m, d)
            break

    teams: dict[str, dict[int, DayCells]] = {}
    current_team: str | None = None
    for row in rows:
        kind = _clean(row[_COL_KIND])
        if kind not in ("Halle", "Feld", "Away"):
            continue

        team_label = _clean(row[_COL_TEAM])
        if team_label:
            current_team = team_label
        if current_team is None:
            continue

        day_map = teams.setdefault(current_team, {})
        for day in range(len(WEEKDAYS)):
            day_cells = day_map.setdefault(day, DayCells(day_date=dates[day]))
            cell = _day_cell(row, day)
            if kind == "Halle":
                day_cells.halle = cell
            elif kind == "Feld":
                day_cells.feld = cell
            else:
                day_cells.away = cell

    return WeekPlan(source_name=pdf_path.name, dates=dates, teams=teams, legend=legend)


if __name__ == "__main__":
    import sys

    for arg in sys.argv[1:]:
        week = parse_week(Path(arg))
        print(f"{week.source_name}: {len(week.teams)} teams, dates {week.dates}")
        print("teams:", ", ".join(week.teams))
