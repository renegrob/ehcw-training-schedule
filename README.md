# EHC Winterthur Trainingspläne → Google Calendar

Fetches EHC Winterthur's weekly "Wochenplan" training-schedule PDFs from the
club's WordPress site and converts them to Markdown, as groundwork for
syncing training/game entries into Google Calendar (same idempotent-upsert
approach as [aws-ical-sync](../aws-ical-sync), reusing its Google service
account secret).

**Current state (scaffolding):** PDF discovery/download + PDF→Markdown
conversion. Team/row extraction and calendar sync are not built yet.

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

## Next steps

- **Team/row extraction**: match a configured team by its *exact* row label
  (e.g. `"U14 A"` — note "U14 Elit", "U14 Top", and "U14 A" are three
  separate teams, so a bare `"U14"` is not selective enough), while still
  picking up generic age-group mentions elsewhere in the document (e.g. the
  "Förder-trainings" row's "Training für U14/U16" applies to all U14
  sub-teams, and remarks like "gem. Aufgebot" or "mit U16 A" signal joint
  sessions).
- **Templated event content**: subject built from the `Art` code expanded
  via the PDF's own legend (ET=Eistraining, TT=Trockentraining,
  TH=Torhütertraining, FS=Freundschaft, MS=Meisterschaft, PO=Play-Off,
  TU=Turnier, ZC=Züri-Cup, TRL=Trainingslager) plus the `Feld` place;
  description including `G` (Garderobe) and `Trsp` (Transport).
- **Traceable `source`**: each extracted event should carry a `source` of
  `{pdf_filename}/{team-label-with-dashes}`, e.g. `Wochenplan-39.pdf/U14-A`
  — also the basis for a future calendar UID/dedup key.
- **Local dry-run script**: extraction-only script that writes the resulting
  events to a JSON/text file, no Google API calls, so a team's config can be
  tested without touching a real calendar.
- **Multi-team config**: a list of entries (one per team, à la
  `aws-ical-sync`'s `sync_configs.py`) pairing an exact team label with a
  target `calendar_id`, so other club members can add their team via config,
  not code changes.
- **Periodic sync**: scan for new/changed PDFs and upsert events into Google
  Calendar, following `aws-ical-sync`'s `events.import()` + `iCalUID`
  pattern.

## Google Calendar secret

Uses the same AWS SSM Parameter Store secret as `aws-ical-sync`
(`/ical-sync/google-service-account` in `eu-central-2` by default,
overridable via `SSM_PARAM_NAME`/`AWS_REGION`) — see that project's README
for how the secret was created and shared with a calendar.
