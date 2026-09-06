# Secrets & private config

Never commit these (all gitignored — keep them that way):

- `.google-service-account.json` — the Google service-account key.
- `sync_configs.py` — holds real `calendar_id`s. Edit `sync_configs_example.py`
  (the committed, documented template) instead; new config fields go there first.
- `.env`, `sync-state.json`, `downloads/`, `markdown/`, `events.txt` / `events.json`.

Do not print secret values or real calendar IDs in logs, test output, or docs. Tests
and examples use the placeholder config in `sync_configs_example.py`.
