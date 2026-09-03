"""
Team sync configuration. Copy this file to sync_configs.py and fill in your
own team(s) - sync_configs.py is gitignored (holds real calendar IDs).

Each entry in CONFIGS describes one team whose Wochenplan rows should be
turned into calendar events.

Fields:
  team             (required) - exact team label as it appears in the
                    Wochenplan's "Team" column, e.g. "U14 A". Must be exact:
                    "U14 Elit", "U14 Top" and "U14 A" are three different
                    teams, so "U14" alone is not selective enough.
  calendar_id      (required) - target Google Calendar ID (email or the
                    "...@group.calendar.google.com" id of a secondary
                    calendar shared with the service account)
  uid_prefix       (default: "ehc-") - namespaces this team's events so
                    multiple teams on the same calendar don't collide
  summary_format   (default: "{type} {place} {time}") - event title template.
                    Placeholders: {type} (activity abbreviation, e.g. "ET"),
                    {type_full} (expanded, e.g. "Eistraining"), {place} (venue
                    for games / rink for trainings), {opponent} (games only),
                    {home_away} (games only; see home_label/away_label),
                    {time} ("HH:MM-HH:MM", empty for all-day events),
                    {start}, {end}, {team}. Extra whitespace is collapsed, so
                    a template can list placeholders that are sometimes empty.
  game_summary_format (default: same as summary_format) - separate template
                    for games. Games are only a heads-up (a player isn't
                    necessarily called up), so give them a distinct, clearly
                    tentative title. Use {home_away} to show home/away and
                    {place} for the venue (empty for home games), e.g.
                    "❓ {home_away} {type} EHC vs {opponent} {place} {time}".
  home_label       (default: "🏠") - what {home_away} expands to for a home
                    game (the game's code+time sit in the Halle cell).
  away_label       (default: "🚗") - what {home_away} expands to for an away
                    game whose transport is empty/unrecognised (fallback).
  transport_icons  (default: {"pw": "🚗", "auto": "🚗", "bus": "🚌",
                    "car": "🚌", "zug": "🚆", "bahn": "🚆"}) - for away games,
                    {home_away} is picked from the plan's transport note (trsp)
                    by matching these substrings case-insensitively; no match
                    falls back to away_label. In Swiss usage "Car" is a coach,
                    so "Pw"/"Auto" -> 🚗 (private car) but "Car"/"Bus" -> 🚌.
  color_id         (optional) - Google Calendar event color, "1" through "11":
                    1 Lavender, 2 Sage, 3 Grape, 4 Flamingo, 5 Banana,
                    6 Tangerine, 7 Peacock, 8 Graphite, 9 Blueberry,
                    10 Basil, 11 Tomato
  mih_overlap      (default: "KEEP") - what to do with a PDF event that
                    overlaps an existing myice event (uid_prefix "mih-ehc-")
                    already on the calendar. The myice entry is authoritative:
                      REMOVE  drop the PDF event
                      KEEP    keep both
                      SHADOW  keep the PDF event but recolour it Graphite (8)
                    Only applies to events myice can replace (regular team
                    trainings and games). Förder trainings and free-skates are
                    never on myice, so a time collision there is ignored and
                    they always stay. Regardless of this policy, every
                    myice-replaceable event is written as *tentative* (the myice
                    feed lags the plan but has no gaps, so it will supersede
                    them); Förder trainings and free-skates stay *confirmed*.
  mih_uid_prefix   (default: "mih-ehc-") - iCalUID prefix identifying the
                    myice events to check overlaps against. If this is itself a
                    prefix of your own uid_prefix (e.g. myice "ehc-" vs your
                    "ehc-wp-"), your own events are automatically excluded, so
                    they are never mistaken for myice ones.
  cancellations    (optional) - list of events to suppress up front, so a
                    training you cancelled is deleted and never re-added on the
                    next --apply. Each entry scopes a single "date" or an
                    inclusive "from"/"to" range (good for a week away), narrowed
                    by an optional "time" (start "HH:MM") and/or "type" (activity
                    code). See cancellations.py. You can also just delete an
                    event in Google Calendar - the sync remembers it and won't
                    re-add it (see sync_state.py); this list is for pre-emptive
                    or bulk cancellations.
  spielplan_mode   (default: "OPTIONAL") - how this team uses its Spielplan:
                      IGNORE    don't use a Spielplan at all
                      OPTIONAL  use it if present, no-op if the team has none
                      REQUIRE   a missing Spielplan is a loud error marker (so a
                                team that should have one never silently lacks it)
  spielplan        (optional) - path to this team's season "Spielplan" PDF (the
                    full-season game list). If omitted, a downloads/ file named
                    "Spielplan <team>.pdf" is auto-detected. Unless
                    spielplan_mode is IGNORE, its games supplement the Wochenplan
                    (see spielplan_events.py):
                    games on dates beyond the downloaded Wochenplan window are
                    created as tentative "provisional" entries (using
                    game_summary_format), and games missing from a week the
                    Wochenplan *does* cover become a loud all-day "evtl.
                    abgesagt" marker (probable cancellation/reschedule). The
                    Wochenplan always wins where it has a game. Use
                    verify_spielplan.py to preview the classification without
                    writing anything.
  club_name        (default: "EHC Winterthur") - the club-name substring used to
                    tell our side from the opponent in the Spielplan's team
                    columns (e.g. "#106189 | EHC Winterthur"). Only relevant
                    when a Spielplan is used.
"""

CONFIGS = [
    {
        "team": "U14 A",
        "calendar_id": "primary",
        "uid_prefix": "ehc-",
        "summary_format": "🏒 EHC {type} {place} {time}",
        "game_summary_format": "❓ {home_away} {type} EHC vs {opponent} {place} {time} (prov.)",
        "color_id": "11",
        "mih_overlap": "REMOVE",  # REMOVE | KEEP | SHADOW
        "cancellations": [
            # {"date": "2026-09-02"},                  # cancel the whole day
            # {"date": "2026-09-25", "time": "16:15"}, # cancel one session
            # {"from": "2026-12-22", "to": "2026-12-28"},  # a week away
        ],
    },
]
