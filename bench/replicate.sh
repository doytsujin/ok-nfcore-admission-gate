#!/usr/bin/env bash
# Replicate the three arms N times each, keeping every run's trace.
#
#   ./bench/replicate.sh              30 replicates of baseline, gated, refuse
#   NFGATE_REPS=5 ./bench/replicate.sh
#   NFGATE_ARMS="baseline gated" ./bench/replicate.sh
#
# Why this exists: the artifact's headline numbers come from n=1 per arm, which
# is enough to show the gate's cost is below the trace's resolution and not
# enough to put an interval on the end-to-end difference. This produces the
# interval, and the corpus that the data descriptor describes.
#
# Arms are interleaved rather than blocked -- replicate 1 of every arm, then
# replicate 2 of every arm -- so that machine state drifting over the hour
# (page cache, thermal, whatever else is running) lands on all arms equally
# instead of on whichever arm ran last. The comparison is then paired by
# replicate index, which is what bench/aggregate.py does.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export JAVA_HOME="$ROOT/toolchain/jdk-21.0.12+8"
export PATH="$JAVA_HOME/bin:$PATH"
export NXF_HOME="$ROOT/toolchain/.nextflow"
export NXF_VER=24.10.5

NF="$ROOT/toolchain/nextflow"
PIPELINE="$ROOT/pipeline-nfcore-demo"
WORK_BASE="${NFGATE_WORK:-$HOME/.nfgate-work}"
REPS="${NFGATE_REPS:-30}"
ARMS="${NFGATE_ARMS:-baseline gated refuse}"

TRACES="$ROOT/runs/replicates"
DECISIONS="$ROOT/results/replicates"
LOGS="$WORK_BASE/replicate-logs"
PROGRESS="$DECISIONS/progress.txt"

mkdir -p "$TRACES" "$DECISIONS" "$LOGS" "$WORK_BASE"

# Outputs go under the work base, not into the repo: 90 copies of the same
# MultiQC report is not a corpus, it is 90 copies of the same MultiQC report.
# Only the trace and the decision log are kept.
OUTBASE="$WORK_BASE/replicate-out"

# $1 = arm, $2 = zero-padded replicate index
one_run() {
  local arm="$1" idx="$2"
  local label="${arm}_${idx}"
  local work="$WORK_BASE/$label"
  local trace="$TRACES/${label}_trace.txt"
  local log="$LOGS/${label}.log"

  rm -rf "$work" "$OUTBASE/$label"
  # The decision log is opened O_APPEND, so a re-run of the same replicate
  # index would double-count rather than replace. Clear it first.
  rm -f "$trace" "$DECISIONS/decisions_${label}.jsonl"

  local -a cfg
  case "$arm" in
    baseline) cfg=(-c "$ROOT/bench/common.config") ;;
    gated)    cfg=(-c "$ROOT/bench/gate.config") ;;
    refuse)   cfg=(-c "$ROOT/bench/gate.config") ;;
  esac

  local minlen=30
  [ "$arm" = "refuse" ] && minlen=10

  GATE_ROOT="$ROOT" \
  GATE_LOG="$DECISIONS/decisions_${label}.jsonl" \
  GATE_RUN_ID="$label" \
  GATE_CTX_MINREADLEN="$minlen" \
  "$NF" run "$PIPELINE" \
    -profile test,podman \
    "${cfg[@]}" \
    --outdir "$OUTBASE/$label" \
    -w "$work" \
    -with-trace "$trace" \
    -ansi-log false >"$log" 2>&1 || true   # the refuse arm is meant to fail

  # The work directory is the expensive part on disk; the trace is the product.
  rm -rf "$work" "$OUTBASE/$label"

  local tasks="?"
  [ -f "$trace" ] && tasks=$(( $(wc -l < "$trace") - 1 ))
  echo "$(date -Is) $label tasks=$tasks" >> "$PROGRESS"
  echo "   $label  tasks=$tasks"
}

echo "== replication: $REPS x [$ARMS] ==" | tee "$PROGRESS"
for i in $(seq 1 "$REPS"); do
  idx=$(printf "%02d" "$i")
  echo "-- replicate $idx --"
  for arm in $ARMS; do
    one_run "$arm" "$idx"
  done
done

echo "== done: $(ls "$TRACES" | wc -l) traces in $TRACES =="
