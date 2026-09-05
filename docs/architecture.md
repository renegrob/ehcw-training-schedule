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
