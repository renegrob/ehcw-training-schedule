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
                    {time} ("HH:MM-HH:MM", empty for all-day events),
                    {start}, {end}, {team}. Extra whitespace is collapsed, so
                    a template can list placeholders that are sometimes empty.
  game_summary_format (default: same as summary_format) - separate template
                    for games. Games are only a heads-up (a player isn't
                    necessarily called up), so give them a distinct, clearly
                    tentative title, e.g. "❓ EHC {type} vs {opponent} {time}".
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
"""

CONFIGS = [
    {
        "team": "U14 A",
        "calendar_id": "primary",
        "uid_prefix": "ehc-",
        "summary_format": "🏒 EHC {type} {place} {time}",
        "game_summary_format": "❓ EHC {type} vs {opponent} {time} (Aufgebot?)",
        "color_id": "11",
        "mih_overlap": "REMOVE",  # REMOVE | KEEP | SHADOW
        "cancellations": [
            # {"date": "2026-09-02"},                  # cancel the whole day
            # {"date": "2026-09-25", "time": "16:15"}, # cancel one session
            # {"from": "2026-12-22", "to": "2026-12-28"},  # a week away
        ],
    },
]
