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
  mih_uid_prefix   (default: "mih-ehc-") - iCalUID prefix identifying the
                    myice events to check overlaps against.
"""

CONFIGS = [
    {
        "team": "U14 A",
        "calendar_id": "primary",
        "uid_prefix": "ehc-",
        "summary_format": "🏒 EHC {type} {place} {time}",
        "game_summary_format": "❓ EHC {type} vs {opponent} {time} (Aufgebot?)",
        "color_id": "11",
        "mih_overlap": "SHADOW",  # REMOVE | KEEP | SHADOW
    },
]
