# Deploying to Lambda

This repo doesn't ship its own `deploy.sh` yet — packaging follows the sibling
[`aws-ical-sync`](../aws-ical-sync) (`uv export` → zip → `create/update-function`
→ EventBridge Scheduler). Two things this project needs on top of that baseline:
durable **sync state in S3** and its **IAM** grant.

## IAM

`lambda-policy.json` (attached to the function role via
`aws iam put-role-policy`, exactly as the sibling does) grants:

- CloudWatch Logs (baseline)
- `ssm:GetParameter` on the shared Google service-account secret
- `s3:GetObject` / `s3:PutObject` on the **one** state object

The S3 resource ARN is scoped to a single object and **must match**
`SYNC_STATE_URI` below. S3 bucket names are global, so pick a unique name (e.g.
prefix with your account id) and update the ARN in `lambda-policy.json` to match.

`s3:ListBucket` is intentionally omitted: a first run with no object yet returns
`NoSuchKey` (handled as empty state) as long as `GetObject` is granted.

`trust-policy.json` is the standard `lambda.amazonaws.com` assume-role doc.

## Deploy-script additions

Add to the config block:

```bash
STATE_BUCKET="ehcw-trainings-state"           # must be globally unique
STATE_KEY="ehcw-trainings/sync-state.json"    # must match lambda-policy.json
STATE_URI="s3://${STATE_BUCKET}/${STATE_KEY}"
```

Ensure the bucket exists (once), before creating the function:

```bash
if ! aws s3api head-bucket --bucket "$STATE_BUCKET" 2>/dev/null; then
  aws s3api create-bucket --bucket "$STATE_BUCKET" --region "$REGION" \
    --create-bucket-configuration "LocationConstraint=$REGION"
fi
```

Pass `SYNC_STATE_URI` into the function environment. The sibling builds
`ENV_JSON` with just the secret param; here it also carries the state URI (and
the secret env var this project reads is `SSM_PARAM_NAME`, not
`SERVICE_ACCOUNT_PARAM`):

```bash
export SSM_PARAM_NAME STATE_URI
ENV_JSON=$(python3 -c "import json, os; print(json.dumps({'Variables': {
    'SSM_PARAM_NAME': os.environ['SSM_PARAM_NAME'],
    'SYNC_STATE_URI': os.environ['STATE_URI'],
}}))")
```

`ENV_JSON` then flows into `create-function`/`update-function-configuration`
`--environment` unchanged.

Locally, leave `SYNC_STATE_URI` unset (or a plain path) — it defaults to
`sync-state.json` on disk, which is gitignored.
