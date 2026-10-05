# Behavioral invariants

Preserve these when changing anything in the extract → supplement → reconcile →
sync path. They are what makes re-running safe.

- **Fail loud, never silent.** Parse/extract failures and probable cancellations
  become visible Tomato-coloured (`colorId 11`) all-day marker events, not dropped
  output. `safe_extract` must always yield a `⚠️ FEHLER` marker rather than nothing.
- **Idempotency.** Events are keyed by a namespaced `iCalUID` and pushed via
  `events.import()`; re-runs must never duplicate.
- **Reconciliation is scoped** by the `source=ehcw-trainings` extendedProperty —
  never create, update, or delete myice (`mih-ehc-`) events or anything this project
  did not create.
- **Past events are left alone** — never created, updated, or deleted.
- **Tentative vs confirmed:** myice-replaceable events (regular trainings/games) are
  written *tentative* (the myice feed lags the plan but has no gaps, so it supersedes
  them); Förder trainings and free-skates are never on myice, so they stay *confirmed*
  and ignore time collisions.
- **An event removed from a plan never comes back on its own.** Anything dropped
  from the pipeline must leave a record in `sync_state` (`tombstones` for a manual
  deletion, `superseded` for a slot the myice feed took over under
  `mih_overlap: REMOVE`), because `reconcile` cannot tell "deliberately dropped"
  from "new" — a uid it does not recognise is created. In particular a myice entry
  *disappearing* means the player was reported absent, not that myice lags the
  plan, so the plan event stays away.
- **Error markers are untouchable** — never cancelled, never removed by overlap
  reconciliation.
- **The Wochenplan is authoritative** over the Spielplan for any day it covers.
