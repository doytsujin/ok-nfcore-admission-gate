#!/usr/bin/env python3
"""E3 -- what whole-run granularity costs.

    python3 aws/bench/run_arm.py --bucket B --role-arn R --reps 30 --confirm

The local artifact refuses SEQTK_TRIM on `minReadLength = 10` while FASTQC
completes for every sample: permitted work proceeds, forbidden work does not.
`omics:StartRun` cannot express that. It has two branches and this measures
both:

    permit  the run starts; the forbidden trim executes along with everything
            else.        cost = vCPU-seconds of forbidden work admitted
    refuse  the run never starts; the permitted QC does not happen either.
            cost = vCPU-seconds of permitted work forbidden

Neither number is available from a design document, which is why this exists.

Arms are interleaved rather than blocked, and paired by replicate index, for
the same reason bench/replicate.sh does it locally: state that drifts over the
hour should land on every arm equally.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from awscli import AwsError, aws  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "aws" / "results"
PIPELINE = ROOT / "pipeline-nfcore-demo"
OMICS_CONF = ROOT / "aws" / "workflows" / "demo" / "omics.config"

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "DELETED"}

# The guard AWS documents for keeping a pipeline portable: the HealthOmics
# config is included only when the engine sets AWS_WORKFLOW_RUN, so the
# packaged copy still runs locally and the vendored tree is never edited.
INCLUDE_GUARD = """

