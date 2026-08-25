#!/usr/bin/env bash
# One-time account setup for the AWS arm. Idempotent: safe to re-run.
#
#   AWS_PROFILE=research ./aws/setup.sh --bucket my-nfgate-bucket
#
# Creates: an S3 bucket for run output, an Object-Lock bucket for decision
# records, the two IAM roles, the ECR mirrors, and the gate Lambda.
# Prints every resource it made so teardown.sh can undo exactly those.
set -euo pipefail

BUCKET=""; DECISION_BUCKET=""; E1_ONLY=0; SKIP_ECR=0
while [ $# -gt 0 ]; do
  case "$1" in
    --bucket) BUCKET="$2"; shift 2 ;;
    --decision-bucket) DECISION_BUCKET="$2"; shift 2 ;;
    # E1 needs a bucket and the run role and nothing else: its probes declare
    # no container, so the ECR mirror (gigabytes, needs a docker daemon) and
    # the gate Lambda are both dead weight until E1 has returned an answer.
    --e1-only) E1_ONLY=1; shift ;;
    # The gate Lambda needs no container images. E2 tests the enforcement
    # point, not the pipeline, so mirroring gigabytes for it is waste.
    --skip-ecr) SKIP_ECR=1; shift ;;
    *) echo "unknown arg $1" >&2; exit 2 ;;
  esac
done
[ -n "$BUCKET" ] || { echo "usage: $0 --bucket NAME [--decision-bucket NAME]" >&2; exit 2; }
DECISION_BUCKET="${DECISION_BUCKET:-${BUCKET}-decisions}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${AWS_PROFILE:-default}"
REGION="${AWS_REGION:-$(aws configure get region --profile "$PROFILE")}"
AWSC=(aws --profile "$PROFILE" --region "$REGION")
ACCOUNT="$("${AWSC[@]}" sts get-caller-identity --query Account --output text)"
ECR_BASE="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

echo "== account $ACCOUNT region $REGION =="
# Appended, never truncated, and deduplicated on read. This file is the
# teardown list; a re-run that resets it would silently drop every resource
# created by the previous run -- which is exactly the run whose resources
# already exist and so are not re-noted below.
MADE="$ROOT/aws/results/created-resources.txt"
mkdir -p "$(dirname "$MADE")"; touch "$MADE"
note() {
  echo "$1"
  grep -qxF "$1" "$MADE" 2>/dev/null || echo "$1" >> "$MADE"
}

# --- buckets ----------------------------------------------------------------
if ! "${AWSC[@]}" s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  if [ "$REGION" = "us-east-1" ]; then
    "${AWSC[@]}" s3api create-bucket --bucket "$BUCKET" >/dev/null
  else
    "${AWSC[@]}" s3api create-bucket --bucket "$BUCKET" \
      --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
  fi
  note "s3://$BUCKET"
fi

# Decision records go in their own bucket with Object Lock in COMPLIANCE mode.
# Separate bucket because Object Lock can only be enabled at creation and you
# do not want run outputs undeletable for the retention period as well.
if ! "${AWSC[@]}" s3api head-bucket --bucket "$DECISION_BUCKET" 2>/dev/null; then
  if [ "$REGION" = "us-east-1" ]; then
    "${AWSC[@]}" s3api create-bucket --bucket "$DECISION_BUCKET" \
      --object-lock-enabled-for-bucket >/dev/null
  else
    "${AWSC[@]}" s3api create-bucket --bucket "$DECISION_BUCKET" \
      --create-bucket-configuration LocationConstraint="$REGION" \
      --object-lock-enabled-for-bucket >/dev/null
  fi
  "${AWSC[@]}" s3api put-object-lock-configuration --bucket "$DECISION_BUCKET" \
    --object-lock-configuration '{"ObjectLockEnabled":"Enabled","Rule":{"DefaultRetention":{"Mode":"COMPLIANCE","Days":1}}}' >/dev/null
  note "s3://$DECISION_BUCKET (object lock, COMPLIANCE, 1 day)"
  echo "   retention is 1 day: long enough to prove the property, short enough"
  echo "   that a test bucket does not become permanent"
fi

# --- iam --------------------------------------------------------------------
render() { sed -e "s/ACCOUNT_ID/$ACCOUNT/g" -e "s/REGION/$REGION/g" \
               -e "s/RUN_BUCKET/$BUCKET/g" -e "s/DECISION_BUCKET/$DECISION_BUCKET/g" "$1"; }

make_role() { # $1 name, $2 trust file, $3 policy file
  if ! "${AWSC[@]}" iam get-role --role-name "$1" >/dev/null 2>&1; then
    "${AWSC[@]}" iam create-role --role-name "$1" \
      --assume-role-policy-document "$(render "$2")" >/dev/null
    note "iam role $1"
  fi
  "${AWSC[@]}" iam put-role-policy --role-name "$1" \
    --policy-name "${1}-policy" --policy-document "$(render "$3")" >/dev/null
}

cat > /tmp/nfgate-lambda-trust.json <<'JSON'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
 "Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}
JSON

make_role nfgate-omics-run-role   "$ROOT/aws/iam/omics-run-role-trust.json" \
                                   "$ROOT/aws/iam/omics-run-role-policy.json"
make_role nfgate-startrun-gate-role /tmp/nfgate-lambda-trust.json \
                                   "$ROOT/aws/iam/gate-role-policy.json"
"${AWSC[@]}" iam attach-role-policy --role-name nfgate-startrun-gate-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole >/dev/null

