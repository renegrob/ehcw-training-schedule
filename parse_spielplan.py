"""
Parses a season "Spielplan" PDF (one team's full-season game list) into a list
of SpielplanGame entries.

Unlike the Wochenplan, the Spielplan is not a vector-lined table - pdfplumber's
find_tables() returns nothing - but it is a fixed-column report. We recover the
columns from the header row's word x-positions and bucket every data word into
the column whose header starts at or before it. One quirk: the "Spielrunde" and
"Datum/Anspielzeit" columns touch, so the round number is glued to the date in
the extracted text (e.g. "103.10.2026" = round 1 on 03.10.2026); we split that
back apart with a regex.

Each row looks like (columns):
  Spiel | Publiziert | Region | Spielklasse | Liga | Gruppe | Wochentag |
  Spielrunde | Datum/Anspielzeit | Heimteam | Gastteam | Eisbahn | Ort Eisbahn

Teams are printed as "#106189 | EHC Winterthur". Our own side is whichever team
name contains the configured club name (default "EHC Winterthur"); the other
side is the opponent, and is_home is true when we are the Heimteam.
"""

import re
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pdfplumber

DEFAULT_CLUB_NAME = "EHC Winterthur"

# Header labels that open each logical column, in order. Their x-positions are
# read from the actual header row so small layout shifts don't break bucketing.
_COLUMN_HEADERS = [
    "Spiel", "Publiziert", "Region", "Spielklasse", "Liga", "Gruppe",
    "Wochentag", "Spielrunde", "Datum", "Heimteam", "Gastteam", "Eisbahn", "Ort",
]

_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
# Round number glued to the date, e.g. "103.10.2026" -> round "1", 03.10.2026.
_ROUND_DATE_RE = re.compile(r"\b(\d+)?(\d{2}\.\d{2}\.\d{4})\b")
_TIME_RE = re.compile(r"\b(\d{2}:\d{2})\b")
_TEAM_RE = re.compile(r"#(\d+)\s*\|\s*(.+)")


@dataclass
class SpielplanGame:
    game_id: str
    date: date
    time: str | None  # "HH:MM", or None if no anspielzeit given
    weekday: str  # raw from the plan, e.g. "Sat"
    round: str | None
    group: str  # e.g. "OS Gruppe 2", "OS Züricup Gruppe 1"
    is_home: bool
    home_team: str
    away_team: str
    opponent: str  # the non-club side
    rink: str  # Eisbahn (venue)
    place: str  # Ort (town, + canton)
    game_type: str  # activity code: "ZC" for Züri-Cup, else "MS"
    source_name: str


@dataclass
class Spielplan:
    source_name: str
    club_name: str
    games: list[SpielplanGame]


def _group_lines(words: list[dict]) -> list[list[dict]]:
    """Group extracted words into visual lines by their vertical position."""
    lines: dict[int, list[dict]] = {}
    for w in words:
        lines.setdefault(round(w["top"]), []).append(w)
    return [sorted(lines[t], key=lambda w: w["x0"]) for t in sorted(lines)]


def _column_starts(header_line: list[dict]) -> list[float]:
    """x0 of each logical column, matched from the header row by label."""
    starts: list[float] = []
    remaining = list(header_line)
    for label in _COLUMN_HEADERS:
        for i, w in enumerate(remaining):
            if w["text"].startswith(label):
                starts.append(w["x0"])
                remaining = remaining[i + 1:]
                break
    return starts


# A data word's left edge sits a hair left of its header label's left edge, so
# without slack a value whose x0 ~ the column start falls one column short.
_COL_TOLERANCE = 4.0


def _bucket(line: list[dict], starts: list[float]) -> list[str]:
    """Join each line's words into per-column text using the column x-starts.
    A word belongs to the last column whose start is <= its x0 (+ tolerance)."""
    cells = [""] * len(starts)
    for w in line:
        idx = bisect_right(starts, w["x0"] + _COL_TOLERANCE) - 1
        if idx < 0:
            idx = 0
        cells[idx] = (cells[idx] + " " + w["text"]).strip()
    return cells


