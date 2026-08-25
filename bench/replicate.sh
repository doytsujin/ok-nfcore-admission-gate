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
GATE_PORT="${GATE_PORT:-8731}"

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
    resident) cfg=(-c "$ROOT/bench/gate-resident.config") ;;
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

# The resident arm needs the daemon up for the whole sweep. Starting it per
# replicate would measure daemon startup, which is the cost being removed.
DAEMON_PID=""
if echo "$ARMS" | grep -qw resident; then
  rm -f "$WORK_BASE/gate-ready.json"
  # NOT wrapped in a subshell: `( ... ) &` makes $! the subshell's pid, so the
  # EXIT trap kills the wrapper and leaves the daemon holding the port. The
  # next sweep then fails to bind and the failure looks like the harness.
  # PYTHONPATH rather than cd, so the pid captured is python's own.
  PYTHONPATH="$ROOT" python3 -m gate.daemon --descriptors "$ROOT/descriptors" \
      --port "$GATE_PORT" --log "$DECISIONS/decisions_resident.jsonl" \
      --run-id resident --ready-file "$WORK_BASE/gate-ready.json" \
      >"$WORK_BASE/gate-daemon.log" 2>&1 &
  DAEMON_PID=$!
  # Wait on readiness rather than sleeping: a fixed sleep either wastes time or
  # races, and a race here would look like the gate refusing.
  for _ in $(seq 1 50); do
    [ -f "$WORK_BASE/gate-ready.json" ] && break
    sleep 0.1
  done
  if [ ! -f "$WORK_BASE/gate-ready.json" ]; then
    echo "gate daemon failed to start; last lines of its log:" >&2
    tail -3 "$WORK_BASE/gate-daemon.log" >&2
    exit 1
  fi
  trap '[ -n "$DAEMON_PID" ] && kill "$DAEMON_PID" 2>/dev/null' EXIT
  echo "gate daemon up on :$GATE_PORT (pid $DAEMON_PID)"
fi

echo "== replication: $REPS x [$ARMS] ==" | tee "$PROGRESS"
for i in $(seq 1 "$REPS"); do
  idx=$(printf "%02d" "$i")
  echo "-- replicate $idx --"
  for arm in $ARMS; do
    one_run "$arm" "$idx"
  done
done

echo "== done: $(ls "$TRACES" | wc -l) traces in $TRACES =="
