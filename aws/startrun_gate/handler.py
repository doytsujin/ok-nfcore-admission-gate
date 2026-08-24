"""E2 -- the admission gate in front of `omics:StartRun`.

The same `gate/` package the local artifact measures, invoked in Lambda, with
one change of enforcement point: locally the decision sits before a *task*;
here it sits before a *run*. Nothing about the policy engine changes, which is
the point -- what changes is the granularity, and that is what E3 measures.

**This function is not the gate. The IAM policy is the gate.**
`iam/deny-startrun-except-gate.json` denies `omics:StartRun` to every principal
except this function's role. Without it a caller simply calls StartRun directly
and the decision here becomes a log line about a run that happened anyway.

Event shape:

    {
      "dataset":    "raw-reads",
      "action":     "trim",
      "context":    {"platform": "illumina", "minReadLength": 10},
      "workflowId": "1234567",
      "roleArn":    "arn:aws:iam::...:role/omics-run-role",
      "outputUri":  "s3://bucket/prefix",
      "parameters": {...}          # passed through to StartRun
    }

Returns the decision record either way. A refusal is a normal outcome with a
200 status and `permitted: false`, not an error -- an error would be indexed,
alarmed and retried, and a policy refusal is none of those things.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import boto3  # provided by the Lambda runtime; not a repo dependency

from gate.descriptor import Descriptor, DescriptorError
from gate.gate import authorize

DESCRIPTORS = Path(os.environ.get("GATE_DESCRIPTORS", "/var/task/descriptors"))
DECISION_BUCKET = os.environ.get("GATE_DECISION_BUCKET", "")
DECISION_PREFIX = os.environ.get("GATE_DECISION_PREFIX", "decisions")

_omics = boto3.client("omics")
_s3 = boto3.client("s3")


def _record(decision_record: dict, key_hint: str) -> str:
    """Write the decision to S3 before acting on it.

    Order matters. The record is written *before* StartRun, so a decision
    cannot be lost by a crash between deciding and acting -- a permitted run
    with no record would be indistinguishable from an ungated one. Duplicate
    records for a run that never started are recoverable; a missing record is
    not.

    The bucket is expected to have Object Lock in compliance mode: the audit
    trail has to resist the account that produced it, or it is a diary.
    """
    if not DECISION_BUCKET:
        return ""
    key = f"{DECISION_PREFIX}/{key_hint}.json"
    _s3.put_object(
        Bucket=DECISION_BUCKET,
        Key=key,
        Body=json.dumps(decision_record, indent=2).encode(),
        ContentType="application/json",
    )
    return f"s3://{DECISION_BUCKET}/{key}"


def handler(event, context):
    wall_start = time.perf_counter()

    # Cold starts are the interesting half of the latency story, so the flag
    # is carried in the record rather than inferred later from log timestamps.
    cold = not getattr(handler, "_warm", False)
    handler._warm = True

    dataset = event["dataset"]
    action = event["action"]
    ctx = event.get("context", {})

    try:
        descriptor = Descriptor.load(DESCRIPTORS / f"{dataset}.json")
    except DescriptorError as exc:
        # A missing or malformed descriptor is a gate error, not a refusal.
        # Collapsing the two would let a deployment mistake read as a policy
        # decision in the audit trail.
        return {"statusCode": 500, "gateError": str(exc)}

    decision = authorize(descriptor, action, ctx)

    record = decision.as_record(
        runId=None,
        enforcementPoint="omics:StartRun",
        granularity="RUN",
        workflowId=event.get("workflowId"),
        requestId=getattr(context, "aws_request_id", None),
        coldStart=cold,
        context=ctx,
    )

    key_hint = f"{time.strftime('%Y/%m/%d')}/{getattr(context, 'aws_request_id', 'local')}"
    record["decisionRecordUri"] = _record(record, key_hint)

    if not decision.permitted:
        record["gateMicros"] = int((time.perf_counter() - wall_start) * 1_000_000)
        _record(record, key_hint)
        return {"statusCode": 200, "permitted": False, "decision": record}

    started = _omics.start_run(
        workflowId=event["workflowId"],
        roleArn=event["roleArn"],
        outputUri=event["outputUri"],
        name=event.get("name", f"gated-{dataset}-{action}"),
        parameters=event.get("parameters", {}),
    )

    record["runId"] = started["id"]
    record["gateMicros"] = int((time.perf_counter() - wall_start) * 1_000_000)
    # Rewritten now that the run id exists. The pre-decision write above is
    # what makes the crash window safe; this one makes the record complete.
    _record(record, key_hint)

    return {"statusCode": 200, "permitted": True, "runId": started["id"],
            "decision": record}
