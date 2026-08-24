#!/usr/bin/env bash
# The positive control for E1.
#
#   ./aws/bench/local_control.sh
#
# Runs both HealthOmics probes under the repository's own Nextflow, where the
# answer is known: `beforeScript` is honoured and a non-zero exit fails the
# task. That is the mechanism the whole artifact rests on.
#
# Why this must exist before the AWS runs: if the probes come back DROPPED and
# COMPLETED on HealthOmics, that is only evidence about HealthOmics if the same
# probes come back EXECUTED and FAILED here. Otherwise the finding is about a
# broken probe. An instrument that has never been read against a known answer
# measures nothing.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export JAVA_HOME="$ROOT/toolchain/jdk-21.0.12+8"
export PATH="$JAVA_HOME/bin:$PATH"
export NXF_HOME="$ROOT/toolchain/.nextflow"
export NXF_VER=24.10.5
NF="$ROOT/toolchain/nextflow"

WORK="${NFGATE_WORK:-$HOME/.nfgate-work}/e1-control"
PUB="$WORK/pub"
rm -rf "$WORK"; mkdir -p "$PUB"

echo "== E1a: does beforeScript execute? =="
"$NF" run "$ROOT/aws/workflows/probe-beforescript-observe/main.nf" \
  -w "$WORK/observe" --pubdir "$PUB" -ansi-log false >"$WORK/observe.log" 2>&1
observe_exit=$?
observe_verdict="$(head -1 "$PUB/probe.out" 2>/dev/null || echo NO_OUTPUT)"
echo "   nextflow exit=$observe_exit  verdict=$observe_verdict"

echo "== E1b: does a non-zero beforeScript stop the task? =="
"$NF" run "$ROOT/aws/workflows/probe-beforescript-enforce/main.nf" \
  -w "$WORK/enforce" --pubdir "$PUB" -ansi-log false >"$WORK/enforce.log" 2>&1
enforce_exit=$?
if [ -f "$PUB/enforce.out" ]; then enforce_verdict=EXIT_STATUS_DISCARDED
else enforce_verdict=TASK_STOPPED; fi
echo "   nextflow exit=$enforce_exit  verdict=$enforce_verdict"

nf_version="$("$NF" -version 2>/dev/null | grep -o 'version [0-9.]*' | head -1 | cut -d' ' -f2)"

cat > "$ROOT/aws/results/e1_local_control.json" <<JSON
{
  "what": "positive control for the HealthOmics beforeScript probes",
  "engine": "Nextflow ${nf_version:-$NXF_VER} (local, podman-less: the probes declare no container)",
  "date": "$(date -I)",
  "e1a_observe": {
    "nextflowExit": $observe_exit,
    "verdict": "$observe_verdict",
    "expected": "EXECUTED"
  },
  "e1b_enforce": {
    "nextflowExit": $enforce_exit,
    "verdict": "$enforce_verdict",
    "expected": "TASK_STOPPED"
  },
  "calibrated": $( [ "$observe_verdict" = "EXECUTED" ] && [ "$enforce_verdict" = "TASK_STOPPED" ] && echo true || echo false ),
  "reading": "With both expectations met, a DROPPED or COMPLETED result on AWS HealthOmics is attributable to the service rather than to the probe."
}
JSON

echo
cat "$ROOT/aws/results/e1_local_control.json"