def _split_team(cell: str) -> tuple[str, str]:
    """"#106189 | EHC Winterthur" -> ("106189", "EHC Winterthur")."""
    match = _TEAM_RE.search(cell)
    if match:
        return match.group(1), match.group(2).strip()
    return "", cell.strip()


def _game_type(group: str) -> str:
    low = group.lower()
    if "cup" in low or "züri" in low or "zueri" in low:
        return "ZC"
    if "playoff" in low or "play-off" in low or "final" in low:
        return "PO"
    return "MS"


def _parse_row(cells: list[str], club_name: str, source_name: str) -> SpielplanGame | None:
    text = " ".join(cells)
    # A data row starts with a numeric Spiel id; header/footer lines don't.
    id_match = re.match(r"\s*(\d{5,})\b", cells[0])
    if not id_match:
        return None

    date_match = _ROUND_DATE_RE.search(text)
    if not date_match:
        return None
    round_num = date_match.group(1)
    d, m, y = (int(x) for x in _DATE_RE.match(date_match.group(2)).groups())
    game_date = date(y, m, d)

    # Time: the first HH:MM after the date token (avoid matching inside it).
    after_date = text[date_match.end():]
    time_match = _TIME_RE.search(after_date)
    time = time_match.group(1) if time_match else None

    # Columns: [Spiel, Publiziert, Region, Spielklasse, Liga, Gruppe,
    #           Wochentag, Spielrunde, Datum, Heimteam, Gastteam, Eisbahn, Ort]
    def col(i: int) -> str:
        return cells[i] if i < len(cells) else ""

    # The Gruppe value can straddle the Liga/Gruppe column edge ("| OS" leaks
    # left), so join both and drop the leading Liga token and separator.
    group = re.sub(r"^\S+\s*\|\s*", "", f"{col(4)} {col(5)}".strip()).strip()
    weekday = col(6)
    home_id, home_team = _split_team(col(9))
    away_id, away_team = _split_team(col(10))
    rink = col(11)
    place = col(12)

    is_home = club_name.lower() in home_team.lower()
    opponent = away_team if is_home else home_team

    return SpielplanGame(
        game_id=id_match.group(1),
        date=game_date,
        time=time,
        weekday=weekday,
        round=round_num,
        group=group,
        is_home=is_home,
        home_team=home_team,
        away_team=away_team,
        opponent=opponent,
        rink=rink,
        place=place,
        game_type=_game_type(text),
        source_name=source_name,
    )


def parse_spielplan(
    pdf_path: str | Path, club_name: str = DEFAULT_CLUB_NAME
) -> Spielplan:
    pdf_path = Path(pdf_path)
    source_name = pdf_path.name

    games: list[SpielplanGame] = []
    with pdfplumber.open(pdf_path) as pdf:
        starts: list[float] | None = None
        for page in pdf.pages:
            lines = _group_lines(page.extract_words())
            for line in lines:
                joined = " ".join(w["text"] for w in line)
                if starts is None and "Heimteam" in joined and "Gastteam" in joined:
                    starts = _column_starts(line)
                    continue
                if starts is None:
                    continue
                game = _parse_row(_bucket(line, starts), club_name, source_name)
                if game:
                    games.append(game)

    games.sort(key=lambda g: (g.date, g.time or ""))
    return Spielplan(source_name=source_name, club_name=club_name, games=games)


if __name__ == "__main__":
    import sys

    for arg in sys.argv[1:]:
        plan = parse_spielplan(arg)
        print(f"{plan.source_name}: {len(plan.games)} games")
        for g in plan.games:
            side = "H" if g.is_home else "A"
            print(
                f"  {g.date} {g.time or '  -  '} [{g.game_type} {side}] "
                f"vs {g.opponent}  @ {g.rink}, {g.place}"
            )
