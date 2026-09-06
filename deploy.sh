#!/usr/bin/env bash
# Deploys the ehcw-trainings Lambda + daily EventBridge Scheduler schedule.
# Runs side by side with the sibling aws-ical-sync (separate function, role,
# schedule, and S3 bucket; the Google service-account SSM secret is shared).
#
# Prerequisites:
#   - AWS CLI configured (aws configure) with a user/role that can create
#     IAM roles, Lambda functions, EventBridge Scheduler schedules, S3
#     buckets, SNS topics, and CloudWatch alarms.
#   - The Google service-account key already stored in the SSM parameter
#     (see docs/deploy.md). This is the same secret aws-ical-sync uses.
#   - The season Spielplan PDFs uploaded once to s3://<bucket>/spielplan/
#     (see docs/deploy.md). The bucket itself is created below.
#   - uv installed (recommended) - used both to package the Lambda and to
#     regenerate requirements.txt from pyproject.toml. Falls back to pip +
#     the existing requirements.txt if uv isn't found.
#   - Optional: copy env.example to .env and set ALERT_EMAIL to receive
#     failure notifications. .env is gitignored - never commit it.
#
# Usage:
#   ./deploy.sh
#
# Re-running after code/config changes updates the existing function
# (idempotent).

set -euo pipefail

rm -f 'function.zip'

# ---- Config: edit these ----------------------------------------------
FUNCTION_NAME="ehcw-trainings"
REGION="eu-central-2"
SSM_PARAM_NAME="/ical-sync/google-service-account"   # shared with aws-ical-sync
SCHEDULE_EXPRESSION="cron(0 12 * * ? *)"             # noon, in the tz below
SCHEDULE_TIMEZONE="Europe/Zurich"                    # DST-safe local noon
ROLE_NAME="ehcw-trainings-role"
LAMBDA_TIMEOUT=300                                   # seconds - a steady-state
                                                     # run is ~90s (PDF fetch +
                                                     # parse + Google compare);
                                                     # headroom for more teams
                                                     # and heavy-change days

# ---- Local/personal config: .env (gitignored, not checked in) --------
# ALERT_EMAIL goes here instead of above, since it's personal data, not
# project config. Copy env.example to .env and fill it in.
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi
ALERT_EMAIL="${ALERT_EMAIL:-}"            # from .env; empty skips alerting setup

# ------------------------------------------------------------------------

# Resolve who we actually are. In an AWS Organizations setup you authenticate
# through the *management* account but deploy into the *workload* account
# (export AWS_PROFILE=workload) - so guard against silently deploying into the
# wrong one. Set EXPECTED_ACCOUNT_ID (in .env or inline) to the workload account
# id; a mismatch aborts before anything is created.
read -r ACCOUNT_ID CALLER_ARN < <(aws sts get-caller-identity --output text --query '[Account,Arn]')
echo "Caller: account $ACCOUNT_ID   ($CALLER_ARN)"
if [ -n "${EXPECTED_ACCOUNT_ID:-}" ] && [ "$EXPECTED_ACCOUNT_ID" != "$ACCOUNT_ID" ]; then
  echo "ERROR: expected account $EXPECTED_ACCOUNT_ID but caller is $ACCOUNT_ID." >&2
  echo "       Refusing to deploy into the wrong account. Did you 'export AWS_PROFILE=workload'" >&2
  echo "       (and re-run 'aws login' if the SSO session expired)?" >&2
  exit 1
elif [ -z "${EXPECTED_ACCOUNT_ID:-}" ]; then
  echo "NOTE: EXPECTED_ACCOUNT_ID not set - account guard is OFF." >&2
fi

# S3 bucket names are globally unique - suffix the account id so this is
# reproducible without a hand-picked name. Both the sync state and the season
# Spielplan PDFs live here (distinct prefixes).
STATE_BUCKET="ehcw-trainings-${ACCOUNT_ID}"
STATE_URI="s3://${STATE_BUCKET}/ehcw-trainings/sync-state.json"
SPIELPLAN_PREFIX="s3://${STATE_BUCKET}/spielplan/"

echo "== 1/9 Regenerating requirements.txt from pyproject.toml =="
if command -v uv &> /dev/null; then
  uv export --no-dev --no-hashes -o requirements.txt --quiet
else
  echo "uv not found - skipping regeneration, using existing requirements.txt as-is"
fi

