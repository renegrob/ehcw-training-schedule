"""
Turns a parsed WeekPlan into calendar-ready events for one configured team.

Per team and weekday there are three sub-cells - Halle, Feld, Away. The
activity code + time may sit in *any* of them (the scheduler is inconsistent:
Wochenplan-40 puts most trainings in Feld with Halle empty), and a day can
carry several timed sessions, so each cell is inspected for a code and every
timed session becomes its own event:

  Training (activity code ET/TT/TH/TRL):
    * the code + time (e.g. "ET 1715-1815") is picked up from whichever slot
      holds it; multiple trainings in one day (e.g. Feld "ET" + Away "TT")
      each yield an event.
    * a single training may name its place/rink (e.g. "Wallrüti") in an
      otherwise-unused Feld/Halle cell.
    * a named extra like "freies Chneblä" or a written-out "Torhüter
      1630-1730" is its own event, timed from its own text or a lone
      bare-time sibling cell.

  Game (activity code MS/FS/ZC/TU/PO):
    * the code + time is picked up from whichever slot holds it; home when it
      is in Halle, away otherwise.
    * Halle names the venue/town (e.g. "Küssnacht") and Feld the opponent
      (e.g. "Innerschwyz").

Slot position does NOT encode an outdoor field - the plan marks outdoor
explicitly with the word "Aussen". Games list only a start time, so a default
duration is assumed. Days with content but no parseable time become all-day
events (the real time lives in another team's row, e.g. a joint U12 game).
"Car" is Swiss-German for a coach/bus and is normalised to "Bus".
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from parse_plan import WEEKDAYS, DayCells, WeekPlan, parse_week

# Games list only a start time; assume this duration for their end time.
DEFAULT_GAME_MINUTES = 90

# {home_away} marker defaults: a house for home games, and for away games an
# icon picked from the plan's transport note (trsp), falling back to a car.
# In Swiss usage "Car" is a coach/bus, so it maps to the bus icon (and is also
# normalised to "Bus" upstream); "Pw"/"Auto" is a private car.
DEFAULT_HOME_LABEL = "🏠"
DEFAULT_AWAY_LABEL = "🚗"
DEFAULT_TRANSPORT_ICONS = {
    "pw": "🚗", "auto": "🚗", "bus": "🚌", "car": "🚌", "zug": "🚆", "bahn": "🚆",
}

GAME_CODES = {"MS", "FS", "ZC", "TU", "PO"}
TRAINING_CODES = {"ET", "TT", "TH", "TRL"}

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
    is_game: bool = False  # games are tentative (a heads-up), not confirmed
    is_home: bool = False  # games only: at our home rink vs away (code in Halle)
    is_error: bool = False  # a fail-loud marker, not a real training/game
    # A myice booking may later replace this event (regular team-row trainings
    # and games): such events are marked tentative and are dropped when a myice
    # entry already overlaps them. Förder trainings, free-skates and error
    # markers are NOT replaceable - myice never carries them, so they stay
    # confirmed and survive overlap resolution untouched.
    myice_replaceable: bool = True
    color_id: str | None = None  # per-event colour override (else config default)
    notes: list[str] = field(default_factory=list)

    def start_datetime(self) -> datetime:
        """Interval start. All-day events span the whole day (00:00)."""
        if self.all_day or not self.time_start:
            return datetime.combine(self.day_date, datetime.min.time())
        h, m = self.time_start.split(":")
        return datetime.combine(self.day_date, datetime.min.time()).replace(
            hour=int(h), minute=int(m)
        )

    def end_datetime(self) -> datetime:
        """Interval end. All-day events span to the next midnight."""
        if self.all_day or not self.time_end:
            return datetime.combine(self.day_date, datetime.min.time()) + timedelta(
                days=1
            )
        h, m = self.time_end.split(":")
        return datetime.combine(self.day_date, datetime.min.time()).replace(
            hour=int(h), minute=int(m)
        )


def _fmt_time(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.zfill(4)
    return f"{raw[:2]}:{raw[2:]}"


def _plus_minutes(hhmm: str, minutes: int) -> str:
    start = datetime.strptime(hhmm, "%H:%M")
    return (start + timedelta(minutes=minutes)).strftime("%H:%M")


def _home_away_marker(
    is_home: bool, transport: str, home_label: str, away_label: str,
    transport_icons: dict[str, str],
) -> str:
    """Marker for a game title: `home_label` at home, otherwise an icon chosen
    from the transport note (e.g. "Pw" -> car, "Bus" -> coach), falling back to
    `away_label` when the transport is empty or unrecognised."""
    if is_home:
        return home_label
    low = (transport or "").lower()
    for key, icon in (transport_icons or {}).items():
        if key in low:
            return icon
    return away_label


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
    is_game: bool = False,
    is_home: bool = False,
    home_label: str = "",
    away_label: str = "",
    transport_icons: dict[str, str] | None = None,
    myice_replaceable: bool = True,
) -> Event:
    all_day = start is None
    if start and not end:
        # Games list only a start time - assume a default duration.
        end = _plus_minutes(start, DEFAULT_GAME_MINUTES)
    time = f"{start}-{end}" if start else ""
    # Home/away is meaningful for games only; blank elsewhere so the placeholder
    # collapses away in training titles.
    home_away = (
        _home_away_marker(is_home, transport, home_label, away_label, transport_icons)
        if is_game else ""
    )
    summary = re.sub(
        r"\s+",
        " ",
        summary_format.format(
            type=type_label, type_full=type_full, place=place,
            opponent=opponent, time=time, start=start or "", end=end or "",
            team=team, home_away=home_away,
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
        is_game=is_game,
        is_home=is_home,
        myice_replaceable=myice_replaceable,
        notes=notes,
    )


_SLOT_LABELS = {"halle": "Halle", "feld": "Feld", "away": "Away"}


def _build_day_events(
    source: str, weekday: str, cells: DayCells, summary_format: str,
    game_summary_format: str, team: str, home_label: str = "", away_label: str = "",
    transport_icons: dict[str, str] | None = None,
) -> list[Event]:
    """Turn one day's three sub-cells into events.

    The activity code+time may sit in *any* of the Halle/Feld/Away slots (the
    scheduler is inconsistent, e.g. Wochenplan-40 puts most trainings in Feld),
    and a day can carry more than one timed session. So each cell is inspected
    for a code, and every timed session yields its own event. Slot position
    only decides game home/away (Halle) and venue/opponent (Halle/Feld)."""
    if not (cells.halle.art or cells.feld.art or cells.away.art):
        return []  # completely empty day

    order = ("halle", "feld", "away")
    parsed = {name: _parse_activity(getattr(cells, name).art) for name in order}
    halle, feld = parsed["halle"], parsed["feld"]

    def garderobe_of(slots: set[str]) -> str:
        return _combine_garderobe(*(getattr(cells, s).g for s in order if s in slots))

    def transport_of(slots: set[str]) -> str:
        return _normalise_transport(*(getattr(cells, s).trsp for s in order if s in slots))

    specs: list[dict] = []  # one dict per event, resolved into Events at the end
    used: set[str] = set()  # slots already consumed as a session/venue/opponent

    # --- Games: a game code in any slot. Venue = Halle name, opponent = Feld name;
    #     home when the code is in Halle, away otherwise. ---
    venue = halle.leftover if halle.type_code is None else ""
    opponent = feld.leftover if feld.type_code is None else ""
    for slot in order:
        a = parsed[slot]
        if a.type_code not in GAME_CODES:
            continue
        specs.append(dict(
            kind="game", type_label=a.type_code,
            type_full=TYPE_MAP.get(a.type_code, a.type_code), place=venue,
            opponent=opponent, start=a.start, end=a.end,
            notes=[f"Gegner: {opponent}"] if opponent else [],
            is_game=True, is_home=(slot == "halle"), myice_replaceable=True,
            fmt=game_summary_format, own=set(order),
        ))
        used.add(slot)
    is_game_day = bool(specs)
    if is_game_day:  # the venue/opponent name cells belong to the game
        if venue:
            used.add("halle")
        if opponent:
            used.add("feld")

    # --- Trainings: a training code + time in any slot, each its own event. ---
    for slot in order:
        a = parsed[slot]
        if a.type_code in TRAINING_CODES and a.start is not None:
            specs.append(dict(
                kind="training", type_label=a.type_code,
                type_full=TYPE_MAP.get(a.type_code, a.type_code), place="",
                opponent="", start=a.start, end=a.end, notes=[], is_game=False,
                is_home=False, myice_replaceable=True, fmt=summary_format,
                own={slot},
            ))
            used.add(slot)

    # --- Named/extra sessions: a written-out activity ("freies Chneblä",
    #     "Torhüter 1630-1730") whose time is its own or a lone bare-time
    #     sibling (e.g. Feld "freies Chneblä" + Away "1600-1615"). These are
    #     EHC-only, so they stay confirmed (not myice-replaceable). ---
    for slot in order:
        if slot in used:
            continue
        a = parsed[slot]
        if a.type_code is not None or not a.leftover:
            continue
        start, end, borrowed = a.start, a.end, None
        if start is None:
            borrowed = next(
                (t for t in order if t not in used and t != slot
                 and parsed[t].type_code is None and not parsed[t].leftover
                 and parsed[t].start is not None),
                None,
            )
            if borrowed is not None:
                start, end = parsed[borrowed].start, parsed[borrowed].end
        if start is None:
            continue  # no time -> not a session; handled as a note below
        specs.append(dict(
            kind="named", type_label=a.leftover, type_full=a.leftover, place="",
            opponent="", start=start, end=end, notes=[], is_game=False,
            is_home=False, myice_replaceable=False, fmt=summary_format, own={slot},
        ))
        used.add(slot)
        if borrowed is not None:
            used.add(borrowed)

    primary = next((s for s in specs if s["kind"] == "training"), None)

    # A single training may name a place in an unused Feld/Halle cell (e.g.
    # Halle "ET 1715-1815" + Feld "Wallrüti"). On a game day those cells are the
    # venue/opponent, so a training then has no place of its own.
    if primary is not None and not is_game_day:
        for slot in ("feld", "halle"):
            a = parsed[slot]
            if (slot not in used and a.type_code is None and a.start is None
                    and a.leftover and not _NON_PLACE_RE.search(a.leftover)):
                primary["place"] = a.leftover
                used.add(slot)
                break

    # Remaining content becomes a note on the primary training, if any.
    if primary is not None:
        for slot in order:
            a = parsed[slot]
            if slot not in used and a.leftover:
                primary["notes"].append(f"{_SLOT_LABELS[slot]}: {a.leftover}")
                used.add(slot)

    # The primary training also absorbs the garderobe/transport of any cell not
    # owned by another session (e.g. a free-skate keeps its own Feld garderobe).
    if primary is not None and len(specs) > 1:
        owned_by_others = set().union(
            *(s["own"] for s in specs if s is not primary)
        )
        primary["own"] |= {s for s in order if s not in owned_by_others}

    # No coded/named/timed session but there is content -> a single all-day
    # event (e.g. a joint game whose real time lives in another team's row).
    if not specs:
        fallback = halle.leftover or parsed["away"].leftover or feld.leftover
        notes = [
            f"{_SLOT_LABELS[slot]}: {parsed[slot].leftover}"
            for slot in order
            if parsed[slot].leftover and parsed[slot].leftover != fallback
        ]
        specs.append(dict(
            kind="fallback", type_label=fallback, type_full=fallback, place="",
            opponent="", start=None, end=None, notes=notes, is_game=False,
            is_home=False, myice_replaceable=True, fmt=summary_format,
            own=set(order),
        ))

    return [
        _make_event(
            source, weekday, cells.day_date, s["type_label"], s["type_full"],
            s["place"], s["opponent"], _fmt_time(s["start"]), _fmt_time(s["end"]),
            garderobe_of(s["own"]), transport_of(s["own"]), s["fmt"], team,
            s["notes"], is_game=s["is_game"], is_home=s["is_home"],
            home_label=home_label, away_label=away_label,
            transport_icons=transport_icons, myice_replaceable=s["myice_replaceable"],
        )
        for s in specs
    ]


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
                    summary_format, team, notes, myice_replaceable=False,
                )
            )
    return events


def _error_event(source: str, day_date: date | None, message: str) -> Event:
    """A loud, all-day marker so a parse/extract failure is *seen* on the
    calendar rather than silently swallowed - better a false alarm than a
    missed training or game."""
    return Event(
        source=source,
        day_date=day_date or date.today(),
        weekday="",
        type="FEHLER",
        type_full="Fehler",
        place="",
        opponent="",
        time_start=None,
        time_end=None,
        garderobe="",
        transport="",
        summary=f"⚠️ FEHLER {source}: {message}",
        all_day=True,
        is_error=True,
        myice_replaceable=False,
        notes=[message],
    )


def _cells_dump(cells: DayCells) -> str:
    return (
        f"Halle={cells.halle.art!r} Feld={cells.feld.art!r} Away={cells.away.art!r}"
    )


def extract_events(week: WeekPlan, config: dict) -> list[Event]:
    """Extracts events for the configured team out of one week's plan.

    Never raises and never silently drops a day: a day that blows up (or a
    team row that has content but yields nothing) produces an error marker
    event instead."""
    team = config["team"]
    team_slug = team.replace(" ", "-")
    source = f"{week.source_name}/{team_slug}"
    summary_format = config.get("summary_format", "{type} {place} {time}")
    # Games are a tentative heads-up; default to the training template if the
    # config doesn't set a distinct one.
    game_summary_format = config.get("game_summary_format", summary_format)
    # Labels/icons for the {home_away} placeholder in game titles.
    home_label = config.get("home_label", DEFAULT_HOME_LABEL)
    away_label = config.get("away_label", DEFAULT_AWAY_LABEL)
    transport_icons = config.get("transport_icons", DEFAULT_TRANSPORT_ICONS)

    week_date = next((d for d in week.dates if d), None)

    if team not in week.teams:
        found = ", ".join(week.teams) or "keine"
        return [
            _error_event(
                source, week_date,
                f"Team {team!r} nicht im Plan gefunden (erkannte Teams: {found})",
            )
        ]

    events: list[Event] = []
    for day, cells in sorted(week.teams[team].items()):
        if cells.day_date is None:
            continue
        try:
            day_events = _build_day_events(
                source, WEEKDAYS[day], cells, summary_format,
                game_summary_format, team, home_label, away_label, transport_icons,
            )
        except Exception as exc:  # never lose the rest of the week over one day
            day_events = [
                _error_event(
                    source, cells.day_date,
                    f"{WEEKDAYS[day]} nicht lesbar: {exc} | {_cells_dump(cells)}",
                )
            ]
        # A day with content must yield at least one event.
        if not day_events and (cells.halle.art or cells.feld.art or cells.away.art):
            day_events = [
                _error_event(
                    source, cells.day_date,
                    f"{WEEKDAYS[day]}: Einträge vorhanden, aber kein Termin erkannt "
                    f"| {_cells_dump(cells)}",
                )
            ]
        events.extend(day_events)

    # Fördertrainings aimed at this team's whole age group (e.g. "U14/U16").
    age_group = _age_group(team)
    if age_group:
        try:
            events.extend(
                _forder_events(week, source, summary_format, team, age_group)
            )
        except Exception as exc:
            events.append(
                _error_event(source, week_date, f"Fördertraining nicht lesbar: {exc}")
            )

    events.sort(key=lambda e: (e.day_date, e.time_start or ""))
    return events


def safe_extract(pdf_path: str | Path, config: dict) -> list[Event]:
    """Parse a Wochenplan PDF and extract one team's events, converting *any*
    failure into a visible error event. This is the entry point callers should
    use so that a broken/renamed/reformatted PDF never yields zero events
    unnoticed."""
    name = Path(pdf_path).name
    team_slug = config.get("team", "?").replace(" ", "-")
    source = f"{name}/{team_slug}"

    try:
        week = parse_week(pdf_path)
    except Exception as exc:
        return [_error_event(source, None, f"PDF nicht lesbar: {exc}")]

    events: list[Event] = []
    if not any(d for d in week.dates):
        events.append(_error_event(source, None, "Keine Datumszeile im Plan gefunden"))

    try:
        events.extend(extract_events(week, config))
    except Exception as exc:  # defence in depth - extract_events shouldn't raise
        week_date = next((d for d in week.dates if d), None)
        events.append(_error_event(source, week_date, f"Extraktion fehlgeschlagen: {exc}"))

    return events
