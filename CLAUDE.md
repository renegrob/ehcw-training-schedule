# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Fetches EHC Winterthur "Wochenplan" (and season "Spielplan") schedule PDFs and syncs
the derived training/game events into Google Calendar (idempotent upsert, same
approach as the sibling `../aws-ical-sync`, shared service-account secret).

## Commands

```bash
uv sync                                                   # install deps (Python 3.12, uv)
uv run python -m unittest discover -s . -p "test_*.py"    # run all tests
uv run python -m unittest test_sync                       # one module
uv run python -m unittest test_sync.TestName.test_x       # one test

uv run python main.py            # fetch Wochenplan PDFs -> markdown/ (inspection only)
uv run python list_events.py     # offline event preview -> events.txt (no Google calls, no key)
uv run python verify_spielplan.py ["U14 A"]   # cross-check Wochenplan games vs Spielplan
uv run python sync.py [--apply]  # dry-run by default; --apply writes to the calendar
./run-local.sh [--apply|--list]  # fetch then sync/list using the LOCAL key (no AWS)
SKIP_FETCH=1 ./run-local.sh      # skip download, use PDFs already on disk
```

## Where things are

- **Architecture / data flow:** [docs/architecture.md](docs/architecture.md) — the
  fetch → parse → extract → supplement → reconcile → sync chain.
- **Running:** [docs/running.md](docs/running.md). **Config & secrets:**
  [docs/configuration.md](docs/configuration.md). **Spielplan:**
  [docs/spielplan.md](docs/spielplan.md). **Cancelling:**
  [docs/cancelling.md](docs/cancelling.md). **Deploy:** [docs/deploy.md](docs/deploy.md).
- **Rules you must follow** live in [`.claude/rules/`](.claude/rules/):
  - [invariants.md](.claude/rules/invariants.md) — fail-loud markers, idempotency,
    `source=ehcw-trainings` scoping, past-events-untouched, tentative-vs-confirmed.
  - [pdf-parsing.md](.claude/rules/pdf-parsing.md) — pdfplumber, not docling; why.
  - [secrets-and-config.md](.claude/rules/secrets-and-config.md) — gitignored keys and
    `sync_configs.py`; edit `sync_configs_example.py` instead.

## Conventions

- `team` labels must be **exact** ("U14 A" ≠ "U14 Elit" ≠ "U14 Top").
- Every module has a `test_*.py` (unittest). Keep them green; prefer testing
  extracted-event behavior over parser internals.
- Team config is `sync_configs.py` (gitignored); scripts fall back to
  `sync_configs_example.py` so they still run without it.
