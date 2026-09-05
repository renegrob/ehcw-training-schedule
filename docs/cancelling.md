# Cancelling events

Two ways, both survive re-runs:

- **Delete it in Google Calendar.** The sync records what it created in a gitignored
  `sync-state.json`. On the next `--apply` it notices that an event it previously
  synced — still in the plan — has vanished from the calendar, concludes you
  cancelled it, and tombstones it so it is never re-added. This is the no-list way:
  Google Calendar is the control surface. (Deletion is detected by *absence*, so it
  does not depend on Google keeping deleted-event tombstones. To un-cancel, remove
  the uid from `sync-state.json`'s `tombstones`.) Detection needs a real `--apply`
  run to persist state.
- **List them up front** via a team's `cancellations` in `sync_configs.py` — handy
  for a whole week away (`{"from": ..., "to": ...}`). Cancellations are applied
  *before* reconciliation, so the event is deleted if still on the calendar and never
  re-created. See `sync_configs_example.py` / `cancellations.py`.

Error markers are never cancellable — a fail-loud marker must always survive.

## Sync state storage

State lives at `SYNC_STATE_URI` — a local path by default, or an `s3://bucket/key`
on Lambda (where the local filesystem is ephemeral, so S3 is the only place it
survives between invocations; the Lambda role then needs `s3:GetObject` /
`s3:PutObject` on that key). See [deploy.md](deploy.md).
