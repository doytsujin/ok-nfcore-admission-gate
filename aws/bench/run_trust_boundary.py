#!/usr/bin/env python3
"""E2 -- who does the gate protect?

    python3 aws/bench/run_trust_boundary.py --role-arn RUN_ROLE --approved WF --other WF --confirm

The `beforeScript` gate lives inside the workflow bundle **the caller
supplies** and runs in the image **the caller chooses**. It therefore protects
a caller from their own pipeline. Whether it can be enforced *against* that
caller is a different question, and it is the only research question left in
this line.

The obvious closure is IAM: restrict `omics:StartRun` to an allowlist of
approved workflow ARNs, so a caller who writes their own ungated definition
cannot start it. That is either supported at resource level or it is not, and
AWS's documentation is not evidence about AWS's behaviour -- see
aws/audit/RESULTS.md. So it is tested.

Four checks, run under a *separate* test role rather than the calling user, so
a Deny cannot lock this account out of HealthOmics:

    1. approved workflow  -> StartRun ALLOWED
    2. other workflow     -> StartRun DENIED
    3. caller can still CreateWorkflow (they own the bundle -- expected)
    4. caller cannot start the workflow they just created

Check 4 is the one that matters. If it passes, the gate is enforceable against
the caller and the trust-boundary objection is answered by configuration
rather than by architecture.
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
RESULTS = ROOT / "aws" / "results"
TEST_ROLE = "nfgate-caller-test"


def ensure_role(account: str, region: str, profile: str, approved_wf: str,
                run_role_arn: str) -> str:
    """A caller role allowed to start ONLY the approved workflow."""
    trust = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": f"arn:aws:iam::{account}:root"},
            "Action": "sts:AssumeRole",
        }],
    }
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "StartOnlyApprovedWorkflows",
                "Effect": "Allow",
                "Action": "omics:StartRun",
                "Resource": [
                    f"arn:aws:omics:{region}:{account}:workflow/{approved_wf}",
                    f"arn:aws:omics:{region}:{account}:run/*",
                ],
            },
            {
                "Sid": "ObserveAndAuthor",
                "Effect": "Allow",
                "Action": ["omics:GetRun", "omics:ListRuns", "omics:GetWorkflow",
                           "omics:ListWorkflows", "omics:CreateWorkflow",
                           "omics:DeleteWorkflow", "omics:TagResource"],
                "Resource": "*",
            },
            {
                "Sid": "PassTheRunRole",
                "Effect": "Allow",
                "Action": "iam:PassRole",
                "Resource": run_role_arn,
                "Condition": {"StringEquals": {"iam:PassedToService": "omics.amazonaws.com"}},
            },
        ],
    }
    try:
        aws("iam", "get-role", "--role-name", TEST_ROLE, profile=profile)
    except AwsError:
        aws("iam", "create-role", "--role-name", TEST_ROLE,
            "--assume-role-policy-document", json.dumps(trust), profile=profile)
    aws("iam", "put-role-policy", "--role-name", TEST_ROLE,
        "--policy-name", f"{TEST_ROLE}-policy",
        "--policy-document", json.dumps(policy), profile=profile)
    return f"arn:aws:iam::{account}:role/{TEST_ROLE}"


def assume(role_arn: str, region: str, profile: str) -> dict:
    d = aws("sts", "assume-role", "--role-arn", role_arn,
            "--role-session-name", "nfgate-trust-test",
            region=region, profile=profile)["Credentials"]
    return {
        "AWS_ACCESS_KEY_ID": d["AccessKeyId"],
        "AWS_SECRET_ACCESS_KEY": d["SecretAccessKey"],
        "AWS_SESSION_TOKEN": d["SessionToken"],
    }


def as_role(env: dict, *args_, region: str):
    """Run one aws call under the assumed role's credentials."""
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    os.environ.pop("AWS_PROFILE", None)
    try:
        return aws(*args_, region=region)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def try_start(env: dict, wf: str, run_role: str, output_uri: str,
              region: str, label: str) -> dict:
    try:
        r = as_role(env, "omics", "start-run", "--workflow-id", wf,
                    "--role-arn", run_role, "--output-uri", output_uri,
                    "--name", f"trust-{label}", region=region)
        return {"allowed": True, "runId": r.get("id")}
    except AwsError as exc:
        return {"allowed": False, "errorCode": exc.error_code,
                "message": exc.stderr[:220]}


