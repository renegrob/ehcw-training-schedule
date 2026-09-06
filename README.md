# EHC Winterthur Trainingspläne → Google Calendar

Fetches EHC Winterthur's weekly "Wochenplan" training-schedule PDFs (and per-team
season "Spielplan" game-list PDFs) from the club's WordPress site and syncs the
derived training/game events into Google Calendar — same idempotent-upsert approach
as [aws-ical-sync](../aws-ical-sync), reusing its Google service-account secret.

**Pipeline:** discover/download the weekly PDFs → parse the team×weekday grid →
extract per-team training/game events (supplemented by the season Spielplan for
future games) → sync them into Google Calendar (idempotent upsert, dry-run by
default). See [docs/architecture.md](docs/architecture.md).

## Setup

```bash
uv sync
cp env.example .env          # then edit SSM_PARAM_NAME / AWS_REGION if needed
uv run python -m unittest discover -s . -p "test_*.py"   # run the tests
```

> [!NOTE]
> `run-local.sh` keeps its venv outside the project tree (default
> `~/.venvs/ehcw-trainings`). To reuse it for direct `uv` commands:
> `export UV_PROJECT_ENVIRONMENT=~/.venvs/ehcw-trainings`. Otherwise `uv sync`'s
> default in-project `.venv` works fine.

## Quick start

```bash
uv run python main.py            # fetch PDFs -> markdown/ for inspection
uv run python list_events.py     # offline preview of extracted events (no credentials)
uv run python sync.py            # dry-run sync (reads calendar, writes nothing)
uv run python sync.py --apply    # actually create/update/delete events
./run-local.sh [--apply|--list]  # fetch, then sync/list using the local key (no AWS)
```

## Docs

- [Running](docs/running.md) — all run modes and `run-local.sh`
- [Configuration](docs/configuration.md) — teams, secrets, environment
- [Architecture](docs/architecture.md) — module-by-module data flow
- [Season Spielplan](docs/spielplan.md) — future games & probable cancellations
- [Cancelling events](docs/cancelling.md) — sync state & tombstones
- [Deploy](docs/deploy.md) — Lambda packaging, IAM, S3 state

Project rules Claude must follow live in [`.claude/rules/`](.claude/rules/).
