#!/usr/bin/env python3
"""Turn the E3 runs into the two numbers the design document could only assert.

    python3 aws/bench/aggregate_aws.py

Reuses `interval()` and the embedded t-table from bench/aggregate.py rather
than reimplementing them, so the AWS arm and the local arm report intervals the
same way and a reader can compare them without checking whether "95% CI" means
the same thing twice.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))
from aggregate import interval  # noqa: E402

RESULTS = ROOT / "aws" / "results"


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=str(RESULTS / "e3_runs.jsonl"))
    ap.add_argument("--out", default=str(RESULTS / "e3_granularity.json"))
    args = ap.parse_args()

    path = Path(args.runs)
    if not path.exists():
        print(f"no runs at {path} -- run aws/bench/run_arm.py first", file=sys.stderr)
        return 1

    rows = load(path)
    permit = [r for r in rows if r["arm"] == "permit"]
    refuse = [r for r in rows if r["arm"] == "refuse"]

    # The two costs of coarse enforcement, in the units the argument is about.
    #
    # admitted:  the permit branch ran the whole pipeline, including the trim
    #            that a per-task gate would have refused. Everything downstream
    #            of the refused step is forbidden work that ran.
    # forbidden: the refuse branch started nothing, so the QC that a per-task
    #            gate would have permitted did not happen either.
    admitted_forbidden = []
    for r in permit:
        tasks = r.get("tasks", [])
        # SEQTK_TRIM is the refused action; MULTIQC consumes its output, so it
        # is downstream of a step that should not have run.
        bad = [t for t in tasks
               if t.get("name") and ("SEQTK_TRIM" in t["name"] or "MULTIQC" in t["name"])]
        admitted_forbidden.append(_vcpu(bad))

    forbidden_permitted = []
    for r in refuse:
        # Nothing ran, so the cost is what the permitted part WOULD have cost.
        # Taken from the paired permit replicate rather than from an average,
        # because pairing is what the interleaving was for.
        mate = next((p for p in permit if p["replicate"] == r["replicate"]), None)
        if not mate:
            continue
        good = [t for t in mate.get("tasks", []) if t.get("name") and "FASTQC" in t["name"]]
        forbidden_permitted.append(_vcpu(good))

    gate_ms = [r["gateWallMs"] for r in rows if r.get("gateWallMs") is not None]
    cold = [r["gateWallMs"] for r in rows if r.get("decision", {}).get("coldStart")]
    warm = [r["gateWallMs"] for r in rows if r.get("decision", {}).get("coldStart") is False]
    eval_us = [r["decision"]["evalMicros"] for r in rows
               if r.get("decision", {}).get("evalMicros") is not None]

    report = {
        "n": {"permit": len(permit), "refuse": len(refuse)},
        "refusalIsTotal": all(r["taskCount"] == 0 for r in refuse),
        "granularityCost": {
            "unit": "vCPU-seconds",
            "forbiddenWorkAdmitted": interval(admitted_forbidden),
            "permittedWorkForbidden": interval(forbidden_permitted),
            "reading": (
                "Whole-run granularity must choose one of these two. A per-task "
                "gate pays neither: it refuses the trim and runs the QC."),
        },
        "gateLatency": {
            "unit": "ms (end-to-end lambda invoke, client-observed)",
            "all": interval(gate_ms),
            "coldStart": interval(cold),
            "warm": interval(warm),
        },
        "policyEvaluation": {
            "unit": "microseconds (inside the handler)",
            "interval": interval([float(x) for x in eval_us]),
            "comparison": (
                "The local artifact measures 11 us policy evaluation and a 119 us "
                "gate process. The evaluation figure is the same quantity and "
                "should transfer; the process figure does NOT -- locally it is a "
                "python3 subprocess per task, here it is a Lambda invocation per "
                "run. Different mechanism, different granularity, not comparable."),
        },
    }

    # The refusal has to be total or the artifact is falsified, exactly as
    # bench/aggregate.py asserts locally. One counterexample matters more than
    # a widened interval.
    if not report["refusalIsTotal"]:
        started = [r["runId"] for r in refuse if r["taskCount"]]
        report["FALSIFIED"] = (
            f"A refused request started a run: {started}. The gate is not "
            f"prospective at StartRun and the enforcement point is unsound.")

    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


def _vcpu(tasks: list[dict]) -> float:
    from datetime import datetime
    total = 0.0
    for t in tasks:
        start, stop, cpus = t.get("startTime"), t.get("stopTime"), t.get("cpus")
        if not (start and stop and cpus):
            continue
        fmt = "%Y-%m-%dT%H:%M:%S.%f%z"
        try:
            a = datetime.strptime(start.replace("Z", "+0000"), fmt)
            b = datetime.strptime(stop.replace("Z", "+0000"), fmt)
        except ValueError:
            continue
        total += float(cpus) * (b - a).total_seconds()
    return total


if __name__ == "__main__":
    raise SystemExit(main())
