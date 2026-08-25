#!/usr/bin/env python3
"""Audit AWS's published list of unsupported Nextflow directives.

    python3 aws/audit/run_audit.py --local                    # calibrate, free
    python3 aws/audit/run_audit.py --confirm --bucket B --role-arn R --image I

AWS publishes 23 claims about its own service. Two are already known false.
This tests the cleanly testable ones and reports every category, including the
ones this method cannot reach -- an audit that silently drops what it cannot
measure repeats the error it is auditing.

`--local` runs every probe against the reference engine, where Nextflow's
documented behaviour is the expected answer. A probe that cannot show a
directive working locally proves nothing about HealthOmics.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "aws" / "bench"))

import probes as P  # noqa: E402
from awscli import AwsError, aws  # noqa: E402
from run_probe import TERMINAL, package  # noqa: E402

RESULTS = ROOT / "aws" / "results"
GEN = RESULTS / "audit-workflows"


def materialise(probe: P.Probe) -> Path:
    """Write one probe out as a workflow directory."""
    slug = probe.name.replace("[", "_").replace("]", "").replace("/", "_")
    d = GEN / slug
    d.mkdir(parents=True, exist_ok=True)
    proc = "AUDIT_" + slug.upper().replace("-", "_")
    (d / "main.nf").write_text(P.render(probe, proc))
    (d / "nextflow.config").write_text(P.CONFIG + "\n" + probe.extra_config + "\n")
    return d


def parse(text: str) -> dict:
    out = {}
    for line in (text or "").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


# ---------------------------------------------------------------- local -----
def run_local(probe: P.Probe, image: str) -> dict:
    d = materialise(probe)
    work = Path(os.environ.get("NFGATE_WORK", str(Path.home() / ".nfgate-work"))) / "audit" / d.name
    pub = work / "pub"
    shutil.rmtree(work, ignore_errors=True)
    pub.mkdir(parents=True, exist_ok=True)

    cfg = work / "local.config"
    cfg.write_text("podman.enabled = true\npodman.mountFlags = 'z'\n")

    env = dict(os.environ)
    env.update({
        "JAVA_HOME": str(ROOT / "toolchain" / "jdk-21.0.12+8"),
        "PATH": f"{ROOT / 'toolchain' / 'jdk-21.0.12+8' / 'bin'}:{os.environ['PATH']}",
        "NXF_HOME": str(ROOT / "toolchain" / ".nextflow"),
        "NXF_VER": "24.10.5",
    })
    proc = subprocess.run(
        [str(ROOT / "toolchain" / "nextflow"), "run", str(d / "main.nf"),
         "-c", str(cfg), "--image", image, "--pubdir", str(pub),
         "-w", str(work / "w"), "-ansi-log", "false"],
        capture_output=True, text=True, env=env, timeout=900)

    text = (pub / "probe.out").read_text() if (pub / "probe.out").exists() else ""
    w = parse(text)
    if (pub / "afterscript.witness").exists():
        w["_afterscript_witness"] = "yes"
    verdict, why = probe.decide(w) if w else ("INCONCLUSIVE", "no output produced")
    return {"probe": probe.name, "where": "local", "exit": proc.returncode,
            "verdict": verdict, "why": why, "witness": w,
            "stderr_tail": proc.stderr.strip().splitlines()[-3:]}


# --------------------------------------------------------------- healthomics -
def run_aws(probe: P.Probe, args) -> dict:
    d = materialise(probe)
    slug = d.name
    zip_path = RESULTS / f"audit-{slug}.zip"
    zip_path.write_bytes(package(d))
    name = f"nfgate-audit-{slug.lower().replace('_','-')}"[:60]

    try:
        wf = aws("omics", "create-workflow", "--name", name, "--engine", "NEXTFLOW",
                 "--definition-zip", f"fileb://{zip_path}",
                 region=args.region, profile=args.profile)
    except AwsError as exc:
        return {"probe": probe.name, "where": "healthomics",
                "verdict": "REJECTED_AT_CREATE", "why": exc.stderr[:300]}

    wid = wf["id"]
    for _ in range(60):
        got = aws("omics", "get-workflow", "--id", wid, region=args.region, profile=args.profile)
        if got.get("status") == "ACTIVE":
            break
        if got.get("status") in ("FAILED", "DELETED"):
            return {"probe": probe.name, "where": "healthomics",
                    "verdict": "REJECTED_AT_CREATE",
                    "why": got.get("statusMessage", "")[:300]}
        time.sleep(5)

    params = RESULTS / f"_audit_params_{slug}.json"
    params.write_text(json.dumps({"image": args.image}))
    run = aws("omics", "start-run", "--workflow-id", wid, "--role-arn", args.role_arn,
              "--output-uri", f"s3://{args.bucket}/{args.prefix}/{slug}",
              "--name", name, "--parameters", f"file://{params}",
              region=args.region, profile=args.profile)
    rid = run["id"]
    done = {}
    for _ in range(240):
        done = aws("omics", "get-run", "--id", rid, region=args.region, profile=args.profile)
        if done.get("status") in TERMINAL:
            break
        time.sleep(15)

    base = f"s3://{args.bucket}/{args.prefix}/{slug}/{rid}"
    w = {}
    try:
        listing = aws("s3", "ls", base + "/", "--recursive",
                      region=args.region, profile=args.profile, parse=False)
    except AwsError:
        listing = ""
    for line in listing.splitlines():
        key = line.split()[-1] if line.split() else ""
        if key.endswith("probe.out"):
            body = aws("s3", "cp", f"s3://{args.bucket}/{key}", "-",
                       region=args.region, profile=args.profile, parse=False)
            w.update(parse(body))
        if key.endswith("afterscript.witness"):
            w["_afterscript_witness"] = "yes"

    verdict, why = probe.decide(w) if w else ("INCONCLUSIVE", "no output produced")
    return {"probe": probe.name, "where": "healthomics", "runId": rid,
            "runStatus": done.get("status"), "engineVersion": done.get("engineVersion"),
            "verdict": verdict, "why": why, "witness": w}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--bucket"); ap.add_argument("--role-arn"); ap.add_argument("--image")
    ap.add_argument("--prefix", default="nfgate/audit")
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    ap.add_argument("--jobs", type=int, default=5,
                    help="concurrent runs; StartRun is quota-limited to 5 TPS")
    args = ap.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    pilot = P.PILOT

    if args.local:
        image = args.image or "docker.io/library/python:3.12-slim"
        rows = [run_local(p, image) for p in pilot]
        out = RESULTS / "audit_local.json"
    elif args.confirm:
        if not (args.bucket and args.role_arn and args.image):
            print("--confirm needs --bucket --role-arn --image", file=sys.stderr)
            return 2
        with cf.ThreadPoolExecutor(max_workers=args.jobs) as ex:
            rows = list(ex.map(lambda p: run_aws(p, args), pilot))
        out = RESULTS / "audit_healthomics.json"
    else:
        for p in pilot:
            materialise(p)
        print(f"generated {len(pilot)} probe workflows under {GEN}")
        print("run with --local to calibrate, or --confirm to test on HealthOmics")
        return 0

    out.write_text(json.dumps(rows, indent=2) + "\n")
    width = max(len(r["probe"]) for r in rows)
    for r in rows:
        print(f"  {r['probe']:<{width}}  {r['verdict']:<18} {r['why'][:80]}")
    print(f"\nwritten {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
