# EHC Winterthur Trainingspläne → Google Calendar

Fetches EHC Winterthur's weekly "Wochenplan" training-schedule PDFs from the
club's WordPress site and converts them to Markdown, as groundwork for
syncing training/game entries into Google Calendar (same idempotent-upsert
approach as [aws-ical-sync](../aws-ical-sync), reusing its Google service
account secret).

**Pipeline:** discover/download the weekly PDFs → parse the team×weekday grid
→ extract per-team training/game events → sync them into Google Calendar
(idempotent upsert, dry-run by default).

## Setup

> [!IMPORTANT]
> This project directory lives on a `noexec` filesystem mount, which breaks
> mmap-loading of compiled `.so` files (e.g. `pydantic_core`, used by
> `docling`'s dependency chain and others) — `uv sync`'s default `.venv`
> here will fail at import time with `failed to map segment from shared
> object`. Point the venv at a normal filesystem instead, e.g.:
> ```bash
> export UV_PROJECT_ENVIRONMENT=~/.venvs/ehcw-trainings
> ```
> Put that in your shell profile (or re-export it each session) before
> running any `uv` command below.

```bash
uv sync
cp env.example .env   # then edit SSM_PARAM_NAME / AWS_REGION if needed
```

Run the tests with:

```bash
uv run python -m unittest discover -s . -p "test_*.py"
```

## Run

```bash
uv run python main.py
```

This fetches the current Wochenplan PDF for each week into `downloads/`
(skipping ones already downloaded, and keeping only the latest revision per
week — a revised plan is republished under a new filename, e.g.
`Wochenplan-34_Neu_1.pdf` superseding `Wochenplan-34_Neu.pdf` and
`Wochenplan-34.pdf`, so older revisions of the same week are dropped) and
converts each to Markdown in `markdown/`.

Inspect the generated Markdown to see the weekly grid (one row-group per
team, one column per weekday) as a table.

Conversion uses `pdfplumber`, not docling: the Wochenplan PDF has real
vector gridlines and embedded text (not a scan), and docling's ML
table-structure model — even in accurate mode — merged adjacent team rows
together (e.g. "MHL" and "U21 Top" collapsed into one row). pdfplumber reads
the vector grid directly and separates every row/column correctly.

## Configure teams

Copy `sync_configs_example.py` to `sync_configs.py` (gitignored) and list one
entry per team. Each pairs an *exact* team label (e.g. `"U14 A"` — "U14 Elit",
"U14 Top" and "U14 A" are distinct teams) with a target `calendar_id` and
title templates. See the example file for every field, including
`game_summary_format` (games are a tentative heads-up) and `mih_overlap`
(`REMOVE` | `KEEP` | `SHADOW`) for events that overlap the myice feed.

## Preview extracted events (offline, no credentials)

```bash
uv run python list_events.py
```

Parses the downloaded PDFs and prints every event it would create per team,
including any `⚠️ FEHLER` markers, to the console and `events.txt`. No Google
API calls — safe for verifying a team's config.

## Sync to Google Calendar

```bash
uv run python sync.py            # dry-run: reads the calendar, writes nothing
uv run python sync.py --apply    # actually create/update/delete events
```

Each event is upserted via `events.import()` keyed on a namespaced `iCalUID`
(so re-runs never duplicate), tagged with a private `source=ehcw-trainings`
property so reconciliation only ever touches events *this* project created —
never the myice (`mih-ehc-`) ones. Events removed from the plans are deleted;
past events are left alone (they are never created, updated, or deleted). A
parse/extract failure becomes a loud all-day error event rather than a silent
gap.

The service-account key is read from AWS SSM by default, or from a local
`.google-service-account.json` (gitignored) if present — so `sync.py` needs
either AWS credentials that can read the secret, or that local key file.

### Local test runs

```bash
bash run-local.sh            # fetch latest PDFs, then dry-run (writes nothing)
bash run-local.sh --apply    # actually create/update events
bash run-local.sh list       # fetch, then write the event preview to events.txt
SKIP_FETCH=1 bash run-local.sh   # sync what's already downloaded
```

The sync modes use the local `.google-service-account.json`, so no AWS access
is needed; `list` needs no key at all (it never touches Google Calendar). Run
it as `bash run-local.sh` (this directory is a `noexec` mount).

## Google Calendar secret

Uses the same AWS SSM Parameter Store secret as `aws-ical-sync`
(`/ical-sync/google-service-account` in `eu-central-2` by default,
overridable via `SSM_PARAM_NAME`/`AWS_REGION`) — see that project's README
for how the secret was created and shared with a calendar.
