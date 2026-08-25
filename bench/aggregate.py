#!/usr/bin/env python3
"""Aggregate the replicated runs into intervals.

`bench/measure.py` compares one baseline run against one gated run, which is
enough to show the gate's own cost is below the trace's resolution and not
enough to put an interval on the end-to-end difference. This reads every
replicate and produces that interval.

The comparison is *paired by replicate index*, because `bench/replicate.sh`
interleaves the arms -- replicate 1 of each, then replicate 2 of each -- so
that machine state drifting over the hour lands on all arms equally. Pairing
removes the drift that both arms of a replicate share and leaves the
difference the gate is responsible for. An unpaired comparison of 30 baselines
against 30 gated runs would be measuring the hour as much as the gate.

Confidence intervals are Student-t on the paired differences. The t-table below
is embedded rather than imported: this repository has no dependencies and is
not going to acquire scipy to look up 2.045.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

from measure import parse_duration, read_trace, task_key  # same directory

# Two-sided 95% critical values. Exact where it matters (n around 30), and the
# normal limit past 120, which is the right approximation there.
_T95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056,
    27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042, 40: 2.021, 60: 2.000,
    120: 1.980,
}


def t95(df: int) -> float:
    if df <= 0:
        return float("nan")
    if df in _T95:
        return _T95[df]
    for key in sorted(_T95):
        if df < key:
            return _T95[key]
    return 1.960


def interval(values: list[float]) -> dict:
    """Mean, sd and a 95% t interval. Reports n=1 honestly instead of faking one."""
    n = len(values)
    if n == 0:
        return {"n": 0}
    mean = statistics.fmean(values)
    out = {
        "n": n,
        "mean": round(mean, 4),
        "median": round(statistics.median(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }
    if n < 2:
        out["note"] = "n=1: no interval"
        return out
    sd = statistics.stdev(values)
    half = t95(n - 1) * sd / math.sqrt(n)
    out.update({
        "sd": round(sd, 4),
        "ci95Low": round(mean - half, 4),
        "ci95High": round(mean + half, 4),
        "ci95HalfWidth": round(half, 4),
    })
    return out


def arm_runs(traces: Path, arm: str) -> dict[str, list[dict]]:
    """Every replicate of one arm, keyed by its zero-padded index."""
    out = {}
    for path in sorted(traces.glob(f"{arm}_*_trace.txt")):
        index = path.name[len(arm) + 1 : -len("_trace.txt")]
        out[index] = read_trace(path)
    return out


def totals(rows: list[dict], field: str) -> float:
    ok = [r for r in rows if r.get("status") == "COMPLETED"]
    return sum(d for d in (parse_duration(r.get(field, "")) for r in ok) if d is not None)


def per_task_paired(base: list[dict], gated: list[dict], field: str) -> list[float]:
    b = {task_key(r): r for r in base if r.get("status") == "COMPLETED"}
    g = {task_key(r): r for r in gated if r.get("status") == "COMPLETED"}
    deltas = []
    for name in sorted(set(b) & set(g)):
        bv, gv = parse_duration(b[name].get(field, "")), parse_duration(g[name].get(field, ""))
        if bv is not None and gv is not None:
            deltas.append(gv - bv)
    return deltas


def decisions(directory: Path, arm: str) -> list[dict]:
    records = []
    for path in sorted(directory.glob(f"decisions_{arm}_*.jsonl")):
        for line in path.read_text().splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


def summarise_decisions(records: list[dict]) -> dict:
    if not records:
        return {"total": 0}
    eval_micros = sorted(r["evalMicros"] for r in records if "evalMicros" in r)
    wall_micros = sorted(r["wallMicros"] for r in records if "wallMicros" in r)
    refusals = [r for r in records if r["verdict"] == "REFUSE"]

    def dist(samples: list[int]) -> dict:
        if not samples:
            return {"n": 0}
        return {
            "n": len(samples),
            "median": samples[len(samples) // 2],
            "mean": round(statistics.fmean(samples), 1),
            "p95": samples[min(len(samples) - 1, int(0.95 * len(samples)))],
            "min": samples[0],
            "max": samples[-1],
        }

    return {
        "total": len(records),
        "permits": sum(1 for r in records if r["verdict"] == "PERMIT"),
        "refusals": len(refusals),
        "refusalsByClass": {
            cls: sum(1 for r in refusals if r.get("reasonClass") == cls)
            for cls in sorted({r.get("reasonClass") for r in refusals if r.get("reasonClass")})
        },
        "policyEvalMicros": dist(eval_micros),
        "gateProcessMicros": dist(wall_micros),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", type=Path, default=Path("runs/replicates"))
    ap.add_argument("--decisions", type=Path, default=Path("results/replicates"))
    ap.add_argument("--out", type=Path, default=Path("results/replication.json"))
    ap.add_argument("--treatment", default="gated",
                    help="arm to compare against baseline. 'gated' is the "
                         "per-task subprocess gate; 'resident' is the daemon. "
                         "Both are paired against the same baseline replicates.")
    args = ap.parse_args()

    baseline = arm_runs(args.traces, "baseline")
    gated = arm_runs(args.traces, args.treatment)
    refuse = arm_runs(args.traces, "refuse")
    shared = sorted(set(baseline) & set(gated))
    if not shared:
        raise SystemExit(f"no paired replicates under {args.traces}")

    report: dict = {
        "treatment": args.treatment,
        "replicates": {
            "baseline": len(baseline),
            args.treatment: len(gated),
            "refuse": len(refuse),
            "paired": len(shared),
        },
        "pairing": "by replicate index; arms were interleaved, not blocked",
    }

    for field in ("realtime", "duration"):
        base_totals = [totals(baseline[i], field) for i in shared]
        gate_totals = [totals(gated[i], field) for i in shared]
        run_deltas = [g - b for b, g in zip(base_totals, gate_totals)]
        task_deltas = [d for i in shared for d in per_task_paired(baseline[i], gated[i], field)]
        report[field] = {
            "baselineRunTotalSec": interval(base_totals),
            "gatedRunTotalSec": interval(gate_totals),
            "pairedRunDeltaSec": interval(run_deltas),
            "pairedTaskDeltaSec": interval(task_deltas),
        }
        ci = report[field]["pairedRunDeltaSec"]
        if "ci95Low" in ci:
            report[field]["intervalIncludesZero"] = ci["ci95Low"] <= 0 <= ci["ci95High"]

    report["tasksPerRun"] = {
        arm: interval([float(len(rows)) for rows in runs.values()])
        for arm, runs in (("baseline", baseline), ("gated", gated), ("refuse", refuse))
    }
    report["decisions"] = {
        "gated": summarise_decisions(decisions(args.decisions, "gated")),
        "refuse": summarise_decisions(decisions(args.decisions, "refuse")),
    }

    # The refusal arm's claim is not statistical: SEQTK_TRIM must never have run
    # in any replicate. One counterexample falsifies the whole artifact, so it
    # is checked rather than assumed.
    trimmed = [
        (i, r.get("name"))
        for i, rows in refuse.items()
        for r in rows
        if "SEQTK_TRIM" in (r.get("name") or "") and r.get("status") == "COMPLETED"
    ]
    report["refusalHeld"] = {
        "replicates": len(refuse),
        "seqtkTrimCompletions": len(trimmed),
        "held": not trimmed,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    r = report["realtime"]
    print(f"paired replicates: {report['replicates']['paired']}")
    print(f"baseline total realtime: {r['baselineRunTotalSec']['mean']:.2f} s "
          f"(sd {r['baselineRunTotalSec'].get('sd', float('nan')):.2f})")
    print(f"gated    total realtime: {r['gatedRunTotalSec']['mean']:.2f} s "
          f"(sd {r['gatedRunTotalSec'].get('sd', float('nan')):.2f})")
    d = r["pairedRunDeltaSec"]
    print(f"paired delta: {d['mean']:+.3f} s, 95% CI "
          f"[{d.get('ci95Low', float('nan')):+.3f}, {d.get('ci95High', float('nan')):+.3f}] "
          f"-- includes zero: {report['realtime'].get('intervalIncludesZero')}")
    g = report["decisions"]["gated"]
    print(f"decisions: {g['total']} ({g['permits']} permit, {g['refusals']} refuse); "
          f"policy eval median {g['policyEvalMicros']['median']} us, "
          f"gate process median {g['gateProcessMicros']['median']} us")
    print(f"refusal held in every replicate: {report['refusalHeld']['held']}")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