def minimal_workflow_zip() -> bytes:
    body = """nextflow.enable.dsl = 2
process UNGATED {
    cpus 2
    memory '4 GB'
    output:
    path 'out.txt'
    script:
    \"\"\"
    echo "no gate here" > out.txt
    \"\"\"
}
workflow { UNGATED() }
"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo("main.nf", date_time=(1980, 1, 1, 0, 0, 0)), body)
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--approved", required=True, help="workflow id the caller may start")
    ap.add_argument("--other", required=True, help="workflow id the caller may not start")
    ap.add_argument("--role-arn", required=True, help="HealthOmics run role")
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--prefix", default="nfgate/trust")
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    account = aws("sts", "get-caller-identity", region=args.region,
                  profile=args.profile)["Account"]
    if not args.confirm:
        print(f"dry run -- would create role {TEST_ROLE} in {account}, start 2 runs")
        return 0

    role_arn = ensure_role(account, args.region, args.profile, args.approved, args.role_arn)
    print(f"caller role: {role_arn}")
    # IAM is eventually consistent; a fresh role's policy is not instantly live.
    time.sleep(15)
    env = assume(role_arn, args.region, args.profile)
    output_uri = f"s3://{args.bucket}/{args.prefix}"

    out = {"account": account, "approvedWorkflow": args.approved,
           "otherWorkflow": args.other, "checks": {}}

    out["checks"]["1_approved_allowed"] = try_start(
        env, args.approved, args.role_arn, output_uri, args.region, "approved")
    out["checks"]["2_other_denied"] = try_start(
        env, args.other, args.role_arn, output_uri, args.region, "other")

    # 3 -- the caller owns the bundle, so authoring must remain possible.
    zip_path = RESULTS / "ungated.zip"
    zip_path.write_bytes(minimal_workflow_zip())
    try:
        wf = as_role(env, "omics", "create-workflow", "--name", "nfgate-caller-ungated",
                     "--engine", "NEXTFLOW", "--definition-zip", f"fileb://{zip_path}",
                     region=args.region)
        out["checks"]["3_caller_can_author"] = {"allowed": True, "workflowId": wf["id"]}
        own = wf["id"]
    except AwsError as exc:
        out["checks"]["3_caller_can_author"] = {"allowed": False, "errorCode": exc.error_code}
        own = None

    # 4 -- and cannot run what they authored.
    if own:
        for _ in range(60):
            g = aws("omics", "get-workflow", "--id", own, region=args.region,
                    profile=args.profile)
            if g.get("status") in ("ACTIVE", "FAILED", "DELETED"):
                break
            time.sleep(5)
        out["checks"]["4_own_workflow_denied"] = try_start(
            env, own, args.role_arn, output_uri, args.region, "own")

    c = out["checks"]
    closed = (c.get("1_approved_allowed", {}).get("allowed") is True
              and c.get("2_other_denied", {}).get("allowed") is False
              and c.get("4_own_workflow_denied", {}).get("allowed") is False)
    out["boundaryClosable"] = closed
    out["reading"] = (
        "omics:StartRun honours resource-level restriction to an approved "
        "workflow. A caller can author an ungated definition and cannot start "
        "it, so the gate IS enforceable against the caller by configuration."
        if closed else
        "Resource-level restriction did not behave as required; see the checks. "
        "The trust-boundary objection stands.")

    p = RESULTS / "trust_boundary.json"
    p.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(c, indent=2))
    print("\n" + out["reading"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
