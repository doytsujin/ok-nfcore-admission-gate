#!/usr/bin/env python3
"""Measure gate overhead from real Nextflow trace files.

Overhead is the difference in per-task wall time between two runs of the same
pipeline on the same inputs -- one ungated, one with the gate wired into
`process.beforeScript`. Nothing here is derived from a cost model; every number
comes out of Nextflow's own trace file, which it writes for the tasks it
actually ran.

Nextflow reports two per-task times:
  duration  submit -> complete, including scheduling and container setup
  realtime  the task script's own execution

The gate runs inside beforeScript, so it lands in `realtime`. Both are reported
because `duration` is what a pipeline operator feels and `realtime` is where
the gate actually sits.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path

_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
_TOKEN = re.compile(r"([0-9]*\.?[0-9]+)\s*(ms|s|m|h)")


def parse_duration(text: str) -> float | None:
    """Nextflow writes durations like '1.9s', '2m 30s', '136ms', or '-'."""
    text = (text or "").strip()
    if not text or text == "-":
        return None
    total, found = 0.0, False
    for value, unit in _TOKEN.findall(text):
        total += float(value) * _UNITS[unit]
        found = True
    return total if found else None


def read_trace(path: Path) -> list[dict]:
    lines = path.read_text().splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        rows.append(dict(zip(header, line.split("\t"))))
    return rows


def task_key(row: dict) -> str:
    """Match tasks across runs by name, which includes the sample tag."""
    return row.get("name", "")


def summarise(rows: list[dict]) -> dict:
    ok = [r for r in rows if r.get("status") == "COMPLETED"]
    durations = [d for d in (parse_duration(r.get("duration", "")) for r in ok) if d is not None]
    realtimes = [d for d in (parse_duration(r.get("realtime", "")) for r in ok) if d is not None]
    return {
        "tasks": len(rows),
        "completed": len(ok),
        "failed": sum(1 for r in rows if r.get("status") == "FAILED"),
        "durationTotalSec": round(sum(durations), 3),
        "realtimeTotalSec": round(sum(realtimes), 3),
        "durationMedianSec": round(statistics.median(durations), 3) if durations else None,
        "realtimeMedianSec": round(statistics.median(realtimes), 3) if realtimes else None,
    }


def paired_deltas(base: list[dict], gated: list[dict], field: str) -> list[tuple[str, float, float]]:
    """Pair tasks by name and return (name, baseline, gated) for completed pairs."""
    b = {task_key(r): r for r in base if r.get("status") == "COMPLETED"}
    g = {task_key(r): r for r in gated if r.get("status") == "COMPLETED"}
    out = []
    for name in sorted(set(b) & set(g)):
        bv = parse_duration(b[name].get(field, ""))
        gv = parse_duration(g[name].get(field, ""))
        if bv is not None and gv is not None:
            out.append((name, bv, gv))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True, type=Path)
    ap.add_argument("--gated", required=True, type=Path)
    ap.add_argument("--decisions", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=Path("results/overhead.json"))
    args = ap.parse_args()

    base = read_trace(args.baseline)
    gated = read_trace(args.gated)

    report: dict = {
        "baseline": summarise(base),
        "gated": summarise(gated),
        "perTask": {},
    }

    for field in ("realtime", "duration"):
        pairs = paired_deltas(base, gated, field)
        if not pairs:
            report["perTask"][field] = {"pairedTasks": 0}
            continue
        deltas = [g - b for _, b, g in pairs]
        base_total = sum(b for _, b, _ in pairs)
        gate_total = sum(g for _, _, g in pairs)
        report["perTask"][field] = {
            "pairedTasks": len(pairs),
            "baselineTotalSec": round(base_total, 3),
            "gatedTotalSec": round(gate_total, 3),
            "absoluteOverheadSec": round(gate_total - base_total, 3),
            "medianDeltaSec": round(statistics.median(deltas), 3),
            "relativeOverheadPct": (
                round(100.0 * (gate_total - base_total) / base_total, 2) if base_total else None
            ),
            "tasks": [
                {"name": n, "baselineSec": round(b, 3), "gatedSec": round(g, 3),
                 "deltaSec": round(g - b, 3)}
                for n, b, g in pairs
            ],
        }

    if args.decisions and args.decisions.exists():
        records = [json.loads(l) for l in args.decisions.read_text().splitlines() if l.strip()]
        permits = [r for r in records if r["verdict"] == "PERMIT"]
        refusals = [r for r in records if r["verdict"] == "REFUSE"]
        eval_micros = [r["evalMicros"] for r in records if "evalMicros" in r]
        wall_micros = [r["wallMicros"] for r in records if "wallMicros" in r]
        report["decisions"] = {
            "total": len(records),
            "permits": len(permits),
            "refusals": len(refusals),
            "refusalsByClass": {
                cls: sum(1 for r in refusals if r.get("reasonClass") == cls)
                for cls in sorted({r.get("reasonClass") for r in refusals if r.get("reasonClass")})
            },
            "policyEvalMedianMicros": round(statistics.median(eval_micros)) if eval_micros else None,
            "gateProcessMedianMicros": round(statistics.median(wall_micros)) if wall_micros else None,
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
