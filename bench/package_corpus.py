#!/usr/bin/env python3
"""Package the replicated runs as a described, checksummed corpus.

A data descriptor needs the data to be identifiable, countable and fixed. This
writes a manifest over the files the replication produced -- every trace, every
decision log, every descriptor that gated them -- with a SHA-256 and a record
count for each, so that a reader can tell whether the corpus they have is the
corpus that was described.

Nothing is copied. The files already live in the repository under
`runs/replicates/` and `results/replicates/`; duplicating them into a
`dataset/` tree would double the bytes and create a second thing to keep in
sync. The manifest points at them where they are.

If `croissant_policy` from ok-croissant-policy-profile is importable, the
corpus is also emitted as a policy-bearing Croissant document. That is not
decoration: the corpus is a dataset of admission decisions, it has a state and
conditions of use like any other, and describing it with the profile is the
cheapest available check that the profile survives contact with a dataset
nobody designed it around.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _records(path: Path) -> int | None:
    if path.suffix == ".jsonl":
        return sum(1 for line in path.read_text().splitlines() if line.strip())
    if path.name.endswith("_trace.txt"):
        return max(0, len(path.read_text().splitlines()) - 1)
    return None


def entry(path: Path) -> dict:
    out = {
        "path": str(path.relative_to(ROOT)),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }
    count = _records(path)
    if count is not None:
        out["records"] = count
    return out


def collect(patterns: list[tuple[str, str]]) -> dict:
    groups: dict = {}
    for label, pattern in patterns:
        files = sorted(ROOT.glob(pattern))
        groups[label] = {
            "pattern": pattern,
            "files": len(files),
            "totalBytes": sum(f.stat().st_size for f in files),
            "totalRecords": sum(_records(f) or 0 for f in files),
            "entries": [entry(f) for f in files],
        }
    return groups


def corpus_descriptor(manifest: dict, replication: dict | None) -> dict:
    """A native gate descriptor for the corpus itself.

    The conditions are the shape of a real handling rule applied to data that
    carries no restriction, exactly as the pipeline descriptors are. What makes
    them worth writing down is that they are the rules this corpus actually has
    -- a consumer that wants fewer than the full set of replicates is asking
    for a subset the interval was not computed over.
    """
    decisions = manifest["groups"]["gatedDecisions"]["totalRecords"]
    replicates = manifest["groups"]["gatedTraces"]["files"]
    return {
        "datasetId": "gate-decisions",
        "version": "1.0.0",
        "dataType": "admission_decision_records",
        "state": "REPLICATED",
        "schema": {
            "format": "jsonl",
            "layout": "one-record-per-decision",
            "engine": "nextflow-24.10.5",
            "pipeline": "nf-core/demo-1.0.1",
        },
        "provenance": {
            "source": (
                f"{replicates} interleaved replicates of three arms (baseline, gated, "
                "refuse) of nf-core/demo v1.0.1 under a prospective admission gate, "
                "on real nf-core/test-datasets Illumina amplicon reads"
            ),
            "producedBy": "bench/replicate.sh",
            "custodian": "ok-nfcore-admission-gate",
            "retentionDays": 3650,
        },
        "policy": {
            "classification": "public-derived-measurement",
            "rationale": (
                "Timings and decision records over public test data. Nothing here is "
                "restricted; the conditions exist so that a consumer cannot quietly "
                "reuse a subset the published interval was not computed over."
            ),
        },
        "permissibleActions": [
            {
                "name": "analyze",
                "requiresState": ["REPLICATED"],
                "conditions": {
                    "replicates": {"min": replicates},
                    "arm": {"in": ["baseline", "gated", "refuse"]},
                },
            },
            {
                "name": "cite",
                "requiresState": ["REPLICATED", "ARCHIVED"],
                "conditions": {"manifestSha256": {"present": True}},
            },
            {
                "name": "redistribute",
                "requiresState": ["ARCHIVED"],
                "conditions": {"decisionRecords": {"min": decisions}},
            },
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", type=Path, default=ROOT / "dataset")
    args = ap.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    groups = collect([
        ("baselineTraces", "runs/replicates/baseline_*_trace.txt"),
        ("gatedTraces", "runs/replicates/gated_*_trace.txt"),
        ("refuseTraces", "runs/replicates/refuse_*_trace.txt"),
        ("gatedDecisions", "results/replicates/decisions_gated_*.jsonl"),
        ("refuseDecisions", "results/replicates/decisions_refuse_*.jsonl"),
        ("descriptors", "descriptors/*.json"),
        # The run log is provenance rather than measurement, but it is the only
        # evidence that the arms were interleaved rather than blocked, which is
        # a claim the paper makes and a reader would otherwise take on trust.
        ("runLog", "results/replicates/progress.txt"),
    ])

    replication_path = ROOT / "results" / "replication.json"
    replication = json.loads(replication_path.read_text()) if replication_path.exists() else None

    manifest = {
        "corpus": "nf-core admission-gate replication",
        "engine": "nextflow-24.10.5",
        "pipeline": "nf-core/demo-1.0.1",
        "container": "podman, rootless",
        "arms": ["baseline", "gated", "refuse"],
        "groups": groups,
        "totals": {
            "files": sum(g["files"] for g in groups.values()),
            "bytes": sum(g["totalBytes"] for g in groups.values()),
            "decisionRecords": groups["gatedDecisions"]["totalRecords"]
            + groups["refuseDecisions"]["totalRecords"],
        },
    }
    if replication:
        manifest["replicationSummary"] = replication.get("replicates")
        manifest["refusalHeld"] = replication.get("refusalHeld")

    manifest_path = args.outdir / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    native = corpus_descriptor(manifest, replication)
    native_path = args.outdir / "gate-decisions.json"
    native_path.write_text(json.dumps(native, indent=2) + "\n")

    print(f"manifest: {manifest['totals']['files']} files, "
          f"{manifest['totals']['bytes']} bytes, "
          f"{manifest['totals']['decisionRecords']} decision records")
    print(f"wrote {manifest_path}")
    print(f"wrote {native_path}")

    # Optional: describe the corpus with the Croissant policy profile.
    profile_root = os.environ.get("CPOL_ROOT", str(ROOT.parent / "ok-croissant-policy-profile"))
    if (Path(profile_root) / "croissant_policy" / "emit.py").is_file():
        sys.path.insert(0, profile_root)
        from croissant_policy import emit, validate  # noqa: PLC0415

        doc = emit.emit(
            native,
            url="https://github.com/doytsujin/ok-nfcore-admission-gate",
            # The corpus is CC-BY-4.0; the code that made it is Apache-2.0.
            # The document describes the corpus, so it carries the data licence.
            license="https://spdx.org/licenses/CC-BY-4.0.html",
            decision_record="results/replicates",
        )
        report = validate.validate(doc)
        croissant_path = args.outdir / "gate-decisions.croissant.json"
        croissant_path.write_text(json.dumps(doc, indent=2) + "\n")
        print(f"wrote {croissant_path} "
              f"({'conforms' if report.conforms else 'NON-CONFORMING: ' + str(report.errors)})")
    else:
        print(f"croissant_policy not found at {profile_root}; skipping the Croissant document "
              "(set CPOL_ROOT to ok-croissant-policy-profile)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
