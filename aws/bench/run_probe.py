#!/usr/bin/env python3
"""E1 -- does AWS HealthOmics honour `process.beforeScript`?

    python3 aws/bench/run_probe.py --bucket my-omics-bucket --role-arn arn:... --confirm

Runs the two probe workflows and writes a verdict to aws/results/e1_probe.json.
Without --confirm it packages, validates and prints what it would do, and
starts nothing.

Why this is a script and not a paragraph: the claim it tests -- that the
per-task enforcement point does not exist on HealthOmics -- currently rests on
a linter list AWS last edited on 2024-02-21, which is contradicted for at least
one other directive by AWS's own current documentation. A stale list is a
hypothesis. This is the test.
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
from awscli import AwsError, aws  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / "aws" / "workflows"
RESULTS = ROOT / "aws" / "results"

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "DELETED"}


def package(src: Path) -> bytes:
    """Zip a workflow directory the way CreateWorkflow expects it.

    Deterministic member order and a fixed timestamp, so re-packaging the same
    source yields the same bytes and a re-run is a re-run rather than a new
    artifact with a new hash.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            if path.is_file():
                info = zipfile.ZipInfo(str(path.relative_to(src)), date_time=(1980, 1, 1, 0, 0, 0))
                info.external_attr = 0o644 << 16
                zf.writestr(info, path.read_bytes())
    return buf.getvalue()


def create_workflow(name: str, src: Path, region: str, profile: str | None) -> dict:
    """CreateWorkflow, distinguishing 'rejected the definition' from 'failed'.

    A rejection here is itself a result -- it means the unsupported directive
    is caught loudly at authoring time, which is the best of the three possible
    behaviours for an operator and should be recorded, not retried around.
    """
    zip_path = RESULTS / f"{name}.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    zip_path.write_bytes(package(src))

    try:
        wf = aws("omics", "create-workflow",
                 "--name", name,
                 "--engine", "NEXTFLOW",
                 "--definition-zip", f"fileb://{zip_path}",
                 region=region, profile=profile)
    except AwsError as exc:
        return {"outcome": "REJECTED_AT_CREATE",
                "errorCode": exc.error_code,
                "message": exc.stderr[:600]}

    wid = wf["id"]
    # CreateWorkflow returns before the definition is validated; ACTIVE means
    # accepted, FAILED means the service rejected it after the fact. Both are
    # results and neither is an exception.
    for _ in range(60):
        got = aws("omics", "get-workflow", "--id", wid, region=region, profile=profile)
        status = got.get("status")
        if status == "ACTIVE":
            return {"outcome": "ACCEPTED", "workflowId": wid}
        if status in ("FAILED", "DELETED"):
            return {"outcome": "REJECTED_AT_CREATE",
                    "workflowId": wid,
                    "errorCode": status,
                    "message": got.get("statusMessage", "")}
        time.sleep(5)
    return {"outcome": "TIMEOUT_VALIDATING", "workflowId": wid}


def start_and_wait(workflow_id: str, role_arn: str, output_uri: str,
                   region: str, profile: str | None, timeout_s: int = 3600) -> dict:
    run = aws("omics", "start-run",
              "--workflow-id", workflow_id,
              "--role-arn", role_arn,
              "--output-uri", output_uri,
              "--name", f"probe-{workflow_id}",
              region=region, profile=profile)
    rid = run["id"]
    started = time.time()
    while time.time() - started < timeout_s:
        got = aws("omics", "get-run", "--id", rid, region=region, profile=profile)
        if got.get("status") in TERMINAL:
            return got
        time.sleep(15)
    return {"id": rid, "status": "TIMEOUT"}


def read_probe_output(output_uri: str, run_id: str, region: str,
                      profile: str | None) -> str:
    """Fetch probe.out from the run's S3 output.

    Read from S3 rather than from the run log on purpose: the question is what
    the task observed, and the run log is written by the same layer whose
    completeness is under test.
    """
    prefix = f"{output_uri.rstrip('/')}/{run_id}/"
    try:
        listing = aws("s3", "ls", prefix, "--recursive",
                      region=region, profile=profile, parse=False)
    except AwsError:
        return ""
    for line in listing.splitlines():
        if line.strip().endswith("probe.out"):
            key = line.split()[-1]
            bucket = output_uri.split("/", 3)[2]
            dest = RESULTS / f"{run_id}_probe.out"
            aws("s3", "cp", f"s3://{bucket}/{key}", str(dest),
                region=region, profile=profile, parse=False)
            return dest.read_text()
    return ""