echo "== 2/9 Packaging Lambda =="
PROJECT_DIR="$(pwd)"
BUILD_DIR=$(mktemp -d -t ehcw-trainings-build-XXXXXX)
trap 'rm -rf "$BUILD_DIR"' EXIT

if command -v uv &> /dev/null; then
  echo "Using uv for packaging..."
  # Lambda's python3.12 runtime is Amazon Linux 2023 (glibc 2.34). Target
  # manylinux_2_28, not the older manylinux2014 - modern Pillow (a pdfplumber
  # dependency) only ships manylinux_2_28 wheels.
  uv pip install -r requirements.txt -t "$BUILD_DIR" --quiet --only-binary :all: --python-platform x86_64-manylinux_2_28 --python-version 3.12
else
  echo "uv not found, falling back to pip..."
  pip install -r requirements.txt -t "$BUILD_DIR" --quiet --only-binary=:all: --platform manylinux_2_28_x86_64 --python-version 3.12 2>/dev/null \
    || pip install -r requirements.txt -t "$BUILD_DIR" --quiet
fi

# The Python modules the handler imports at runtime. Keep in sync with the
# import graph of lambda_function.py.
for f in lambda_function.py sync.py sync_state.py fetch_plans.py \
         extract_events.py parse_plan.py parse_spielplan.py \
         spielplan_events.py cancellations.py overlap.py \
         google_calendar.py convert_to_markdown.py; do
  [ -f "$f" ] && cp "$f" "$BUILD_DIR"/
done
# Team config: bundle the real one if present, else the example so the function
# still runs. sync_configs.py is gitignored (holds real calendar IDs).
if [ -f sync_configs.py ]; then
  cp sync_configs.py "$BUILD_DIR"/
fi
cp sync_configs_example.py "$BUILD_DIR"/
(cd "$BUILD_DIR" && zip -r "${PROJECT_DIR}/function.zip" . -q)
echo "Package size: $(du -h function.zip | cut -f1)"

echo "== 3/9 Ensuring S3 state/Spielplan bucket exists =="
if ! aws s3api head-bucket --bucket "$STATE_BUCKET" 2>/dev/null; then
  aws s3api create-bucket --bucket "$STATE_BUCKET" --region "$REGION" \
    --create-bucket-configuration "LocationConstraint=$REGION" >/dev/null
  echo "Created bucket $STATE_BUCKET"
else
  echo "Bucket $STATE_BUCKET already exists"
fi

echo "== 4/9 Creating/updating IAM role =="
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document file://trust-policy.json >/dev/null
  echo "Role created, waiting for IAM propagation..."
  sleep 10
fi
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "ehcw-trainings-policy" \
  --policy-document file://lambda-policy.json >/dev/null

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

echo "== 5/9 Checking SSM parameter exists =="
if ! aws ssm get-parameter --name "$SSM_PARAM_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "ERROR: SSM parameter $SSM_PARAM_NAME not found in $REGION."
  echo "Create it first with:"
  echo "  aws ssm put-parameter --name \"$SSM_PARAM_NAME\" --type SecureString \\"
  echo "    --value file://service-account-key.json --region $REGION"
  exit 1
fi

echo "== 6/9 Creating/updating Lambda function =="
export SSM_PARAM_NAME STATE_URI SPIELPLAN_PREFIX
ENV_JSON=$(python3 -c "import json, os; print(json.dumps({'Variables': {
    'SSM_PARAM_NAME': os.environ['SSM_PARAM_NAME'],
    'SYNC_STATE_URI': os.environ['STATE_URI'],
    'SPIELPLAN_S3_PREFIX': os.environ['SPIELPLAN_PREFIX'],
    'DOWNLOAD_DIR': '/tmp/downloads',
}}))")

if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file fileb://function.zip \
    --region "$REGION" >/dev/null
  aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
  aws lambda update-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --environment "$ENV_JSON" \
    --timeout "$LAMBDA_TIMEOUT" \
    --region "$REGION" >/dev/null
  aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
else
  aws lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.12 \
    --role "$ROLE_ARN" \
    --handler lambda_function.handler \
    --timeout "$LAMBDA_TIMEOUT" \
    --memory-size 256 \
    --zip-file fileb://function.zip \
    --environment "$ENV_JSON" \
    --region "$REGION" >/dev/null
fi

