# Architecture

A chain of small single-purpose modules; `sync.py` is the orchestrator.

1. **`fetch_plans.py`** — downloads Wochenplan PDFs from the club WordPress REST
   API into `downloads/`. Dedupes revisions of the same week by week number (a
   revised plan is republished under a new filename, so only the latest per week
   is kept).
2. **`parse_plan.py`** — parses a Wochenplan PDF (a real vector-lined table) into
   a `WeekPlan`: per team, per weekday, three sub-cells (Halle / Feld / Away).
3. **`extract_events.py`** — turns a `WeekPlan` into `Event`s for one configured
   team. Owns the Halle/Feld/Away semantics (they mean different things for
   trainings vs games), the `Event` dataclass, `TYPE_MAP`, `_make_event`,
   `_error_event`, and `safe_extract` (a broken/renamed PDF becomes a loud
   `⚠️ FEHLER` all-day event, never a silent gap). Sets `Event.myice_replaceable`.
4. **`parse_spielplan.py`** + **`spielplan_events.py`** — the season Spielplan
   (fixed-column report PDF, columns recovered from header x-positions) supplements
   the Wochenplan. See [spielplan.md](spielplan.md).
5. **`overlap.py`** — reconciles PDF events against existing myice-feed events
   (`mih-ehc-` prefix from aws-ical-sync). Only `myice_replaceable` events are
   affected; per-team `mih_overlap` policy is REMOVE / KEEP / SHADOW.
6. **`cancellations.py`** — drops plan-derived events listed in a team's
   `cancellations` *before* reconciliation. See [cancelling.md](cancelling.md).
7. **`sync.py`** — orchestrates: extract + supplement + cancel + overlap, then
   upserts each event via Google Calendar `events.import()` keyed on a namespaced
   `iCalUID` (idempotent, no DB), tagged `source=ehcw-trainings`. Dry-run by
   default; `--apply` writes.
8. **`sync_state.py`** — records what was synced so a manual deletion in Google
   Calendar is detected by *absence* and tombstoned (never re-added).

`convert_to_markdown.py` + `main.py` are the inspection-only path (PDF → Markdown
table).

The core behavioral invariants that must be preserved live in
[`.claude/rules/`](../.claude/rules/).

## Known limitations

- **Cross-team `freiwillig` sessions have no recoverable time.** A `<code>
  freiwillig` cell (e.g. `TT freiwillig`) in a team's row marks that team's
  *voluntary* participation in another (sibling) team's session of the same code —
  mandatory for that team, optional for this one. The session's time lives only in
  the other team's aligned cell, never in the `freiwillig` cell itself. Because
  `extract_events.py` parses one team row in isolation, it cannot recover that time
  and instead emits a visible all-day `freiwillig` marker (fail-visible, not a
  dropped day). Resolving the real time would require a cross-team join (reading the
  aligned cell in the sibling row), which is not implemented. Only relevant if such
  a team gets configured for sync.

- **A re-issued Wochenplan re-keys that week's events.** The `iCalUID` is a hash of
  `Event.source`, which is the *PDF filename* (`Wochenplan-38.pdf/U14-A`). The club
  republishes a corrected week under a new name rather than overwriting it
  (`Wochenplan-38_Neu.pdf`), and `latest_local_pdfs()` then switches to it — so every
  event of that week gets a new UID even when its date, time and type are unchanged.
  The sync reports this as a delete + create of the whole week rather than a quiet
  `unchanged`, and the new Google event ids lose any per-event state (reminders,
  manual colour edits).

  The consequence to watch: **tombstones are keyed by UID**, so an event you deleted
  by hand can come back after its week is re-issued — the tombstone no longer matches
  the new UID. If a deleted event reappears, this is why; delete it again (the fresh
  tombstone then sticks until the next re-issue of that week).

  Fixing it means hashing the *week* rather than the filename —
  `week_key_from_name()` in `fetch_plans.py` already normalises revisions to a week
  number for exactly this kind of de-duplication. That is deliberately not done: it
  would re-key every existing event once, i.e. a one-time full delete + recreate of
  the whole calendar.
