"""
Turns a parsed WeekPlan into calendar-ready events for one configured team.

Per team and weekday there are three sub-cells - Halle, Feld, Away - whose
roles differ between trainings and games:

  Training (activity code ET/TT/TH/TRL, normally in the Halle cell):
    * Halle = activity code + time (e.g. "ET 1715-1815")
    * Feld  = the place/rink (e.g. "Wallrüti"), OR a *second* session that
      day (e.g. Halle "ET 0900-1030" + Feld "ET 1300-1430"), OR a named
      extra like "freies Chneblä" whose time then sits in the Away cell.

  Game (activity code MS/FS/ZC/TU/PO, normally in the Away cell):
    * Halle = the venue/town where it is played (e.g. "Küssnacht")
    * Feld  = the opponent (e.g. "Innerschwyz")
    * Away  = activity code + time (e.g. "FS 1030")

Games list only a start time, so a default duration is assumed. Days with
content but no parseable time become all-day events (the real time lives in
another team's row, e.g. a joint U12 game). "Car" is Swiss-German for a
coach/bus and is normalised to "Bus".
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from parse_plan import WEEKDAYS, Cell, DayCells, WeekPlan

# Games list only a start time; assume this duration for their end time.
DEFAULT_GAME_MINUTES = 90

GAME_CODES = {"MS", "FS", "ZC", "TU", "PO"}

# Activity-code -> full word. Seeded from the legend printed on each plan, but
# kept here as the source of truth (the in-PDF legend text is occasionally
# mangled by the layout, e.g. "TU = Turnier ZC").
TYPE_MAP = {
    "ET": "Eistraining",
    "TT": "Trockentraining",
    "TH": "Torhütertraining",
    "FS": "Freundschaft",
    "MS": "Meisterschaft",
    "PO": "Play-Off",
    "TU": "Turnier",
    "ZC": "Züri-Cup",
    "TRL": "Trainingslager",
}

_TYPE_RE = re.compile(r"\b(ET|TT|TH|FS|MS|PO|TU|ZC|TRL)\b")
_TIME_RANGE_RE = re.compile(r"(\d{3,4})\s*-\s*(\d{3,4})")
_TIME_SINGLE_RE = re.compile(r"\b(\d{3,4})\b")

# Feld text that is a note/activity, not a place/opponent name.
_NON_PLACE_RE = re.compile(
    r"frei|freiwillig|chnebl|^mit\b|gem\.|aufgebot|training", re.IGNORECASE
)


@dataclass
class ParsedActivity:
    type_code: str | None
    start: str | None  # "HHMM"
    end: str | None  # "HHMM"
    leftover: str  # text with the type/time removed (opponent, place, ...)


@dataclass
class Event:
    source: str  # e.g. "Wochenplan-39.pdf/U14-A"
    day_date: date
    weekday: str
    type: str  # abbreviation or descriptive text (e.g. "ET", "freies Chneblä")
    type_full: str  # expanded name (e.g. "Eistraining")
    place: str  # venue/rink (e.g. "Küssnacht", "Wallrüti")
    opponent: str  # only for games (e.g. "Innerschwyz")
    time_start: str | None  # "HH:MM" (None for all-day)
    time_end: str | None  # "HH:MM" (None for all-day)
    garderobe: str
    transport: str
    summary: str
    all_day: bool = False
    notes: list[str] = field(default_factory=list)


def _fmt_time(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.zfill(4)
    return f"{raw[:2]}:{raw[2:]}"


def _plus_minutes(hhmm: str, minutes: int) -> str:
    start = datetime.strptime(hhmm, "%H:%M")
    return (start + timedelta(minutes=minutes)).strftime("%H:%M")


def _parse_activity(text: str) -> ParsedActivity:
    type_code = None
    type_match = _TYPE_RE.search(text)
    if type_match:
        type_code = type_match.group(1)

    start = end = None
    leftover = text
    range_match = _TIME_RANGE_RE.search(text)
    if range_match:
        start, end = range_match.groups()
        leftover = leftover.replace(range_match.group(0), " ")
    else:
        single_match = _TIME_SINGLE_RE.search(text)
        if single_match:
            start = single_match.group(1)
            leftover = leftover.replace(single_match.group(0), " ")

    if type_match:
        leftover = leftover.replace(type_match.group(0), " ")
    leftover = re.sub(r"\s+", " ", leftover).strip()
    return ParsedActivity(type_code, start, end, leftover)


def _normalise_transport(*values: str) -> str:
    parts = []
    for value in values:
        value = value.strip()
        if not value:
            continue
        # "Car" is a coach/bus in Swiss usage.
        value = re.sub(r"\bCar\b", "Bus", value)
        parts.append(value)
    return ", ".join(dict.fromkeys(parts))


def _combine_garderobe(*values: str) -> str:
    parts = [v.strip() for v in values if v.strip()]
    return ", ".join(dict.fromkeys(parts))


def _place_from_feld(feld: Cell) -> tuple[str, str]:
    """Returns (place, note). A Feld cell that is really an activity note
    (e.g. "freies Chneblä", "mit U12") yields an empty place and a note."""
    text = feld.art.strip()
    if not text:
        return "", ""
    if _NON_PLACE_RE.search(text) or _TIME_RANGE_RE.search(text) or _TYPE_RE.search(text):
        return "", text
    return text, ""


def _make_event(
    source: str,
    weekday: str,
    day_date: date,
    type_label: str,
    type_full: str,
    place: str,
    opponent: str,
    start: str | None,
    end: str | None,
    garderobe: str,
    transport: str,
    summary_format: str,
    team: str,
    notes: list[str],
) -> Event:
    all_day = start is None
    if start and not end:
        # Games list only a start time - assume a default duration.
        end = _plus_minutes(start, DEFAULT_GAME_MINUTES)
    time = f"{start}-{end}" if start else ""
    summary = re.sub(
        r"\s+",
        " ",
        summary_format.format(
            type=type_label, type_full=type_full, place=place,
            opponent=opponent, time=time, start=start or "", end=end or "",
            team=team,
        ),
    ).strip()
    return Event(
        source=source,
        day_date=day_date,
        weekday=weekday,
        type=type_label,
        type_full=type_full,
        place=place,
        opponent=opponent,
        time_start=start,
        time_end=end,
        garderobe=garderobe,
        transport=transport,
        summary=summary,
        all_day=all_day,
        notes=notes,
    )


def _second_session(
    source: str, weekday: str, cells: DayCells, feld: "ParsedActivity",
    away: "ParsedActivity", primary_from_halle: bool, summary_format: str, team: str,
) -> Event | None:
    """A named extra session in the Feld cell - e.g. an afternoon "ET 1300-1430"
    or a "freies Chneblä" whose time sits in the Away cell."""
    name = feld.leftover
    if not name:
        return None

    if feld.start:  # Feld carries its own time (e.g. "ET 1300-1430")
        start, end = feld.start, feld.end
    elif away.start and primary_from_halle:  # time is in the Away cell
        start, end = away.start, away.end
    else:
        return None  # no time for it -> handled as a note on the primary

    type_full = TYPE_MAP.get(feld.type_code, name) if feld.type_code else name
    type_label = feld.type_code or name
    return _make_event(
        source, weekday, cells.day_date, type_label, type_full, "", "",
        _fmt_time(start), _fmt_time(end),
        _combine_garderobe(cells.feld.g), _normalise_transport(cells.feld.trsp),
        summary_format, team, [],
    )


def _build_day_events(
    source: str, weekday: str, cells: DayCells, summary_format: str, team: str
) -> list[Event]:
    if not (cells.halle.art or cells.feld.art or cells.away.art):
        return []  # completely empty day

    halle = _parse_activity(cells.halle.art)
    feld = _parse_activity(cells.feld.art)
    away = _parse_activity(cells.away.art)

    type_code = halle.type_code or away.type_code
    is_game = type_code in GAME_CODES
    primary_from_halle = halle.start is not None

    # Primary time: Halle first, then Away (games put it in Away).
    timed = next((a for a in (halle, away) if a.start), None)

    # A Feld cell can be: the place, a second session, or just a note.
    feld_place, feld_note = _place_from_feld(cells.feld)
    second = _second_session(
        source, weekday, cells, feld, away, primary_from_halle, summary_format, team
    )

    # --- place / opponent ---
    place = ""
    opponent = ""
    notes: list[str] = []
    if is_game:
        # Game: Halle = venue, Feld = opponent.
        place = halle.leftover
        opponent = feld.leftover
        if opponent:
            notes.append(f"Gegner: {opponent}")
    else:
        # Training: Feld is the place (unless it's a second session / note).
        if second is None:
            place = feld_place
            if feld_note:
                notes.append(f"Feld: {feld_note}")
        # A no-code training whose time came from Away may name a venue-type
        # in Halle (e.g. "Turnhalle") - keep it as a note.
        if not halle.type_code and halle.leftover and halle.leftover != place:
            notes.append(f"Halle: {halle.leftover}")

    # --- type ---
    if type_code:
        type_label = type_code
        type_full = TYPE_MAP.get(type_code, type_code)
    else:
        # No code: fall back to descriptive text (venue/opponent for a
        # timeless game row, or the Halle venue-type).
        fallback = halle.leftover or away.leftover or feld.leftover
        type_label = type_full = fallback

    # --- garderobe / transport (Feld's belong to the second session) ---
    feld_g = "" if second is not None else cells.feld.g
    feld_trsp = "" if second is not None else cells.feld.trsp
    garderobe = _combine_garderobe(cells.halle.g, feld_g, cells.away.g)
    transport = _normalise_transport(cells.halle.trsp, feld_trsp, cells.away.trsp)

    events = [
        _make_event(
            source, weekday, cells.day_date, type_label, type_full, place, opponent,
            _fmt_time(timed.start) if timed else None,
            _fmt_time(timed.end) if timed else None,
            garderobe, transport, summary_format, team, notes,
        )
    ]
    if second is not None:
        events.append(second)
    return events


def _age_group(team_label: str) -> str | None:
    """"U14 A" -> "U14". Returns None for non-age-group teams (MHL, Senioren...)."""
    match = re.match(r"(U\d+)", team_label)
    return match.group(1) if match else None


def _forder_events(
    week: WeekPlan, source: str, summary_format: str, team: str, age_group: str
) -> list[Event]:
    """Fördertrainings live in their own "Förder- trainings" row and are aimed
    at a whole age group (e.g. "Training für U14/U16"), so they apply to every
    U14 team, not just the one whose row they'd otherwise sit in. Pull in the
    days that mention this team's age group."""
    group_re = re.compile(rf"\b{re.escape(age_group)}\b")
    events: list[Event] = []

    for team_label, day_map in week.teams.items():
        if "förder" not in team_label.lower():
            continue
        for day, cells in sorted(day_map.items()):
            if cells.day_date is None:
                continue
            audience = " ".join(
                p for p in (cells.feld.art, cells.away.art) if p
            ).strip()
            if not group_re.search(audience):
                continue

            halle = _parse_activity(cells.halle.art)
            if not (halle.type_code or halle.start):
                continue

            type_label = f"Förder {halle.type_code}" if halle.type_code else "Förder"
            type_full = "Fördertraining"
            garderobe = _combine_garderobe(cells.halle.g, cells.feld.g)
            notes = [f"Fördertraining ({audience})"] if audience else ["Fördertraining"]
            events.append(
                _make_event(
                    source, WEEKDAYS[day], cells.day_date, type_label, type_full,
                    "", "", _fmt_time(halle.start), _fmt_time(halle.end),
                    garderobe, _normalise_transport(cells.halle.trsp),
                    summary_format, team, notes,
                )
            )
    return events


def extract_events(week: WeekPlan, config: dict) -> list[Event]:
    """Extracts events for the configured team out of one week's plan."""
    team = config["team"]
    if team not in week.teams:
        return []

    team_slug = team.replace(" ", "-")
    source = f"{week.source_name}/{team_slug}"
    summary_format = config.get("summary_format", "{type} {place} {time}")

    events: list[Event] = []
    for day, cells in sorted(week.teams[team].items()):
        if cells.day_date is None:
            continue
        events.extend(
            _build_day_events(source, WEEKDAYS[day], cells, summary_format, team)
        )

    # Fördertrainings aimed at this team's whole age group (e.g. "U14/U16").
    age_group = _age_group(team)
    if age_group:
        events.extend(_forder_events(week, source, summary_format, team, age_group))

    events.sort(key=lambda e: (e.day_date, e.time_start or ""))
    return events