FUNCTION_ARN=$(aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" --query 'Configuration.FunctionArn' --output text)

echo "== 7/9 Creating/updating EventBridge Scheduler execution role =="
SCHEDULER_ROLE_NAME="${FUNCTION_NAME}-scheduler-role"
if ! aws iam get-role --role-name "$SCHEDULER_ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role \
    --role-name "$SCHEDULER_ROLE_NAME" \
    --assume-role-policy-document file://scheduler-trust-policy.json >/dev/null
  echo "Role created, waiting for IAM propagation..."
  sleep 10
fi

cat > scheduler-invoke-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "${FUNCTION_ARN}"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name "$SCHEDULER_ROLE_NAME" \
  --policy-name "${FUNCTION_NAME}-scheduler-invoke-policy" \
  --policy-document file://scheduler-invoke-policy.json >/dev/null

SCHEDULER_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${SCHEDULER_ROLE_NAME}"

echo "== 8/9 Creating/updating EventBridge Scheduler schedule =="
if aws scheduler get-schedule --name "${FUNCTION_NAME}-daily" --region "$REGION" >/dev/null 2>&1; then
  aws scheduler update-schedule \
    --name "${FUNCTION_NAME}-daily" \
    --schedule-expression "$SCHEDULE_EXPRESSION" \
    --schedule-expression-timezone "$SCHEDULE_TIMEZONE" \
    --flexible-time-window "Mode=OFF" \
    --target "{\"RoleArn\":\"$SCHEDULER_ROLE_ARN\",\"Arn\":\"$FUNCTION_ARN\"}" \
    --region "$REGION" >/dev/null
else
  aws scheduler create-schedule \
    --name "${FUNCTION_NAME}-daily" \
    --schedule-expression "$SCHEDULE_EXPRESSION" \
    --schedule-expression-timezone "$SCHEDULE_TIMEZONE" \
    --flexible-time-window "Mode=OFF" \
    --target "{\"RoleArn\":\"$SCHEDULER_ROLE_ARN\",\"Arn\":\"$FUNCTION_ARN\"}" \
    --region "$REGION" >/dev/null
fi

echo "== 9/9 Setting up error alerting =="
if [ -n "$ALERT_EMAIL" ]; then
  TOPIC_ARN=$(aws sns create-topic --name "${FUNCTION_NAME}-alerts" --region "$REGION" --query 'TopicArn' --output text)

  EXISTING_SUB=$(aws sns list-subscriptions-by-topic --topic-arn "$TOPIC_ARN" --region "$REGION" \
    --query "Subscriptions[?Endpoint=='${ALERT_EMAIL}'] | length(@)" --output text)
  if [ "$EXISTING_SUB" = "0" ]; then
    aws sns subscribe \
      --topic-arn "$TOPIC_ARN" \
      --protocol email \
      --notification-endpoint "$ALERT_EMAIL" \
      --region "$REGION" >/dev/null
    echo "Subscription email sent to $ALERT_EMAIL - you must click the confirmation link before alerts will deliver."
  fi

  aws cloudwatch put-metric-alarm \
    --alarm-name "${FUNCTION_NAME}-errors" \
    --alarm-description "Fires when $FUNCTION_NAME has one or more failed invocations in a 24h window" \
    --namespace "AWS/Lambda" \
    --metric-name "Errors" \
    --dimensions "Name=FunctionName,Value=${FUNCTION_NAME}" \
    --statistic Sum \
    --period 86400 \
    --evaluation-periods 1 \
    --threshold 1 \
    --comparison-operator GreaterThanOrEqualToThreshold \
    --treat-missing-data notBreaching \
    --alarm-actions "$TOPIC_ARN" \
    --region "$REGION" >/dev/null
  echo "Alarm '${FUNCTION_NAME}-errors' -> SNS topic '${FUNCTION_NAME}-alerts' -> $ALERT_EMAIL"
else
  echo "ALERT_EMAIL not set - skipping alarm/notification setup. Set it in .env to enable."
fi

echo "== Done =="
echo "Function: $FUNCTION_ARN"
echo "Bucket:   $STATE_BUCKET (state: $STATE_URI, spielplan: $SPIELPLAN_PREFIX)"
echo "Schedule: $SCHEDULE_EXPRESSION [$SCHEDULE_TIMEZONE] (via EventBridge Scheduler)"
echo ""
echo "Upload the season Spielplan PDFs (once per season) with:"
echo "  aws s3 cp \"Spielplan U14 A.pdf\" ${SPIELPLAN_PREFIX}"
echo ""
echo "Test it manually with:"
echo "  aws lambda invoke --function-name $FUNCTION_NAME --region $REGION --log-type Tail out.json && cat out.json"
