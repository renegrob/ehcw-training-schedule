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
- **Error markers are untouchable** — never cancelled, never removed by overlap
  reconciliation.
- **The Wochenplan is authoritative** over the Spielplan for any day it covers.
