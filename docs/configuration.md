# Configuration

## Teams

Copy `sync_configs_example.py` to `sync_configs.py` (gitignored — it holds real
calendar IDs) and list one entry per team. Each pairs an *exact* team label (e.g.
`"U14 A"` — "U14 Elit", "U14 Top" and "U14 A" are distinct teams) with a target
`calendar_id` and title templates.

`sync_configs_example.py` documents every field, including `game_summary_format`
(games are a tentative heads-up), `mih_overlap` (`REMOVE` | `KEEP` | `SHADOW`) for
events that overlap the myice feed, `spielplan_mode`, and `cancellations`. All entry
points fall back to importing `sync_configs_example` when `sync_configs` is absent,
so scripts still run without a private config.

## Secrets & environment

Copy `env.example` to `.env` and adjust as needed. See [secrets rule](../.claude/rules/secrets-and-config.md)
for what must never be committed.

- **Google service-account key** — read from `.google-service-account.json`
  (gitignored) if present, otherwise from AWS SSM Parameter Store (same secret as
  `../aws-ical-sync`: `/ical-sync/google-service-account` in `eu-central-2` by
  default, overridable via `SSM_PARAM_NAME` / `AWS_REGION`). Local scripts use the
  file; the deployed Lambda uses SSM. See that project's README for how the secret
  was created and shared with a calendar.
- **`SYNC_STATE_URI`** — where sync state lives: local `sync-state.json` by default,
  or `s3://bucket/key` on Lambda. See [cancelling.md](cancelling.md) and
  [deploy.md](deploy.md).
