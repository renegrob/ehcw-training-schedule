# Running

## Fetch & inspect PDFs

```bash
uv run python main.py
```

Fetches the current Wochenplan PDF for each week into `downloads/` (skipping ones
already downloaded, keeping only the latest revision per week — a revised plan is
republished under a new filename, e.g. `Wochenplan-34_Neu_1.pdf` superseding
`Wochenplan-34_Neu.pdf` and `Wochenplan-34.pdf`) and converts each to Markdown in
`markdown/`. Inspect the Markdown to see the weekly grid (one row-group per team,
one column per weekday) as a table.

## Preview extracted events (offline, no credentials)

```bash
uv run python list_events.py
```

Parses the downloaded PDFs and prints every event it would create per team —
including the season-Spielplan supplement (future games and probable-cancellation
markers) and any `⚠️ FEHLER` markers — to the console and `events.txt`. No Google
API calls; safe for verifying a team's config.

## Sync to Google Calendar

```bash
uv run python sync.py            # dry-run: reads the calendar, writes nothing
uv run python sync.py --apply    # actually create/update/delete events
```

Each event is upserted via `events.import()` keyed on a namespaced `iCalUID` (so
re-runs never duplicate), tagged `source=ehcw-trainings` so reconciliation only
touches events *this* project created. See [`.claude/rules/invariants.md`](../.claude/rules/invariants.md)
for the guarantees this relies on.

## Verify Spielplan matching

```bash
uv run python verify_spielplan.py            # all configured teams
uv run python verify_spielplan.py "U14 A"    # one team
```

Reports the match / missing / future / wp-only classification without writing
anything. See [spielplan.md](spielplan.md).

## Local test runs

```bash
./run-local.sh            # fetch latest PDFs, then dry-run (writes nothing)
./run-local.sh --apply    # actually create/update events
./run-local.sh --list     # fetch, then write the event preview to events.txt
./run-local.sh --help     # show usage
SKIP_FETCH=1 ./run-local.sh   # sync what's already downloaded
```

`run-local.sh` reads the Google key from the local `.google-service-account.json`
rather than AWS SSM; `--list` needs no key at all (it never touches Google
Calendar). It also uses a venv outside the project tree (`~/.venvs/ehcw-trainings`);
to run `uv` commands directly against it,
`export UV_PROJECT_ENVIRONMENT=~/.venvs/ehcw-trainings`.

### The sync state is shared with the deployed Lambda

The sync state holds the tombstones ("you deleted this event, stay away") and the
list of events we created. The Lambda keeps it in S3, so if a local run kept its
own copy the two would diverge and each would undo the other's deletions — a local
`--apply` would silently resurrect events you deleted, and vice versa.

So sync runs default to the **same S3 object** the Lambda uses, derived from the
caller's account id. Log in first:

```bash
source ./aws-login.sh      # SSO login, exports AWS_PROFILE=workload
./run-local.sh --apply
```

Each run prints which state it used (`Sync state: s3://…` or `./sync-state.json`).

| Situation | Behaviour |
|---|---|
| Logged in to AWS | Uses the shared S3 state |
| Not logged in, dry-run | **Loud warning**, falls back to local `./sync-state.json` — the created/deleted counts may be wrong |
| Not logged in, `--apply` | Hard error; refuses to write the calendar against unshared state |
| `LOCAL_STATE=1` | Forces the local file (escape hatch) |
| `SYNC_STATE_URI=…` | Explicit location, used as-is |

`AWS_PROFILE` defaults to `workload`. The profile's SSO credential provider needs
`botocore[crt]`, which the venv does not ship, so the script resolves credentials
via the AWS CLI and passes them to boto3 as environment variables.

If the two ever do drift apart, whichever side actually matches the calendar is the
correct one; upload it with
`aws s3 cp sync-state.json s3://ehcw-trainings-<account-id>/ehcw-trainings/sync-state.json`.
