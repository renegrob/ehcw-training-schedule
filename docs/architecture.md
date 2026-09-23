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

- ~~A re-issued Wochenplan re-keys that week's events.~~ **Fixed.** `sync._uid()`
  normalises the *PDF filename* half of `Event.source` (`Wochenplan-38.pdf/U14-A`)
  to its week number via `week_key_from_name()` (from `fetch_plans.py`) before
  hashing, so `Wochenplan-38.pdf` and a later `Wochenplan-38_Neu.pdf` for the same
  week produce the same `iCalUID` for an unchanged event — tombstones and
  per-event state (reminders, manual colour edits) survive a re-issue. This
  shipped as a one-time re-key of every existing event (every UID changed on
  that `--apply`, appearing as a full delete + recreate); after that one run,
  re-issues are stable.

  **Lesson learned deploying this fix:** the re-key silently orphaned existing
  `sync-state.json` tombstones (they're keyed by the *old* UID, which no
  longer matches anything), so hand-deleted events briefly reappeared on the
  live calendar until the state was migrated by hand (matching old entries to
  their new UID by date+summary). Any future change to the fields `_uid()`
  hashes needs that same state migration *before* the next `--apply` — see the
  warning in `sync._uid()`'s docstring.