def verdict(observe: dict, enforce: dict) -> dict:
    """Turn two run outcomes into the one sentence the paper needs.

    Deliberately enumerates the case where the claim is refuted, and says so in
    those words, so that a refuting result cannot be quietly reported as a
    confirming one.
    """
    o_out = (observe.get("probeOutput") or "").strip().splitlines()
    o_first = o_out[0] if o_out else ""

    if observe.get("outcome") == "REJECTED_AT_CREATE":
        return {
            "beforeScript": "REJECTED",
            "perTaskEnforcement": "UNAVAILABLE",
            "claim": "SUPPORTED",
            "statement": (
                "HealthOmics rejects a workflow definition containing "
                "beforeScript at CreateWorkflow. The per-task enforcement point "
                "is unavailable, and its absence is loud rather than silent -- "
                "the best of the three possible service behaviours."),
        }
    if o_first == "DROPPED":
        return {
            "beforeScript": "SILENTLY_DROPPED",
            "perTaskEnforcement": "UNAVAILABLE",
            "claim": "SUPPORTED",
            "statement": (
                "HealthOmics accepts a workflow declaring beforeScript and does "
                "not execute it. The per-task enforcement point is unavailable "
                "and its absence is silent: a gated definition and an ungated "
                "one produce identical runs, so a decision log proves nothing "
                "about what was checked."),
        }
    if o_first == "EXECUTED" and enforce.get("runStatus") == "FAILED":
        return {
            "beforeScript": "HONOURED",
            "perTaskEnforcement": "AVAILABLE",
            "claim": "REFUTED",
            "statement": (
                "HealthOmics executes beforeScript and fails the task on a "
                "non-zero exit. Per-task admission control IS available on the "
                "managed service; the local gate ports across unchanged and the "
                "'managed provenance or per-task enforcement, not both' "
                "trade-off does not hold."),
        }
    if o_first == "EXECUTED":
        return {
            "beforeScript": "EXECUTED_EXIT_DISCARDED",
            "perTaskEnforcement": "UNSOUND",
            "claim": "SUPPORTED_WITH_A_WORSE_FINDING",
            "statement": (
                "HealthOmics executes beforeScript but discards its exit "
                "status. The hook runs and cannot refuse -- side effects "
                "without enforcement, which is worse than no hook at all "
                "because the gate appears to be present."),
        }
    return {
        "beforeScript": "INCONCLUSIVE",
        "perTaskEnforcement": "UNKNOWN",
        "claim": "UNTESTED",
        "statement": "The probe did not produce a readable verdict; see the raw outcomes.",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", help="s3 bucket for run output, e.g. my-omics-bucket")
    ap.add_argument("--prefix", default="nfgate/e1")
    ap.add_argument("--role-arn", help="HealthOmics service role for the run")
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    ap.add_argument("--confirm", action="store_true",
                    help="actually create workflows and start runs (costs money)")
    args = ap.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)

    if not args.confirm:
        print("dry run -- packaging only, nothing created, nothing charged\n")
        for name in ("probe-beforescript-observe", "probe-beforescript-enforce"):
            blob = package(WORKFLOWS / name)
            print(f"  {name}: {len(blob)} bytes")
        print("\nre-run with --confirm --bucket ... --role-arn ... to execute")
        return 0

    if not (args.bucket and args.role_arn):
        print("--confirm needs --bucket and --role-arn", file=sys.stderr)
        return 2

    output_uri = f"s3://{args.bucket}/{args.prefix}"
    result: dict = {"region": args.region, "outputUri": output_uri,
                    "pricesAndRulesReadOn": "2026-08-24"}

    # E1a -- observation. Always completes, always yields a verdict.
    obs = create_workflow("nfgate-probe-observe", WORKFLOWS / "probe-beforescript-observe",
                          args.region, args.profile)
    if obs["outcome"] == "ACCEPTED":
        run = start_and_wait(obs["workflowId"], args.role_arn, output_uri,
                             args.region, args.profile)
        obs["runId"] = run.get("id")
        obs["runStatus"] = run.get("status")
        obs["statusMessage"] = run.get("statusMessage", "")
        obs["probeOutput"] = read_probe_output(output_uri, run.get("id", ""),
                                               args.region, args.profile)
    result["e1a_observe"] = obs

    # E1b -- enforcement. Only informative once E1a says the directive runs,
    # but it is cheap and its result is recorded either way.
    enf = create_workflow("nfgate-probe-enforce", WORKFLOWS / "probe-beforescript-enforce",
                          args.region, args.profile)
    if enf["outcome"] == "ACCEPTED":
        run = start_and_wait(enf["workflowId"], args.role_arn, output_uri,
                             args.region, args.profile)
        enf["runId"] = run.get("id")
        enf["runStatus"] = run.get("status")
        enf["statusMessage"] = run.get("statusMessage", "")
    result["e1b_enforce"] = enf

    result["verdict"] = verdict(obs, enf)

    out = RESULTS / "e1_probe.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["verdict"], indent=2))
    print(f"\nwritten {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
