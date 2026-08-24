#!/usr/bin/env bash
# Everything that must be true before a single AWS call costs money.
#
#   ./aws/preflight.sh                 # uses $AWS_PROFILE or default
#   AWS_PROFILE=research ./aws/preflight.sh
#
# Exits 0 only when the account can actually run the arm. Every failure prints
# the specific thing to fix rather than a stack trace, because the person
# fixing it is doing so between other work.
set -uo pipefail

PROFILE="${AWS_PROFILE:-default}"
REGION="${AWS_REGION:-$(aws configure get region --profile "$PROFILE" 2>/dev/null || echo us-east-1)}"
AWSC=(aws --profile "$PROFILE" --region "$REGION")

fail=0
ok()   { printf '  \033[32mok\033[0m    %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=1; }
warn() { printf '  \033[33mwarn\033[0m  %s\n' "$1"; }

echo "== preflight: profile=$PROFILE region=$REGION =="

# --- 1. tooling -------------------------------------------------------------
if command -v aws >/dev/null 2>&1; then
  ok "aws cli $(aws --version 2>&1 | cut -d' ' -f1)"
else
  bad "aws cli not on PATH"
fi

# HealthOmics arrived in botocore 1.29.x as the `omics` service. An older CLI
# fails with an unhelpful 'Invalid choice' rather than a version message.
if aws omics help >/dev/null 2>&1; then
  ok "aws omics subcommand present"
else
  bad "this aws cli has no 'omics' subcommand -- upgrade it"
fi

# --- 2. credentials ---------------------------------------------------------
ident="$("${AWSC[@]}" sts get-caller-identity --output json 2>&1)"
if echo "$ident" | grep -q '"Account"'; then
  acct=$(echo "$ident" | python3 -c 'import json,sys; print(json.load(sys.stdin)["Account"])')
  arn=$(echo "$ident" | python3 -c 'import json,sys; print(json.load(sys.stdin)["Arn"])')
  ok "credentials valid: account $acct"
  ok "caller: $arn"
else
  bad "credentials rejected for profile '$PROFILE'"
  echo "        $(echo "$ident" | head -1)"
  echo "        Fix: aws configure --profile $PROFILE   (or refresh SSO / assume the role)"
fi

# --- 3. is HealthOmics actually in this region? -----------------------------
# Not every region has it, and the failure mode without this check is a
# confusing AccessDenied rather than 'not here'.
if [ "$fail" -eq 0 ]; then
  wfs="$("${AWSC[@]}" omics list-workflows --max-results 1 --output json 2>&1)"
  case "$wfs" in
    *'"items"'*)      ok "HealthOmics reachable in $REGION" ;;
    *AccessDenied*)   bad "HealthOmics reachable but caller lacks omics:ListWorkflows" ;;
    *EndpointConnectionError*|*"Could not connect"*)
                      bad "HealthOmics has no endpoint in $REGION -- pick a supported region" ;;
    *)                bad "omics list-workflows failed: $(echo "$wfs" | head -1)" ;;
  esac
fi

# --- 4. permissions the arm needs -------------------------------------------
# Probed by calling the cheapest read in each service. A read that works is not
# proof the write will, but a read that fails is proof the write will not.
if [ "$fail" -eq 0 ]; then
  for probe in \
      "s3:ListAllMyBuckets|s3api list-buckets --max-items 1" \
      "iam:ListRoles|iam list-roles --max-items 1" \
      "logs:DescribeLogGroups|logs describe-log-groups --limit 1" \
      "lambda:ListFunctions|lambda list-functions --max-items 1" \
      "ecr:DescribeRepositories|ecr describe-repositories --max-results 1"
  do
    name="${probe%%|*}"; cmd="${probe#*|}"
    # shellcheck disable=SC2086
    if out="$("${AWSC[@]}" $cmd --output json 2>&1)"; then
      ok "$name"
    else
      case "$out" in
        *AccessDenied*|*UnauthorizedOperation*) bad "$name denied" ;;
        *RepositoryNotFound*|*"does not exist"*) ok "$name (nothing there yet, permission fine)" ;;
        *) warn "$name inconclusive: $(echo "$out" | head -1 | cut -c1-90)" ;;
      esac
    fi
  done
fi

# --- 5. quotas that bite ----------------------------------------------------
# The two that actually stop this arm: concurrent runs and max run duration.
if [ "$fail" -eq 0 ]; then
  q="$("${AWSC[@]}" service-quotas list-service-quotas --service-code omics \
        --max-results 100 --output json 2>/dev/null)"
  if [ -n "$q" ]; then
    python3 - "$q" <<'PY' || true
import json, sys
try:
    quotas = json.loads(sys.argv[1]).get("Quotas", [])
except Exception:
    sys.exit(0)
want = ("concurrent", "duration", "active runs", "workflows")
for qq in quotas:
    name = qq.get("QuotaName", "")
    if any(w in name.lower() for w in want):
        print(f"  info  quota: {name} = {qq.get('Value')}")
PY
  else
    warn "could not read service quotas (needs servicequotas:ListServiceQuotas)"
  fi
fi

# --- 6. what it will cost ---------------------------------------------------
echo
echo "== cost estimate for the full arm =="
python3 "$(dirname "$0")/bench/estimate_cost.py" --reps "${NFGATE_AWS_REPS:-30}"

echo
if [ "$fail" -eq 0 ]; then
  echo "preflight: PASS -- ./aws/setup.sh is safe to run"
else
  echo "preflight: FAIL -- fix the items above; nothing has been created or charged"
fi
exit "$fail"
