"""
Supplements the Wochenplan-derived events with a team's season Spielplan.

The Wochenplan is authoritative and always more recent, so within any week it
covers it wins outright. The Spielplan only fills the gaps around it:

  * A Spielplan game on a date **beyond** the downloaded Wochenplan window has
    no Wochenplan counterpart yet, so it becomes a tentative ("provisional")
    game entry - a heads-up that is superseded the moment that week's
    Wochenplan appears (the Wochenplan game then takes over under its own UID,
    and this one is reconciled away).

  * A Spielplan game whose week **is** covered by a Wochenplan, but which has no
    game in it that day, has probably been cancelled or moved. That is surfaced
    as a loud all-day marker (same visible, fail-loud spirit as the extraction
    error markers) so a human notices - never silently created.

Never raises: a missing/broken Spielplan yields a visible error marker instead
of vanishing, matching extract_events' fail-loud approach.
"""

from datetime import date
from pathlib import Path

from extract_events import (
    DEFAULT_AWAY_LABEL,
    DEFAULT_HOME_LABEL,
    DEFAULT_TRANSPORT_ICONS,
    TYPE_MAP,
    Event,
    _error_event,
    _make_event,
)
from fetch_plans import DOWNLOAD_DIR
from parse_plan import WEEKDAYS, parse_week
from parse_spielplan import DEFAULT_CLUB_NAME, SpielplanGame, parse_spielplan

# Tomato - the loud colour the sync also uses for error markers.
MARKER_COLOR_ID = "11"

# Per-team Spielplan policy (config "spielplan_mode"):
#   IGNORE   - never use the Spielplan (skip the supplement entirely)
#   OPTIONAL - use it if found, no-op if the team has none (default)
#   REQUIRE  - a missing Spielplan is an error (a loud marker), not silence
IGNORE, OPTIONAL, REQUIRE = "IGNORE", "OPTIONAL", "REQUIRE"
_MODES = {IGNORE, OPTIONAL, REQUIRE}
DEFAULT_MODE = OPTIONAL


def find_spielplan(
    team: str, config: dict, download_dir: Path = DOWNLOAD_DIR
) -> Path | None:
    """The Spielplan PDF for a team: an explicit config `spielplan` path wins,
    otherwise a downloads/ file whose name contains the team label. Returns None
    when the team has no Spielplan (the supplement is then a no-op)."""
    explicit = config.get("spielplan")
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    for path in sorted(download_dir.glob("Spielplan*.pdf")):
        if team.lower() in path.stem.lower():
            return path
    return None


def covered_dates(pdfs: list[Path]) -> set[date]:
    """Every calendar day the downloaded Wochenplans cover (whole weeks)."""
    dates: set[date] = set()
    for pdf in pdfs:
        try:
            for d in parse_week(pdf).dates:
                if d:
                    dates.add(d)
        except Exception:
            continue  # a broken week just narrows coverage; not fatal here
    return dates


def _town(place: str) -> str:
    """Drop a trailing 2-letter canton code: "Rapperswil SG" -> "Rapperswil"."""
    parts = place.rsplit(" ", 1)
    if len(parts) == 2 and len(parts[1]) == 2 and parts[1].isupper():
        return parts[0]
    return place


def _game_event(source: str, team: str, config: dict, g: SpielplanGame) -> Event:
    game_fmt = config.get(
        "game_summary_format", config.get("summary_format", "{type} {place} {time}")
    )
    # Mirror the Wochenplan: away games show the venue town, home games none.
    place = "" if g.is_home else _town(g.place)
    venue = ", ".join(p for p in (g.rink, g.place) if p)
    notes = [f"Gegner: {g.opponent}"]
    if venue:
        notes.append(f"Ort: {venue}")
    if g.round:
        notes.append(f"Spielrunde {g.round}")
    notes.append("Provisorisch (aus Spielplan)")
    return _make_event(
        source,
        WEEKDAYS[g.date.weekday()],
        g.date,
        g.game_type,
        TYPE_MAP.get(g.game_type, g.game_type),
        place,
        g.opponent,
        g.time,
        None,  # only a start time is known; _make_event assumes a duration
        "",
        "",
        game_fmt,
        team,
        notes,
        is_game=True,
        is_home=g.is_home,
        home_label=config.get("home_label", DEFAULT_HOME_LABEL),
        away_label=config.get("away_label", DEFAULT_AWAY_LABEL),
        transport_icons=config.get("transport_icons", DEFAULT_TRANSPORT_ICONS),
        myice_replaceable=True,
    )


