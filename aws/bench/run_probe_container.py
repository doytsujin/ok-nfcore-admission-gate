#!/usr/bin/env python3
"""E1c/E1d -- the containerised case.

    python3 aws/bench/run_probe_container.py --bucket B --role-arn R \
        --image ACCOUNT.dkr.ecr.REGION.amazonaws.com/nfgate/probe:py312-alpine --confirm

E1 answered the question for a task declaring no container, which HealthOmics
runs in a default image of its own. The gate runs on tasks that declare one,
and that raises a second question the first result cannot settle: *where* does
`beforeScript` execute -- inside the declared image, or outside it in the
engine's wrapper? That decides whether the gate's interpreter and code are
reachable from the point the decision is made.

The image is Debian-based precisely so the answer is unambiguous: `os_id=debian`
means inside, anything else means outside.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from awscli import aws  # noqa: E402
from run_probe import (RESULTS, WORKFLOWS, create_workflow, package,  # noqa: E402
                       read_probe_output, start_and_wait)


def parse_witness(text: str) -> dict:
    """Flatten the probe's key=value output into a dict."""
    out = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("=="):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def verdict(obs: dict, enf: dict) -> dict:
    w = parse_witness(obs.get("probeOutput", ""))
    ran = w.get("ran")
    where = None
    if w.get("os_id"):
        where = "INSIDE_DECLARED_CONTAINER" if w["os_id"] == "debian" else "OUTSIDE_CONTAINER"

    if ran != "yes":
        return {
            "beforeScriptWithContainer": "DROPPED",
            "gatePortsToHealthOmics": False,
            "statement": (
                "HealthOmics executes beforeScript for a task with no container "
                "directive but drops it when one is declared. The gate does NOT "
                "port to HealthOmics for real containerised pipelines, and the "
                "E1 result must be restated as applying only to the default "
                "container."),
        }

    enforced = enf.get("runStatus") == "FAILED"
    reachable = w.get("bin_on_path", "none") != "none"
    py = w.get("python3", "none") != "none"

    return {
        "beforeScriptWithContainer": "EXECUTED",
        "executionContext": where,
        "nonZeroExitStopsTask": enforced,
        "bundleBinReachable": reachable,
        "python3Available": py,
        "gateDeliverable": bool(reachable or py),
        "gatePortsToHealthOmics": bool(enforced and (reachable or py)),
        "witness": w,
        "statement": (
            f"beforeScript runs for containerised tasks, "
            f"{'inside' if where == 'INSIDE_DECLARED_CONTAINER' else 'outside'} "
            f"the declared image; non-zero exit "
            f"{'fails' if enforced else 'does NOT fail'} the task; "
            f"bundle bin/ {'is' if reachable else 'is NOT'} on PATH; "
            f"python3 {'is' if py else 'is NOT'} present."),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--prefix", default="nfgate/e1c")
    ap.add_argument("--role-arn", required=True)
    ap.add_argument("--image", required=True, help="ECR image URI for the probe")
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    if not args.confirm:
        for name in ("probe-container-observe", "probe-container-enforce"):
            print(f"  {name}: {len(package(WORKFLOWS / name))} bytes")
        print("dry run -- nothing created")
        return 0

    output_uri = f"s3://{args.bucket}/{args.prefix}"
    params = RESULTS / "_container_params.json"
    params.write_text(json.dumps({"image": args.image}))

    result = {"image": args.image, "region": args.region, "outputUri": output_uri}

    for key, wf_dir, name in (
        ("e1c_observe", "probe-container-observe", "nfgate-probe-c-observe"),
        ("e1d_enforce", "probe-container-enforce", "nfgate-probe-c-enforce"),
    ):
        rec = create_workflow(name, WORKFLOWS / wf_dir, args.region, args.profile)
        if rec["outcome"] == "ACCEPTED":
            run = aws("omics", "start-run",
                      "--workflow-id", rec["workflowId"],
                      "--role-arn", args.role_arn,
                      "--output-uri", output_uri,
                      "--name", name,
                      "--parameters", f"file://{params}",
                      region=args.region, profile=args.profile)
            done = start_and_wait_existing(run["id"], args.region, args.profile)
            rec["runId"] = run["id"]
            rec["runStatus"] = done.get("status")
            rec["statusMessage"] = done.get("statusMessage", "")
            rec["engineVersion"] = done.get("engineVersion")
            if key == "e1c_observe":
                rec["probeOutput"] = read_probe_output(output_uri, run["id"],
                                                       args.region, args.profile)
        result[key] = rec

    result["verdict"] = verdict(result.get("e1c_observe", {}),
                                result.get("e1d_enforce", {}))
    out = RESULTS / "e1c_container.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["verdict"], indent=2))
    print(f"\nwritten {out}")
    return 0


def start_and_wait_existing(run_id: str, region: str, profile: str | None) -> dict:
    """start_and_wait() in run_probe starts its own run; here the run is already
    started because these probes need --parameters, so only the wait is reused."""
    import time
    from run_probe import TERMINAL
    for _ in range(240):
        got = aws("omics", "get-run", "--id", run_id, region=region, profile=profile)
        if got.get("status") in TERMINAL:
            return got
        time.sleep(15)
    return {"id": run_id, "status": "TIMEOUT"}


if __name__ == "__main__":
    raise SystemExit(main())
