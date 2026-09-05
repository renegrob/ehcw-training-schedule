# Season Spielplan (future games & cancellations)

The Wochenplan only covers a few weeks out. A team's **Spielplan** — the
full-season game list — fills the gaps. Drop the team's `Spielplan <team>.pdf` into
`downloads/` (or point to it with the `spielplan` config key). Per-team behaviour is
set by `spielplan_mode`: `IGNORE`, `OPTIONAL` (default — use it if present), or
`REQUIRE` (a missing Spielplan becomes a loud error marker).

Unless ignored, `sync.py` supplements the Wochenplan events (see
`spielplan_events.py`):

- **Future games** on dates *beyond* the downloaded Wochenplan window are created as
  tentative, **provisional** game entries (using `game_summary_format`). When that
  week's Wochenplan later appears, its game takes over and the provisional one is
  reconciled away.
- **Probable cancellations:** a Spielplan game whose week *is* covered by a
  Wochenplan, but which has no game in it that day, becomes a loud all-day
  `⚠️ Spiel evtl. abgesagt` marker (only for upcoming games) — probably cancelled or
  moved. It is logged and shown on the calendar, never silently dropped.

The Wochenplan is authoritative: wherever it has a game, the Spielplan is ignored
for that day. Preview the whole classification (match / missing / future / wp-only)
without writing anything with `verify_spielplan.py` (see [running.md](running.md)).

The Spielplan PDF is a fixed-column report (not a vector table), so
`parse_spielplan.py` recovers its columns from the header word positions.