def _cancellation_marker(source: str, g: SpielplanGame) -> Event:
    """A loud, all-day heads-up that a Spielplan game is missing from the
    Wochenplan covering its week - probably cancelled or moved."""
    return Event(
        source=source,
        day_date=g.date,
        weekday=WEEKDAYS[g.date.weekday()],
        type="ABSAGE?",
        type_full="Mögliche Absage",
        place="",
        opponent=g.opponent,
        time_start=None,
        time_end=None,
        garderobe="",
        transport="",
        summary=f"⚠️ Spiel evtl. abgesagt: {g.game_type} vs {g.opponent} "
        f"({g.time or '?'})",
        all_day=True,
        is_game=False,
        is_home=False,
        is_error=False,
        # A marker is a confirmed alert, never replaced by a myice booking.
        myice_replaceable=False,
        color_id=MARKER_COLOR_ID,
        notes=[
            f"Laut Spielplan Spiel am {g.date.isoformat()} gegen {g.opponent} "
            f"({g.time or '?'}), aber nicht im Wochenplan dieser Woche - "
            f"evtl. abgesagt oder verschoben.",
            "Quelle: Spielplan",
        ],
    )


def spielplan_supplement(
    config: dict,
    wp_events: list[Event],
    covered: set[date],
    today: date,
    download_dir: Path = DOWNLOAD_DIR,
) -> tuple[list[Event], dict]:
    """Extra events to add for one team: future Spielplan games plus
    cancellation markers. Returns (events, stats). Never raises - a broken or
    missing Spielplan surfaces as a visible error marker instead of silence.

    `covered` is the set of days the Wochenplans cover; `wp_events` are that
    team's already-extracted Wochenplan events (only their game days matter).
    `today` gates cancellation markers so past games aren't flagged."""
    team = config["team"]
    team_slug = team.replace(" ", "-")
    club = config.get("club_name", DEFAULT_CLUB_NAME)

    mode = str(config.get("spielplan_mode", DEFAULT_MODE)).upper()
    if mode == IGNORE:
        return [], {"spielplan": None, "spielplan_mode": IGNORE}
    if mode not in _MODES:
        allowed = ", ".join(sorted(_MODES))
        return [
            _error_event(
                f"?/{team_slug}", None,
                f"Ungültiger spielplan_mode {mode!r} (erlaubt: {allowed})",
            )
        ], {"spielplan": None, "spielplan_mode": mode, "error": "invalid mode"}

    path = find_spielplan(team, config, download_dir)
    if path is None:
        stats = {"spielplan": None, "spielplan_mode": mode}
        if mode == REQUIRE:
            return [
                _error_event(
                    f"Spielplan?/{team_slug}", None,
                    f"Spielplan für Team {team!r} erforderlich, aber nicht gefunden",
                )
            ], {**stats, "error": "missing"}
        return [], stats

    source = f"{path.name}/{team_slug}"
    try:
        plan = parse_spielplan(path, club_name=club)
    except Exception as exc:
        return [_error_event(source, None, f"Spielplan nicht lesbar: {exc}")], {
            "spielplan": path.name,
            "spielplan_mode": mode,
            "error": str(exc),
        }

    wp_game_dates = {e.day_date for e in wp_events if e.is_game and not e.is_error}

    events: list[Event] = []
    future = cancelled = covered_skip = 0
    for g in plan.games:
        if g.date in wp_game_dates:
            covered_skip += 1  # Wochenplan already has this game -> it wins
            continue
        if g.date in covered:
            # Its week is covered but the game isn't in it -> probable cancel.
            if g.date >= today:
                events.append(_cancellation_marker(source, g))
                cancelled += 1
            else:
                covered_skip += 1  # past & gone: nothing to do
        else:
            events.append(_game_event(source, team, config, g))
            future += 1

    return events, {
        "spielplan": path.name,
        "spielplan_mode": mode,
        "spielplan_future": future,
        "spielplan_cancelled": cancelled,
        "spielplan_covered": covered_skip,
    }
