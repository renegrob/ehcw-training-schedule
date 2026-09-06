#!/usr/bin/env bash
# Creates and hardens the ehcw-trainings S3 bucket that holds the sync state and
# the season Spielplan PDFs. Standalone and idempotent - safe to re-run.
#
# deploy.sh also ensures the bucket merely *exists* (so a plain deploy works on
# its own), but this script is the one place that applies the full hardening:
# public-access block, versioning, and a TLS-only resource policy. Run it once
# up front (or any time to re-assert the settings), then deploy.
#
# Object access is granted to the Lambda via the identity-based policy in
# lambda-policy.json - this script does not add a resource-based grant, so no
# principal (you, or the function role) is locked out.
#
# Usage:
#   ./create-bucket.sh                 # region defaults to eu-central-2
#   REGION=eu-central-1 ./create-bucket.sh
#
# Prerequisites: AWS CLI configured with a principal allowed to create buckets
# and set bucket public-access-block / versioning / policy.

set -euo pipefail

# Personal/account-specific values (EXPECTED_ACCOUNT_ID) live in .env, gitignored.
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

REGION="${REGION:-eu-central-2}"

# Resolve who we actually are. In an AWS Organizations setup you authenticate
# through the *management* account but deploy into the *workload* account
# (export AWS_PROFILE=workload) - so guard against silently acting in the wrong
# one. Set EXPECTED_ACCOUNT_ID (in .env or inline) to the workload account id;
# a mismatch aborts before anything is created.
read -r ACCOUNT_ID CALLER_ARN < <(aws sts get-caller-identity --output text --query '[Account,Arn]')
echo "Caller: account $ACCOUNT_ID   ($CALLER_ARN)"
if [ -n "${EXPECTED_ACCOUNT_ID:-}" ] && [ "$EXPECTED_ACCOUNT_ID" != "$ACCOUNT_ID" ]; then
  echo "ERROR: expected account $EXPECTED_ACCOUNT_ID but caller is $ACCOUNT_ID." >&2
  echo "       Refusing to act in the wrong account. Did you 'export AWS_PROFILE=workload'" >&2
  echo "       (and re-run 'aws login' if the SSO session expired)?" >&2
  exit 1
elif [ -z "${EXPECTED_ACCOUNT_ID:-}" ]; then
  echo "NOTE: EXPECTED_ACCOUNT_ID not set - account guard is OFF." >&2
fi

# S3 bucket names are global - suffix the account id so it is unique and
# reproducible without a hand-picked name. Must match deploy.sh.
STATE_BUCKET="ehcw-trainings-${ACCOUNT_ID}"

echo "Bucket: $STATE_BUCKET   Region: $REGION"

echo "== 1/4 Creating bucket (if absent) =="
if aws s3api head-bucket --bucket "$STATE_BUCKET" 2>/dev/null; then
  echo "Bucket already exists"
else
  aws s3api create-bucket --bucket "$STATE_BUCKET" --region "$REGION" \
    --create-bucket-configuration "LocationConstraint=$REGION" >/dev/null
  echo "Created bucket"
fi

echo "== 2/4 Blocking all public access =="
aws s3api put-public-access-block --bucket "$STATE_BUCKET" \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" >/dev/null

echo "== 3/4 Enabling versioning =="
# Protects the machine-maintained sync state from accidental clobbering; the
# objects are tiny, so the cost is negligible.
aws s3api put-bucket-versioning --bucket "$STATE_BUCKET" \
  --versioning-configuration Status=Enabled >/dev/null

echo "== 4/4 Applying TLS-only bucket policy =="
POLICY_FILE=$(mktemp)
trap 'rm -f "$POLICY_FILE"' EXIT
cat > "$POLICY_FILE" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyInsecureTransport",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::${STATE_BUCKET}",
        "arn:aws:s3:::${STATE_BUCKET}/*"
      ],
      "Condition": { "Bool": { "aws:SecureTransport": "false" } }
    }
  ]
}
EOF
aws s3api put-bucket-policy --bucket "$STATE_BUCKET" --policy "file://$POLICY_FILE" >/dev/null

echo "== Done =="
echo "s3://${STATE_BUCKET}/  (public access blocked, versioning on, TLS-only)"
echo "  ehcw-trainings/sync-state.json   <- created/maintained automatically"
echo "  spielplan/                       <- upload season PDFs here:"
echo "      aws s3 cp \"Spielplan U14 A.pdf\" s3://${STATE_BUCKET}/spielplan/"
