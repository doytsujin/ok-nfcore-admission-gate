#!/usr/bin/env bash
# Pull the raw evidence out of AWS before the account is torn down.
#
# The evidence markdown in aws/results/ quotes logs verbatim and the verdict
# JSON is committed, but the underlying S3 objects and CloudWatch streams are
# the primary record behind claims that are going into papers. Deleting the
# account without them means no one -- including us -- can re-verify anything.
#
#   AWS_PROFILE=nfgate ./aws/archive_evidence.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${AWS_PROFILE:-nfgate}"
REGION="${AWS_REGION:-us-east-1}"
BUCKET="${NFGATE_BUCKET:-nfgate-AWS_ACCOUNT-us-east-1}"
DEST="$ROOT/aws/results/archive"
AWSC=(aws --profile "$PROFILE" --region "$REGION")

mkdir -p "$DEST"

# Runs cited in the evidence files and drafts.
RUNS="7520549 9958245 3778195 7868498 1144766 8101547 2475440"

echo "== run and task metadata =="
for r in $RUNS; do
  "${AWSC[@]}" omics get-run --id "$r" --output json > "$DEST/run_${r}.json" 2>/dev/null \
    && echo "   run $r" || echo "   run $r -- gone"
  "${AWSC[@]}" omics list-run-tasks --id "$r" --output json > "$DEST/tasks_${r}.json" 2>/dev/null || true
  # Task logs are where the refusal lines live. --start-from-head matters: the
  # default can return an empty page for a short task.
  for t in $(python3 -c "
import json,sys
try:
    print(' '.join(str(i['taskId']) for i in json.load(open('$DEST/tasks_${r}.json')).get('items',[])))
except Exception: pass" 2>/dev/null); do
    "${AWSC[@]}" logs get-log-events \
      --log-group-name /aws/omics/WorkflowLog \
      --log-stream-name "run/${r}/task/${t}" --start-from-head --output json \
      > "$DEST/log_${r}_${t}.json" 2>/dev/null && echo "      task $t log" || true
  done
done

echo "== published text outputs =="
# Only small text artefacts; run working data is regenerable and large.
"${AWSC[@]}" s3 ls "s3://$BUCKET/" --recursive 2>/dev/null \
  | awk '{print $NF}' \
  | grep -E '\.(out|done|witness|txt|json)$' \
  | grep -v '/logs/' \
  | while read -r key; do
      safe="${key//\//_}"
      "${AWSC[@]}" s3 cp "s3://$BUCKET/$key" "$DEST/obj_${safe}" >/dev/null 2>&1 \
        && echo "   $key" || true
    done

echo
echo "archived $(ls -1 "$DEST" | wc -l) files to $DEST"
du -sh "$DEST"
