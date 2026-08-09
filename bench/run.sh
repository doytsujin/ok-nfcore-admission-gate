#!/usr/bin/env bash
# Run the baseline and gated pipelines and measure the difference.
#
#   ./bench/run.sh baseline        ungated reference run
#   ./bench/run.sh gated           gate admits every task
#   ./bench/run.sh refuse          gate refuses SEQTK_TRIM (wrong read length)
#   ./bench/run.sh all             all three, then measure
#
# Everything the pipeline needs is under toolchain/ -- nothing is installed
# system-wide. The work directory deliberately lives outside the repo: this
# repo is normally checked out on removable media whose SELinux label is
# `unlabeled_t`, and container tasks cannot execute from there.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export JAVA_HOME="$ROOT/toolchain/jdk-21.0.12+8"
export PATH="$JAVA_HOME/bin:$PATH"
export NXF_HOME="$ROOT/toolchain/.nextflow"
export NXF_VER=24.10.5

NF="$ROOT/toolchain/nextflow"
PIPELINE="$ROOT/pipeline-nfcore-demo"
WORK_BASE="${NFGATE_WORK:-$HOME/.nfgate-work}"
RUNS="$ROOT/runs"
RESULTS="$ROOT/results"

mkdir -p "$RUNS" "$RESULTS" "$WORK_BASE"

run_baseline() {
  echo "== baseline (ungated) =="
  rm -rf "$WORK_BASE/baseline"
  "$NF" run "$PIPELINE" \
    -profile test,podman \
    -c "$ROOT/bench/common.config" \
    --outdir "$RUNS/baseline_out" \
    -w "$WORK_BASE/baseline" \
    -with-trace "$RUNS/baseline_trace.txt" \
    -ansi-log false
}

# $1 = label, $2 = min read length offered to the gate
run_gated() {
  local label="$1" minlen="$2"
  echo "== gated ($label, minReadLength=$minlen) =="
  rm -rf "$WORK_BASE/$label"
  rm -f "$RESULTS/decisions_$label.jsonl"
  GATE_ROOT="$ROOT" \
  GATE_LOG="$RESULTS/decisions_$label.jsonl" \
  GATE_RUN_ID="$label" \
  GATE_CTX_MINREADLEN="$minlen" \
  "$NF" run "$PIPELINE" \
    -profile test,podman \
    -c "$ROOT/bench/gate.config" \
    --outdir "$RUNS/${label}_out" \
    -w "$WORK_BASE/$label" \
    -with-trace "$RUNS/${label}_trace.txt" \
    -ansi-log false || true   # a refusal is expected to fail the pipeline
}

measure() {
  echo "== overhead =="
  python3 "$ROOT/bench/measure.py" \
    --baseline "$RUNS/baseline_trace.txt" \
    --gated "$RUNS/gated_trace.txt" \
    --decisions "$RESULTS/decisions_gated.jsonl" \
    --out "$RESULTS/overhead.json"
}

case "${1:-all}" in
  baseline) run_baseline ;;
  gated)    run_gated gated 30 ;;
  refuse)   run_gated refuse 10 ;;   # violates minReadLength >= 20
  measure)  measure ;;
  all)      run_baseline; run_gated gated 30; run_gated refuse 10; measure ;;
  *) echo "usage: $0 {baseline|gated|refuse|measure|all}" >&2; exit 2 ;;
esac
