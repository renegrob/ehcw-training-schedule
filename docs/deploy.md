# Deploying to AWS Lambda

`ehcw-trainings` runs serverless on AWS Lambda + EventBridge Scheduler, side by
side with the sibling [`aws-ical-sync`](../../aws-ical-sync): its own function,
role, schedule, and S3 bucket. The only thing the two share is the Google
service-account key in SSM. The daily **apply** job runs at **noon
Europe/Zurich** (DST-safe).

`deploy.sh` does the whole thing and is idempotent — re-run it after any code or
config change. Everything below uses placeholders; nothing here is
account-specific.

## What gets created

- **Lambda** `ehcw-trainings` (handler `lambda_function.handler`, Python 3.12).
- **Execution role** `ehcw-trainings-role` with `lambda-policy.json` attached.
- **Scheduler role** `ehcw-trainings-scheduler-role` + an EventBridge Scheduler
  schedule `ehcw-trainings-daily` (`cron(0 12 * * ? *)`,
  `--schedule-expression-timezone Europe/Zurich`).
- **S3 bucket** `ehcw-trainings-<account-id>` holding both the sync state and
  the season Spielplan PDFs (distinct prefixes — see below).
- Optional **SNS topic + CloudWatch alarm** for failure emails (only if
  `ALERT_EMAIL` is set in `.env`).

## S3 bucket layout

S3 bucket names are global, so both `create-bucket.sh` and `deploy.sh` derive a
unique one by suffixing your account id: `ehcw-trainings-<account-id>`.

`create-bucket.sh` provisions and **hardens** the bucket (standalone, idempotent):

```bash
./create-bucket.sh                 # region defaults to eu-central-2
REGION=eu-central-1 ./create-bucket.sh
```

It creates the bucket, blocks all public access, enables versioning (guards the
machine-maintained state against accidental clobbering), and attaches a resource
policy that **denies any non-TLS request** (`aws:SecureTransport`). It adds no
resource-based grant, so object access is governed solely by the Lambda role's
identity policy (`lambda-policy.json`) and no principal is locked out. `deploy.sh`
also ensures the bucket merely *exists* inline, so a plain deploy works on its
own — but run `create-bucket.sh` up front for the full hardening.

```
s3://ehcw-trainings-<account-id>/
  ehcw-trainings/sync-state.json     # read+write, machine-maintained (never edit by hand)
  spielplan/Spielplan U14 A.pdf      # read-only, you upload once per season
  spielplan/Spielplan <team>.pdf
```

- **`ehcw-trainings/sync-state.json`** — what the sync remembers it created, so
  events you delete in Google Calendar are not re-added (see
  [sync_state](../sync_state.py)). Created and maintained automatically; a
  first run with no object yet is handled as empty state.
- **`spielplan/`** — the static season Spielplan PDFs. On Lambda the local
  filesystem is ephemeral and the code package is read-only, so these live in
  S3. The handler pulls every `*.pdf` under this prefix into `/tmp/downloads` at
  the start of each run, where `find_spielplan` discovers them exactly as it
  would a local `downloads/` file.

## IAM (`lambda-policy.json`)

The committed policy is account-agnostic (wildcards, no account id or literal
bucket name):

- CloudWatch Logs (baseline).
- `ssm:GetParameter` on the shared Google service-account secret.
- `s3:GetObject`/`s3:PutObject` on the **one** state object
  (`ehcw-trainings-*/ehcw-trainings/sync-state.json`).
- `s3:GetObject` on the Spielplan PDFs (`ehcw-trainings-*/spielplan/*`).
- `s3:ListBucket` on `ehcw-trainings-*` — needed both to enumerate the Spielplan
  PDFs and so the first run reads the state correctly.

`s3:ListBucket` is granted unconditionally (this bucket is dedicated to the
project). It is required for the **first run**: `GetObject` on the not-yet-created
`sync-state.json` returns `NoSuchKey` (404, handled as empty state) *only* when
the caller has `ListBucket`; without it S3 returns `AccessDenied` (403) and the
run fails. `trust-policy.json` is the standard `lambda.amazonaws.com`
assume-role doc; `scheduler-trust-policy.json` is the `scheduler.amazonaws.com`
one.

## Account guard (Organizations setups)

