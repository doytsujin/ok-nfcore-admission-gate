#!/usr/bin/env python3
"""Measure what the gate costs as a *process*, not as a function.

The gate reports `wallMicros` from inside itself, which excludes the cost of
starting the interpreter that runs it. That was an acknowledged limitation while
n=1, because nothing in the end-to-end comparison could resolve a per-task
effect anyway. With 30 replicates it can, so the excluded cost is no longer
academic: it is the thing the replication actually measured.

This times the whole `python3 -m gate` invocation the way Nextflow invokes it,
and separates it into bare interpreter startup and the gate's own work, so the
end-to-end per-task delta can be attributed rather than guessed at.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WARMUP = 5


def _dist(samples: list[float]) -> dict:
    samples = sorted(samples)
    return {
        "n": len(samples),
        "medianMs": round(statistics.median(samples), 2),
        "meanMs": round(statistics.fmean(samples), 2),
        "sdMs": round(statistics.stdev(samples), 2) if len(samples) > 1 else None,
        "p95Ms": round(samples[min(len(samples) - 1, int(0.95 * len(samples)))], 2),
        "minMs": round(samples[0], 2),
        "maxMs": round(samples[-1], 2),
    }


def _time(cmd: list[str], env: dict | None, iterations: int) -> dict:
    for _ in range(WARMUP):
        subprocess.run(cmd, env=env, capture_output=True, cwd=ROOT)
    samples = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        subprocess.run(cmd, env=env, capture_output=True, cwd=ROOT)
        samples.append((time.perf_counter_ns() - start) / 1e6)
    return _dist(samples)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=60)
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "subprocess_cost.json")
    args = ap.parse_args()

    env = dict(os.environ, PYTHONPATH=str(ROOT))
    gate = _time(
        [sys.executable, "-m", "gate", "--descriptors", "descriptors",
         "--dataset", "raw-reads", "--action", "qc", "--context", "platform=illumina",
         "--log", "/dev/null", "--run-id", "probe", "--task", "probe"],
        env, args.iterations,
    )
    bare = _time([sys.executable, "-c", "pass"], None, args.iterations)

    report = {
        "pythonVersion": sys.version.split()[0],
        "gateProcess": gate,
        "bareInterpreter": bare,
        "gateOwnWorkMs": round(gate["medianMs"] - bare["medianMs"], 2),
        "note": (
            "The gate's self-reported wallMicros (~119 us median over 210 real decisions) "
            "measures argument parse to record written, inside the process. This measures "
            "the process. The difference is what a per-task subprocess deployment costs "
            "and what the end-to-end per-task delta is made of."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    print(f"gate subprocess: {gate['medianMs']:.1f} ms median "
          f"(p95 {gate['p95Ms']:.1f}, min {gate['minMs']:.1f})")
    print(f"bare python3:    {bare['medianMs']:.1f} ms median")
    print(f"gate's own work: {report['gateOwnWorkMs']:.1f} ms "
          f"-- against 11 us of policy evaluation inside it")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