echo
echo "NOT attached automatically: aws/iam/deny-startrun-except-gate.json"
echo "  That policy is the enforcement point, and attaching it to the wrong"
echo "  principal locks you out of your own account's HealthOmics. Attach it"
echo "  deliberately, to the roles that must not start runs directly:"
echo
echo "    aws iam put-role-policy --role-name YOUR_ROLE \\"
echo "      --policy-name deny-startrun-except-gate \\"
echo "      --policy-document file://<(sed s/ACCOUNT_ID/$ACCOUNT/g aws/iam/deny-startrun-except-gate.json)"
echo
echo "  E2 is not measured until it is attached and a direct StartRun is denied."

if [ "$E1_ONLY" = "1" ]; then
  echo
  echo "== --e1-only: skipping ECR mirrors and the gate lambda =="
  echo "== created (cumulative) =="; sort -u "$MADE"
  echo
  echo "next: python3 aws/bench/run_probe.py --bucket $BUCKET \\"
  echo "        --role-arn arn:aws:iam::${ACCOUNT}:role/nfgate-omics-run-role --confirm"
  exit 0
fi

# --- ecr mirrors ------------------------------------------------------------
# podman by preference, and not only because it is what is installed here: the
# local arm runs its containers under rootless podman, so mirroring with the
# same engine means the images pushed to ECR are the ones the measured runs
# actually used. Override with NFGATE_CONTAINER_CMD if you want otherwise.
if [ "$SKIP_ECR" = "1" ]; then
  echo "== --skip-ecr: not mirroring containers =="
else
CTR="${NFGATE_CONTAINER_CMD:-}"
if [ -z "$CTR" ]; then
  if command -v podman >/dev/null 2>&1; then CTR=podman
  elif command -v docker >/dev/null 2>&1; then CTR=docker
  else echo "no podman or docker on PATH -- cannot mirror containers" >&2; exit 1
  fi
fi
echo "== mirroring containers into ECR using $CTR =="

# Rootless podman keeps its own auth file; logging in per-image would be three
# identical round trips, so it happens once here.
"${AWSC[@]}" ecr get-login-password \
  | "$CTR" login --username AWS --password-stdin "$ECR_BASE"

while read -r src repo; do
  case "$src" in ''|\#*) continue ;; esac
  "${AWSC[@]}" ecr describe-repositories --repository-names "$repo" >/dev/null 2>&1 || {
    "${AWSC[@]}" ecr create-repository --repository-name "$repo" >/dev/null
    note "ecr repo $repo"
  }
  # HealthOmics pulls as a SERVICE PRINCIPAL, not as the run role, so the run
  # role's ecr:* grants are not sufficient and StartRun fails with a bare
  # "ECR access denied (omics.amazonaws.com)". Each repository needs its own
  # resource policy. Scoped with aws:SourceAccount so the repository cannot be
  # used as a confused deputy by another account's runs.
  "${AWSC[@]}" ecr set-repository-policy --repository-name "$repo" \
    --policy-text "$(render "$ROOT/aws/iam/ecr-repository-policy.json")" >/dev/null
  tag="${src##*:}"
  echo "   $src -> $ECR_BASE/$repo:$tag"
  # biocontainers images are multi-arch; HealthOmics runs x86_64, and rootless
  # podman on an x86_64 host picks that anyway. Named explicitly so the mirror
  # does not silently become arm64 if this is ever run from an Apple machine.
  "$CTR" pull --quiet --arch amd64 "docker.io/$src"
  "$CTR" tag "docker.io/$src" "$ECR_BASE/$repo:$tag"
  "$CTR" push --quiet "$ECR_BASE/$repo:$tag"
done < "$ROOT/aws/workflows/demo/containers.txt"
fi

# --- gate lambda ------------------------------------------------------------
echo "== packaging the gate lambda =="
STAGE=$(mktemp -d)
cp -r "$ROOT/gate" "$STAGE/gate"
cp -r "$ROOT/descriptors" "$STAGE/descriptors"
cp "$ROOT/aws/startrun_gate/handler.py" "$STAGE/handler.py"
find "$STAGE" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
(cd "$STAGE" && zip -qr /tmp/nfgate-gate.zip .)

GATE_ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/nfgate-startrun-gate-role"
if "${AWSC[@]}" lambda get-function --function-name nfgate-startrun-gate >/dev/null 2>&1; then
  "${AWSC[@]}" lambda update-function-code --function-name nfgate-startrun-gate \
    --zip-file fileb:///tmp/nfgate-gate.zip >/dev/null
else
  # Role propagation is eventually consistent; the first create after
  # create-role routinely fails with InvalidParameterValueException.
  for attempt in 1 2 3 4 5; do
    if "${AWSC[@]}" lambda create-function --function-name nfgate-startrun-gate \
        --runtime python3.12 --role "$GATE_ROLE_ARN" --handler handler.handler \
        --timeout 30 --memory-size 256 \
        --environment "Variables={GATE_DESCRIPTORS=/var/task/descriptors,GATE_DECISION_BUCKET=$DECISION_BUCKET}" \
        --zip-file fileb:///tmp/nfgate-gate.zip >/dev/null 2>&1; then
      note "lambda nfgate-startrun-gate"
      break
    fi
    echo "   waiting for role propagation ($attempt/5)"; sleep 10
  done
fi

rm -rf "$STAGE"
echo
echo "== created (cumulative) =="; sort -u "$MADE"
echo
echo "next: python3 aws/bench/run_probe.py --bucket $BUCKET \\"
echo "        --role-arn arn:aws:iam::${ACCOUNT}:role/nfgate-omics-run-role --confirm"
