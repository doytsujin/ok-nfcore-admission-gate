#!/usr/bin/env python3
"""Emit a Workflow Run RO-Crate from a real Nextflow run, with the gate's
decision records attached.

Two things are being joined here, and the distinction is the point of the whole
artifact:

  * Nextflow's trace is *retrospective* -- it records what ran, after it ran.
    Workflow Run RO-Crate standardises that record.
  * The gate's decision log is *prospective* -- each entry was written before
    its task's script, and a REFUSE entry corresponds to work that never
    happened.

A retrospective provenance format has no native slot for "this was refused",
because a run record describes actions. The refusals are therefore attached as
`ControlAction` entities alongside the `CreateAction` entities that WRROC uses
for executed steps, so a reader can see both what ran and what was stopped in
one crate.

Conforms to the Workflow Run Crate profile shape (RO-Crate 1.1 metadata
descriptor + prov entities). It is deliberately hand-built rather than emitted
by a plugin, so the mapping from decision record to provenance entity is
visible and reviewable.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RO_CRATE_CONTEXT = "https://w3id.org/ro/crate/1.1/context"
WORKFLOW_RUN_CRATE = "https://w3id.org/ro/wfrun/workflow/0.5"
PROCESS_RUN_CRATE = "https://w3id.org/ro/wfrun/process/0.5"


def read_trace(path: Path) -> list[dict]:
    lines = path.read_text().splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    return [
        dict(zip(header, line.split("\t")))
        for line in lines[1:]
        if line.strip()
    ]


def read_decisions(path: Path | None) -> list[dict]:
    if not path or not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def build(trace: list[dict], decisions: list[dict], workflow_name: str,
          workflow_version: str) -> dict:
    graph: list[dict] = [
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "conformsTo": {"@id": RO_CRATE_CONTEXT.replace("/context", "")},
            "about": {"@id": "./"},
        },
        {
            "@id": "./",
            "@type": "Dataset",
            "name": f"Gated run of {workflow_name}",
            "description": (
                "Workflow Run RO-Crate for a real nf-core execution, extended "
                "with prospective admission decisions recorded before each task."
            ),
            "conformsTo": [
                {"@id": WORKFLOW_RUN_CRATE},
                {"@id": PROCESS_RUN_CRATE},
            ],
            "mentions": [{"@id": "#run"}],
            "hasPart": [{"@id": "workflow.nf"}],
        },
        {
            "@id": WORKFLOW_RUN_CRATE,
            "@type": "CreativeWork",
            "name": "Workflow Run Crate",
            "version": "0.5",
        },
        {
            "@id": PROCESS_RUN_CRATE,
            "@type": "CreativeWork",
            "name": "Process Run Crate",
            "version": "0.5",
        },
        {
            "@id": "workflow.nf",
            "@type": ["File", "SoftwareSourceCode", "ComputationalWorkflow"],
            "name": workflow_name,
            "version": workflow_version,
            "programmingLanguage": {"@id": "#nextflow"},
        },
        {
            "@id": "#nextflow",
            "@type": "ComputerLanguage",
            "name": "Nextflow",
            "url": "https://www.nextflow.io/",
        },
    ]

    executed_ids = []
    for row in trace:
        task_id = row.get("task_id", "")
        name = row.get("name", "")
        node = {
            "@id": f"#task-{task_id}",
            "@type": "CreateAction",
            "name": name,
            "actionStatus": (
                "http://schema.org/CompletedActionStatus"
                if row.get("status") == "COMPLETED"
                else "http://schema.org/FailedActionStatus"
            ),
            "startTime": row.get("submit", ""),
            "endTime": row.get("complete", ""),
            "nfExitStatus": row.get("exit", ""),
            "nfDuration": row.get("duration", ""),
            "nfRealtime": row.get("realtime", ""),
            "nfHash": row.get("hash", ""),
        }
        graph.append(node)
        executed_ids.append({"@id": node["@id"]})

    # Prospective decisions. A PERMIT is an authorisation that preceded a
    # CreateAction; a REFUSE has no CreateAction at all, which is exactly the
    # information a retrospective-only crate cannot carry.
    decision_ids = []
    for i, rec in enumerate(decisions):
        node = {
            "@id": f"#decision-{i}",
            "@type": "ControlAction",
            "name": f"{rec['verdict']} {rec['datasetId']}:{rec['action']}",
            "actionStatus": (
                "http://schema.org/CompletedActionStatus"
                if rec["verdict"] == "PERMIT"
                else "http://schema.org/FailedActionStatus"
            ),
            "startTime": rec.get("timestamp", ""),
            "gateVerdict": rec["verdict"],
            "gateDataset": rec["datasetId"],
            "gateDescriptorVersion": rec["descriptorVersion"],
            "gateAction": rec["action"],
            "gateObservedState": rec.get("observedState", ""),
            "gateReasonClass": rec.get("reasonClass"),
            "gateReasons": rec.get("reasons", []),
            "gateConditionsChecked": rec.get("conditionsChecked", []),
            "gateEvalMicros": rec.get("evalMicros"),
        }
        graph.append(node)
        decision_ids.append({"@id": node["@id"]})

    graph.append({
        "@id": "#run",
        "@type": "CreateAction",
        "name": f"{workflow_name} run",
        "instrument": {"@id": "workflow.nf"},
        "object": decision_ids,
        "result": executed_ids,
        "description": (
            f"{len(executed_ids)} executed task(s); "
            f"{sum(1 for d in decisions if d['verdict'] == 'PERMIT')} permitted, "
            f"{sum(1 for d in decisions if d['verdict'] == 'REFUSE')} refused."
        ),
    })

    return {"@context": RO_CRATE_CONTEXT, "@graph": graph}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True, type=Path)
    ap.add_argument("--decisions", type=Path, default=None)
    ap.add_argument("--workflow-name", default="nf-core/demo")
    ap.add_argument("--workflow-version", default="1.0.1")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    crate = build(
        read_trace(args.trace),
        read_decisions(args.decisions),
        args.workflow_name,
        args.workflow_version,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(crate, indent=2) + "\n")

    entities = len(crate["@graph"])
    refused = sum(
        1 for n in crate["@graph"]
        if n.get("@type") == "ControlAction" and n.get("gateVerdict") == "REFUSE"
    )
    print(f"wrote {args.out} -- {entities} entities, {refused} refusal(s) recorded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