// Appended at packaging time by aws/bench/run_arm.py -- not present in the
// vendored pipeline, which stays byte-identical to nf-core/demo 1.0.1.
if (System.getenv('AWS_WORKFLOW_RUN')) {
    includeConfig 'conf/omics.config'
}
"""


def package_demo(ecr_base: str) -> bytes:
    """Zip nf-core/demo with the HealthOmics config layered on top.

    The pipeline on disk is not modified. Everything HealthOmics-specific is
    added to the in-zip copy, so `git status` stays clean and the artifact's
    claim to be running stock nf-core/demo 1.0.1 stays true.
    """
    conf = OMICS_CONF.read_text().replace("__ECR_BASE__", ecr_base)
    skip = {".git", "work", ".nextflow"}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(PIPELINE.rglob("*")):
            rel = path.relative_to(PIPELINE)
            if any(part in skip for part in rel.parts):
                continue
            if not path.is_file():
                continue
            info = zipfile.ZipInfo(str(rel), date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            body = path.read_bytes()
            if str(rel) == "nextflow.config":
                body = body + INCLUDE_GUARD.encode()
            zf.writestr(info, body)
        zf.writestr(zipfile.ZipInfo("conf/omics.config", date_time=(1980, 1, 1, 0, 0, 0)),
                    conf)
    return buf.getvalue()


def decidability_check() -> dict:
    """Is this policy actually undecidable at StartRun?

    EXPERIMENTS.md commits to checking this rather than assuming it. If every
    condition on the `trim` action is a run parameter, whole-run granularity is
    sufficient *for this example* and the example is the wrong one -- the
    general argument would still hold, but this artifact would not be
    demonstrating it.
    """
    from gate.descriptor import Descriptor

    d = Descriptor.load(ROOT / "descriptors" / "raw-reads.json")
    trim = d.action("trim")
    conditions = sorted(trim.conditions) if trim else []

    # Run parameters are fixed in the StartRun request. Anything else has to be
    # observed from the run's own intermediate state, which by definition does
    # not exist yet when StartRun is called.
    run_parameters = {"platform", "input", "outdir"}
    undecidable = [c for c in conditions if c not in run_parameters]

    return {
        "conditionsOnTrim": conditions,
        "knownAtStartRun": [c for c in conditions if c in run_parameters],
        "notKnownAtStartRun": undecidable,
        "startRunSufficient": not undecidable,
        "note": (
            "minReadLength is a property of the trimming step's own "
            "configuration and of the reads as they exist after QC. It is "
            "supplied per-task locally. If it were hoisted into the run "
            "parameters the example would become decidable at StartRun and a "
            "different condition -- one on an intermediate dataset's state -- "
            "would be needed to make the point."),
    }


def invoke_gate(payload: dict, region: str, profile: str | None) -> dict:
    """Call the gate Lambda and return its decision."""
    req = RESULTS / "_gate_request.json"
    res = RESULTS / "_gate_response.json"
    req.write_text(json.dumps(payload))
    aws("lambda", "invoke",
        "--function-name", "nfgate-startrun-gate",
        "--payload", f"fileb://{req}",
        "--cli-read-timeout", "120",
        str(res), region=region, profile=profile)
    return json.loads(res.read_text())


def wait_for_run(run_id: str, region: str, profile: str | None,
                 timeout_s: int = 3600) -> dict:
    started = time.time()
    while time.time() - started < timeout_s:
        got = aws("omics", "get-run", "--id", run_id, region=region, profile=profile)
        if got.get("status") in TERMINAL:
            return got
        time.sleep(15)
    return {"id": run_id, "status": "TIMEOUT"}


def run_tasks(run_id: str, region: str, profile: str | None) -> list[dict]:
    """Per-task records, which is where the vCPU-seconds come from."""
    out = aws("omics", "list-run-tasks", "--id", run_id, region=region, profile=profile)
    tasks = []
    for t in out.get("items", []):
        detail = aws("omics", "get-run-task", "--id", run_id,
                     "--task-id", t["taskId"], region=region, profile=profile)
        tasks.append(detail)
    return tasks


def vcpu_seconds(tasks: list[dict]) -> float:
    """Billable-shaped compute: cpus x wall seconds, summed over tasks.

    Not the invoice -- HealthOmics bills whole instances with minimums, and
    this deliberately does not model that. It is the quantity the granularity
    argument is about: how much work ran that should not have, or did not run
    that should have.
    """
    total = 0.0
    for t in tasks:
        start, stop = t.get("startTime"), t.get("stopTime")
        cpus = float(t.get("cpus") or 0)
        if not (start and stop and cpus):
            continue
        from datetime import datetime
        fmt = "%Y-%m-%dT%H:%M:%S.%f%z"
        try:
            a = datetime.strptime(start.replace("Z", "+0000"), fmt)
            b = datetime.strptime(stop.replace("Z", "+0000"), fmt)
        except ValueError:
            continue
        total += cpus * (b - a).total_seconds()
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket")
    ap.add_argument("--prefix", default="nfgate/e3")
    ap.add_argument("--role-arn")
    ap.add_argument("--reps", type=int, default=30)
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)

    dec = decidability_check()
    print("== is StartRun granularity sufficient for this policy? ==")
    print(json.dumps(dec, indent=2))
    if dec["startRunSufficient"]:
        print("\nSTOP: every condition on `trim` is known at StartRun. This "
              "example does not demonstrate the granularity gap; pick a "
              "condition on an intermediate dataset's state instead.")
        return 1
    print()

    if not args.confirm:
        blob = package_demo("ACCOUNT.dkr.ecr.REGION.amazonaws.com")
        print(f"dry run -- demo package is {len(blob)} bytes, nothing started")
        print("re-run with --confirm --bucket ... --role-arn ... to execute")
        return 0

    if not (args.bucket and args.role_arn):
        print("--confirm needs --bucket and --role-arn", file=sys.stderr)
        return 2

    account = aws("sts", "get-caller-identity", region=args.region,
                  profile=args.profile)["Account"]
    ecr_base = f"{account}.dkr.ecr.{args.region}.amazonaws.com"
    output_uri = f"s3://{args.bucket}/{args.prefix}"

    zip_path = RESULTS / "demo-healthomics.zip"
    zip_path.write_bytes(package_demo(ecr_base))
    wf = aws("omics", "create-workflow", "--name", "nfgate-demo",
             "--engine", "NEXTFLOW", "--definition-zip", f"fileb://{zip_path}",
             region=args.region, profile=args.profile)
    workflow_id = wf["id"]
    print(f"workflow {workflow_id} created; waiting for validation")
    for _ in range(60):
        got = aws("omics", "get-workflow", "--id", workflow_id,
                  region=args.region, profile=args.profile)
        if got.get("status") == "ACTIVE":
            break
        if got.get("status") in ("FAILED", "DELETED"):
            print(f"workflow rejected: {got.get('statusMessage')}", file=sys.stderr)
            return 1
        time.sleep(5)

    records = []
    for i in range(1, args.reps + 1):
        idx = f"{i:02d}"
        # Interleaved, not blocked -- replicate i of each arm before i+1.
        for arm, minlen in (("permit", 30), ("refuse", 10)):
            payload = {
                "dataset": "raw-reads",
                "action": "trim",
                "context": {"platform": "illumina", "minReadLength": minlen},
                "workflowId": workflow_id,
                "roleArn": args.role_arn,
                "outputUri": output_uri,
                "name": f"nfgate-{arm}-{idx}",
            }
            t0 = time.time()
            resp = invoke_gate(payload, args.region, args.profile)
            gate_wall_ms = (time.time() - t0) * 1000.0

            rec = {
                "replicate": i,
                "arm": arm,
                "permitted": resp.get("permitted"),
                "gateWallMs": gate_wall_ms,
                "decision": resp.get("decision", {}),
            }
            if resp.get("permitted") and resp.get("runId"):
                run = wait_for_run(resp["runId"], args.region, args.profile)
                tasks = run_tasks(resp["runId"], args.region, args.profile)
                rec["runId"] = resp["runId"]
                rec["runStatus"] = run.get("status")
                rec["taskCount"] = len(tasks)
                rec["vcpuSeconds"] = vcpu_seconds(tasks)
                rec["tasks"] = [
                    {"name": t.get("name"), "status": t.get("status"),
                     "cpus": t.get("cpus"), "memory": t.get("memory"),
                     "startTime": t.get("startTime"), "stopTime": t.get("stopTime")}
                    for t in tasks
                ]
            else:
                # The refusal is the measurement: no run, no tasks, no compute.
                rec["runId"] = None
                rec["runStatus"] = "NEVER_STARTED"
                rec["taskCount"] = 0
                rec["vcpuSeconds"] = 0.0
            records.append(rec)
            print(f"   {arm}_{idx}  permitted={rec['permitted']} "
                  f"tasks={rec['taskCount']} vcpu_s={rec['vcpuSeconds']:.1f}")

            out = RESULTS / "e3_runs.jsonl"
            with out.open("a") as fh:
                fh.write(json.dumps(rec) + "\n")

    meta = RESULTS / "e3_meta.json"
    meta.write_text(json.dumps({
        "workflowId": workflow_id,
        "region": args.region,
        "reps": args.reps,
        "decidability": dec,
    }, indent=2) + "\n")
    print(f"\nwritten {RESULTS / 'e3_runs.jsonl'} and {meta}")
    print("now: python3 aws/bench/aggregate_aws.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
