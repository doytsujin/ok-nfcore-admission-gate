#!/usr/bin/env python3
"""The real gate, per task, on HealthOmics.

    python3 aws/bench/run_gate_real.py --bucket B --role-arn R --image I --confirm

Ships `gate/` and `descriptors/` from this repository inside the workflow
bundle and invokes the gate from `beforeScript`, unchanged in logic. Two arms:

    permit   minReadLength=30  -- both tasks admitted, run completes
    refuse   minReadLength=10  -- QC admitted, TRIM refused

The refuse arm is the one that matters. If QC completes and TRIM never starts,
per-task admission control is demonstrated on the managed service: permitted
work proceeded and forbidden work did not, in the same run. A StartRun-level
gate cannot produce that outcome.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from awscli import AwsError, aws  # noqa: E402
from run_probe import RESULTS, TERMINAL, create_workflow  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / "aws" / "workflows" / "gate-real"


def package_with_gate() -> bytes:
    """Bundle = workflow + gate/ + descriptors/, all from this repository.

    Staged through a temp dir rather than assembled by hand so that what ships
    is provably a copy of the tracked source: no edited-for-cloud variant of the
    gate can creep in and quietly make the result not about this artifact.
    """
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        shutil.copy(WF / "main.nf", stage / "main.nf")
        shutil.copy(WF / "nextflow.config", stage / "nextflow.config")
        shutil.copytree(ROOT / "gate", stage / "gate",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(ROOT / "descriptors", stage / "descriptors")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    info = zipfile.ZipInfo(str(path.relative_to(stage)),
                                           date_time=(1980, 1, 1, 0, 0, 0))
                    info.external_attr = 0o644 << 16
                    zf.writestr(info, path.read_bytes())
        return buf.getvalue()


def wait(run_id: str, region: str, profile: str | None) -> dict:
    for _ in range(240):
        got = aws("omics", "get-run", "--id", run_id, region=region, profile=profile)
        if got.get("status") in TERMINAL:
            return got
        time.sleep(15)
    return {"id": run_id, "status": "TIMEOUT"}


def tasks_of(run_id: str, region: str, profile: str | None) -> list[dict]:
    out = aws("omics", "list-run-tasks", "--id", run_id, region=region, profile=profile)
    return [{"taskId": t.get("taskId"), "name": t.get("name"), "status": t.get("status")}
            for t in out.get("items", [])]


def task_log(run_id: str, task_id: str, region: str, profile: str | None) -> list[str]:
    """Read a task's log. --start-from-head matters: without it the API can
    return an empty page for a short-lived task, which reads as 'no evidence'
    when the evidence is there."""
    try:
        d = aws("logs", "get-log-events",
                "--log-group-name", "/aws/omics/WorkflowLog",
                "--log-stream-name", f"run/{run_id}/task/{task_id}",
                "--start-from-head",
                region=region, profile=profile)
    except AwsError:
        return []
    return [e.get("message", "") for e in d.get("events", [])]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--prefix", default="nfgate/gate-real")
    ap.add_argument("--role-arn", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    blob = package_with_gate()
    if not args.confirm:
        print(f"dry run -- bundle is {len(blob)} bytes (workflow + gate/ + descriptors/)")
        return 0

    zip_path = RESULTS / "gate-real.zip"
    zip_path.write_bytes(blob)
    rec = create_workflow("nfgate-gate-real", WF, args.region, args.profile)
    # create_workflow packages the workflow dir only; re-create from the full
    # bundle instead. Kept explicit rather than refactored, because the two
    # packagings are genuinely different and collapsing them would hide that.
    if rec.get("workflowId"):
        aws("omics", "delete-workflow", "--id", rec["workflowId"],
            region=args.region, profile=args.profile)
    wf = aws("omics", "create-workflow", "--name", "nfgate-gate-real",
             "--engine", "NEXTFLOW", "--definition-zip", f"fileb://{zip_path}",
             region=args.region, profile=args.profile)
    workflow_id = wf["id"]
    for _ in range(60):
        got = aws("omics", "get-workflow", "--id", workflow_id,
                  region=args.region, profile=args.profile)
        if got.get("status") == "ACTIVE":
            break
        if got.get("status") in ("FAILED", "DELETED"):
            print(f"workflow rejected: {got.get('statusMessage')}", file=sys.stderr)
            return 1
        time.sleep(5)

    result = {"workflowId": workflow_id, "image": args.image, "arms": {}}
    output_uri = f"s3://{args.bucket}/{args.prefix}"

    for arm, minlen in (("permit", 30), ("refuse", 10)):
        params = RESULTS / f"_params_{arm}.json"
        params.write_text(json.dumps({
            "image": args.image, "minReadLength": minlen, "runLabel": arm,
        }))
        run = aws("omics", "start-run", "--workflow-id", workflow_id,
                  "--role-arn", args.role_arn,
                  "--output-uri", f"{output_uri}/{arm}",
                  "--name", f"nfgate-gate-real-{arm}",
                  "--parameters", f"file://{params}",
                  region=args.region, profile=args.profile)
        done = wait(run["id"], args.region, args.profile)
        tl = tasks_of(run["id"], args.region, args.profile)
        for t in tl:
            t["log"] = task_log(run["id"], t["taskId"], args.region, args.profile)
        result["arms"][arm] = {
            "minReadLength": minlen,
            "runId": run["id"],
            "runStatus": done.get("status"),
            "engineVersion": done.get("engineVersion"),
            "statusMessage": done.get("statusMessage", ""),
            "tasks": tl,
        }
        names = {t["name"]: t["status"] for t in tl}
        print(f"  {arm}: run {done.get('status')}  tasks={names}")

    # The claim, checked rather than narrated.
    r = result["arms"].get("refuse", {})
    names = {t["name"]: t["status"] for t in r.get("tasks", [])}
    qc_ok = names.get("GATED_QC") == "COMPLETED"
    trim_absent_or_failed = names.get("GATED_TRIM") in (None, "FAILED", "CANCELLED")
    result["perTaskGranularityDemonstrated"] = bool(qc_ok and trim_absent_or_failed)
    result["reading"] = (
        "In the refuse arm the permitted task completed and the refused task did "
        "not run. Per-task admission control works on HealthOmics."
        if result["perTaskGranularityDemonstrated"] else
        "Not demonstrated -- see the task table before claiming anything.")

    out = RESULTS / "gate_real.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print("\n" + result["reading"])
    print(f"written {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