If you authenticate through a **management** account and deploy into a separate
**workload** account (`export AWS_PROFILE=workload`), set `EXPECTED_ACCOUNT_ID`
to the workload account id in `.env`. `deploy.sh` and `create-bucket.sh` then
verify the live `aws sts get-caller-identity` matches before creating anything —
if the profile is unset or the SSO session expired (so the caller is really the
management account), the run **aborts** instead of provisioning in the wrong
account. Both scripts print the resolved account + ARN on every run; leaving
`EXPECTED_ACCOUNT_ID` unset disables the check (with a warning). You can also set
it inline: `EXPECTED_ACCOUNT_ID=123456789012 ./deploy.sh`.

## One-time setup

### 0. Authenticate into the workload account

```bash
aws login --profile management        # your SSO login
export AWS_PROFILE=workload           # switch into the workload account
aws sts get-caller-identity           # confirm the account id
```

### 1. Store the Google service-account key in SSM

This is the **same secret** `aws-ical-sync` uses — if you already deployed that
project, it is likely already present and you can skip this. Otherwise:

```bash
aws ssm put-parameter \
  --name "/ical-sync/google-service-account" \
  --type SecureString \
  --value file://path/to/service-account-key.json \
  --region eu-central-2
```

Use the same region as in `deploy.sh`.

### 2. Create your team config

`sync_configs.py` (gitignored, real calendar IDs) is bundled into the Lambda
package when present; `sync_configs_example.py` is bundled as a fallback so the
function still runs without it.

```bash
cp sync_configs_example.py sync_configs.py
# edit sync_configs.py with your teams and calendar IDs
```

### 3. Provision the bucket, then deploy

```bash
./create-bucket.sh   # create + harden the bucket (recommended)
./deploy.sh          # package, IAM, function, schedule (also creates the bucket if missing)
```

Either script creates the bucket, so it exists before you upload Spielplans;
`create-bucket.sh` additionally applies the hardening described above.

### 4. Upload the season Spielplan PDFs

Once per season, upload each team's Spielplan to the `spielplan/` prefix (the
`deploy.sh` output prints the exact bucket name and command):

```bash
aws s3 cp "Spielplan U14 A.pdf" s3://ehcw-trainings-<account-id>/spielplan/
```

The filename must contain the team label so `find_spielplan` matches it (see
[docs/spielplan.md](spielplan.md)). Re-uploading replaces the file; no redeploy
is needed for a Spielplan change.

## Configuration knobs (top of `deploy.sh`)

- `REGION` — an AWS region close to you (defaults to `eu-central-2`, matching
  the sibling).
- `SSM_PARAM_NAME` — path to the SSM parameter from step 1.
- `SCHEDULE_EXPRESSION` / `SCHEDULE_TIMEZONE` — daily-at-noon cron and its
  timezone. `Europe/Zurich` keeps it at local noon across DST.
- `LAMBDA_TIMEOUT` — seconds; the default leaves headroom for a first sync of a
  new calendar (many creates).

The function environment is set by `deploy.sh`:

| Env var              | Value                                             |
|----------------------|---------------------------------------------------|
| `SSM_PARAM_NAME`     | the Google secret parameter                       |
| `SYNC_STATE_URI`     | `s3://ehcw-trainings-<account-id>/ehcw-trainings/sync-state.json` |
| `SPIELPLAN_S3_PREFIX`| `s3://ehcw-trainings-<account-id>/spielplan/`     |
| `DOWNLOAD_DIR`       | `/tmp/downloads` (package dir is read-only)       |

## Error alerting (optional)

Copy `env.example` to `.env` and set `ALERT_EMAIL` to receive an email when a
daily run fails. `.env` is gitignored — never commit it. When set, `deploy.sh`
creates an SNS topic + a CloudWatch alarm on the Lambda `Errors` metric and
subscribes your address (confirm the subscription email once). Unset → the step
is skipped.

## Test it

```bash
aws lambda invoke --function-name ehcw-trainings --region eu-central-2 \
  --log-type Tail out.json && cat out.json
```

The manual invoke runs the real apply job. Check CloudWatch Logs and the
per-team JSON lines in the output. Re-running is safe — the sync is idempotent
(events are keyed by a namespaced `iCalUID` and pushed via `events.import()`).

## Local vs Lambda

Locally, leave `DOWNLOAD_DIR`, `SPIELPLAN_S3_PREFIX`, and `SYNC_STATE_URI`
unset: PDFs are fetched into / read from `downloads/`, and state defaults to
`sync-state.json` on disk (both gitignored). See [running.md](running.md) and
[configuration.md](configuration.md).
