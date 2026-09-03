"""
Cross-checks the games extracted from the Wochenplan against a team's season
Spielplan - a diagnostic to validate the matching logic before it drives any
calendar writes. It writes nothing; it only reports.

For every Spielplan game it prints one of:
  MATCH    - a Wochenplan game exists that day (details compared; any
             home/away or time discrepancy is flagged)
  MISSING  - the game's week is covered by a Wochenplan, but no game is in it
             -> probably cancelled (this is what the sync would notify on)
  FUTURE   - the game is beyond the downloaded Wochenplan window -> not yet
             covered (this is what the sync would create calendar entries for)

Wochenplan games with no Spielplan counterpart (e.g. friendlies/tournaments the
Spielplan doesn't list) are reported separately as WP-ONLY.

Usage:
  python verify_spielplan.py [team ...]      # defaults to all configured teams
"""

import sys
from datetime import date
from pathlib import Path

from extract_events import Event, safe_extract
from fetch_plans import latest_local_pdfs
from parse_spielplan import DEFAULT_CLUB_NAME, SpielplanGame, parse_spielplan
from spielplan_events import covered_dates, find_spielplan

try:
    from sync_configs import CONFIGS
except ImportError:
    from sync_configs_example import CONFIGS


def wochenplan_games(config: dict, pdfs: list[Path]) -> list[Event]:
    """All real game events extracted from the Wochenplans for one team."""
    games: list[Event] = []
    for pdf in pdfs:
        for event in safe_extract(pdf, config):
            if event.is_game and not event.is_error:
                games.append(event)
    return games


def _fmt_game(g: SpielplanGame) -> str:
    side = "home" if g.is_home else "away"
    return f"{g.date} {g.time or '  -  '} {g.game_type} {side} vs {g.opponent}"


def _discrepancies(sp: SpielplanGame, wp: Event) -> list[str]:
    issues = []
    if sp.is_home != wp.is_home:
        issues.append(
            f"home/away: Spielplan={'home' if sp.is_home else 'away'} "
            f"Wochenplan={'home' if wp.is_home else 'away'}"
        )
    if sp.time and wp.time_start and sp.time != wp.time_start:
        issues.append(f"time: Spielplan={sp.time} Wochenplan={wp.time_start}")
    return issues


def verify_team(config: dict, pdfs: list[Path]) -> dict:
    team = config["team"]
    club = config.get("club_name", DEFAULT_CLUB_NAME)
    print(f"\n=== {team} ===")

    spielplan_path = find_spielplan(team, config)
    if spielplan_path is None:
        print("  no Spielplan PDF found (skipping)")
        return {"team": team, "skipped": True}

    plan = parse_spielplan(spielplan_path, club_name=club)
    print(f"  Spielplan: {plan.source_name} ({len(plan.games)} games)")

    covered = covered_dates(pdfs)
    wp_games = wochenplan_games(config, pdfs)
    wp_by_date: dict[date, Event] = {g.day_date: g for g in wp_games}

    counts = {"match": 0, "missing": 0, "future": 0, "wp_only": 0, "flagged": 0}
    matched_dates: set[date] = set()

    for sp in sorted(plan.games, key=lambda g: (g.date, g.time or "")):
        wp = wp_by_date.get(sp.date)
        if wp is not None:
            matched_dates.add(sp.date)
            issues = _discrepancies(sp, wp)
            if issues:
                counts["flagged"] += 1
                print(f"  MATCH*   {_fmt_game(sp)}  [{'; '.join(issues)}]")
            else:
                counts["match"] += 1
                print(f"  MATCH    {_fmt_game(sp)}")
        elif sp.date in covered:
            counts["missing"] += 1
            print(f"  MISSING  {_fmt_game(sp)}  (covered week, not in Wochenplan)")
        else:
            counts["future"] += 1
            print(f"  FUTURE   {_fmt_game(sp)}")

    for wp in sorted(wp_games, key=lambda e: e.day_date):
        if wp.day_date not in matched_dates:
            counts["wp_only"] += 1
            side = "home" if wp.is_home else "away"
            print(
                f"  WP-ONLY  {wp.day_date} {wp.time_start or '  -  '} {wp.type} "
                f"{side} vs {wp.opponent or '?'}  (not in Spielplan)"
            )

    print(
        f"  -> {counts['match']} match, {counts['flagged']} flagged, "
        f"{counts['missing']} missing, {counts['future']} future, "
        f"{counts['wp_only']} wp-only"
    )
    counts["team"] = team
    return counts


def main(argv: list[str]) -> None:
    wanted = set(argv)
    configs = [c for c in CONFIGS if not wanted or c["team"] in wanted]
    if not configs:
        print(f"No configured team matches {sorted(wanted)}")
        return
    pdfs = latest_local_pdfs()
    print(f"{len(pdfs)} Wochenplan(s), {len(configs)} team(s)")
    for config in configs:
        verify_team(config, pdfs)


if __name__ == "__main__":
    main(sys.argv[1:])
