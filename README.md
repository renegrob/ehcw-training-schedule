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

Regular team-row trainings and games are the ones the myice feed can replace
(myice lags the plan but has no gaps), so they are written as **tentative** and
are dropped when a myice event already overlaps them (per `mih_overlap`). Förder
trainings and free-skates are never on myice, so they stay **confirmed** and a
time collision there is ignored.

### Cancelling events

Two ways, both survive re-runs:

- **Delete it in Google Calendar.** The sync records what it created in a
  gitignored `sync-state.json`. On the next `--apply` it notices that an event
  it previously synced — still in the plan — has vanished from the calendar,
  concludes you cancelled it, and tombstones it so it is never re-added. This is
  the no-list way: Google Calendar is the control surface. (Deletion is detected
  by *absence*, so it does not depend on Google keeping deleted-event
  tombstones. To un-cancel, remove the uid from `sync-state.json`'s
  `tombstones`.) Detection needs a real `--apply` run to persist state. The
  state lives at `SYNC_STATE_URI` — a local path by default, or an
  `s3://bucket/key` on Lambda (where the local filesystem is ephemeral, so S3
  is the only place it survives between invocations; the Lambda role then needs
  `s3:GetObject`/`s3:PutObject` on that key).
- **List them up front** via a team's `cancellations` in `sync_configs.py` —
  handy for a whole week away (`{"from": ..., "to": ...}`). See
  `sync_configs_example.py` / `cancellations.py`.

The service-account key is read from AWS SSM by default, or from a local
`.google-service-account.json` (gitignored) if present — so `sync.py` needs
either AWS credentials that can read the secret, or that local key file.

### Local test runs

```bash
./run-local.sh            # fetch latest PDFs, then dry-run (writes nothing)
./run-local.sh --apply    # actually create/update events
./run-local.sh --list     # fetch, then write the event preview to events.txt
./run-local.sh --help     # show usage
SKIP_FETCH=1 ./run-local.sh   # sync what's already downloaded
```

The sync modes use the local `.google-service-account.json`, so no AWS access
is needed; `--list` needs no key at all (it never touches Google Calendar).

## Google Calendar secret

Uses the same AWS SSM Parameter Store secret as `aws-ical-sync`
(`/ical-sync/google-service-account` in `eu-central-2` by default,
overridable via `SSM_PARAM_NAME`/`AWS_REGION`) — see that project's README
for how the secret was created and shared with a calendar.
