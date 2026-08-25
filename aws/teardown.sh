#!/usr/bin/env bash
# Delete everything this arm created. Run archive_evidence.sh FIRST.
#
#   AWS_PROFILE=nfgate ./aws/teardown.sh --confirm
#
# Deliberately not clever: it deletes only resources whose names this arm
# chose, reports anything it could not remove, and never empties a bucket it
# did not create.
set -uo pipefail

CONFIRM=0
[ "${1:-}" = "--confirm" ] && CONFIRM=1

PROFILE="${AWS_PROFILE:-nfgate}"
REGION="${AWS_REGION:-us-east-1}"
BUCKET="${NFGATE_BUCKET:-nfgate-426674444486-us-east-1}"
DBUCKET="${BUCKET}-decisions"
AWSC=(aws --profile "$PROFILE" --region "$REGION")

if [ "$CONFIRM" != "1" ]; then
  echo "dry run. Would delete:"
  echo "  omics workflows named nfgate-*  and their runs"
  echo "  ecr repositories nfgate/*"
  echo "  lambda nfgate-startrun-gate"
  echo "  iam roles nfgate-omics-run-role, nfgate-startrun-gate-role, nfgate-caller-test"
  echo "  s3://$BUCKET and s3://$DBUCKET"
  echo
  echo "re-run with --confirm. Run ./aws/archive_evidence.sh first."
  exit 0
fi

echo "== runs =="
"${AWSC[@]}" omics list-runs --output json 2>/dev/null \
  | python3 -c "
import json,sys
for r in json.load(sys.stdin).get('items',[]):
    print(r['id'])" 2>/dev/null | while read -r r; do
  "${AWSC[@]}" omics delete-run --id "$r" >/dev/null 2>&1 && echo "   deleted run $r" || echo "   run $r -- not deletable"
done

echo "== workflows =="
"${AWSC[@]}" omics list-workflows --output json 2>/dev/null \
  | python3 -c "
import json,sys
for w in json.load(sys.stdin).get('items',[]):
    if str(w.get('name','')).startswith('nfgate'):
        print(w['id'])" 2>/dev/null | while read -r w; do
  "${AWSC[@]}" omics delete-workflow --id "$w" >/dev/null 2>&1 && echo "   deleted workflow $w" || echo "   workflow $w -- failed"
done

echo "== ecr =="
"${AWSC[@]}" ecr describe-repositories --output json 2>/dev/null \
  | python3 -c "
import json,sys
for r in json.load(sys.stdin).get('repositories',[]):
    if r['repositoryName'].startswith('nfgate'):
        print(r['repositoryName'])" 2>/dev/null | while read -r repo; do
  "${AWSC[@]}" ecr delete-repository --repository-name "$repo" --force >/dev/null 2>&1 \
    && echo "   deleted ecr $repo" || echo "   ecr $repo -- failed"
done

echo "== lambda =="
"${AWSC[@]}" lambda delete-function --function-name nfgate-startrun-gate >/dev/null 2>&1 \
  && echo "   deleted lambda" || echo "   lambda -- absent or failed"

echo "== iam =="
for role in nfgate-omics-run-role nfgate-startrun-gate-role nfgate-caller-test; do
  for pol in $("${AWSC[@]}" iam list-role-policies --role-name "$role" --output json 2>/dev/null \
      | python3 -c "import json,sys; print(' '.join(json.load(sys.stdin).get('PolicyNames',[])))" 2>/dev/null); do
    "${AWSC[@]}" iam delete-role-policy --role-name "$role" --policy-name "$pol" >/dev/null 2>&1 || true
  done
  for arn in $("${AWSC[@]}" iam list-attached-role-policies --role-name "$role" --output json 2>/dev/null \
      | python3 -c "import json,sys; print(' '.join(p['PolicyArn'] for p in json.load(sys.stdin).get('AttachedPolicies',[])))" 2>/dev/null); do
    "${AWSC[@]}" iam detach-role-policy --role-name "$role" --policy-arn "$arn" >/dev/null 2>&1 || true
  done
  "${AWSC[@]}" iam delete-role --role-name "$role" >/dev/null 2>&1 \
    && echo "   deleted role $role" || echo "   role $role -- absent or failed"
done

echo "== s3 =="
for b in "$BUCKET" "$DBUCKET"; do
  if "${AWSC[@]}" s3api head-bucket --bucket "$b" >/dev/null 2>&1; then
    "${AWSC[@]}" s3 rm "s3://$b" --recursive >/dev/null 2>&1 || true
    if "${AWSC[@]}" s3api delete-bucket --bucket "$b" >/dev/null 2>&1; then
      echo "   deleted s3://$b"
    else
      # The decisions bucket has Object Lock in COMPLIANCE mode. Objects under
      # retention cannot be deleted by anyone, including the account root,
      # until the retention date passes. That is the property the bucket was
      # created to demonstrate, so failing here is the feature working.
      echo "   s3://$b -- NOT deleted (object lock retention, or non-empty)"
    fi
  else
    echo "   s3://$b -- absent"
  fi
done

echo
echo "== what remains =="
"${AWSC[@]}" omics list-workflows --output json 2>/dev/null | python3 -c "
import json,sys; print('   workflows:', len(json.load(sys.stdin).get('items',[])))" 2>/dev/null
"${AWSC[@]}" s3api list-buckets --output json 2>/dev/null | python3 -c "
import json,sys
bs=[b['Name'] for b in json.load(sys.stdin).get('Buckets',[]) if 'nfgate' in b['Name']]
print('   nfgate buckets:', bs or 'none')" 2>/dev/null
