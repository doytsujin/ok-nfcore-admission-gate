"""Gate CLI -- the process Nextflow invokes before each task.

Wired in via `process.beforeScript` in nextflow.config, so it runs inside the
task's own working directory, in the task's own environment, immediately
before the task script. A non-zero exit makes Nextflow fail the task, which is
what turns a policy decision into an actual refusal.

Usage:
    python3 -m gate --dataset raw-reads --action align --context k=v ...

Exit codes:
    0  admitted
    3  refused by policy   (distinguished from 1 so a crash is not mistaken
                            for a refusal, and vice versa)
    1  gate error          (bad descriptor, missing dataset, bad arguments)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gate.descriptor import Descriptor, DescriptorError  # noqa: E402
from gate.gate import authorize  # noqa: E402
from gate.telemetry import DecisionLog  # noqa: E402

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REFUSED = 3


def parse_context(pairs: list[str]) -> dict:
    ctx: dict = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"gate: bad --context {pair!r}, expected key=value")
        key, _, value = pair.partition("=")
        # Numbers arrive from the shell as strings; coerce so numeric
        # comparisons in policy.py do not silently fail closed.
        try:
            ctx[key] = int(value)
        except ValueError:
            try:
                ctx[key] = float(value)
            except ValueError:
                ctx[key] = value
    return ctx


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gate", description="Prospective admission gate")
    ap.add_argument("--descriptors", default=os.environ.get("GATE_DESCRIPTORS", "descriptors"))
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--action", required=True)
    ap.add_argument("--context", nargs="*", default=[])
    ap.add_argument("--log", default=os.environ.get("GATE_LOG", "results/decisions.jsonl"))
    ap.add_argument("--run-id", default=os.environ.get("GATE_RUN_ID", "unknown"))
    ap.add_argument("--task", default=os.environ.get("GATE_TASK", "unknown"))
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="evaluate and record, but always exit 0 (used to measure gate "
             "overhead without changing which tasks run)",
    )
    args = ap.parse_args(argv)

    wall_start = time.perf_counter()

    path = Path(args.descriptors) / f"{args.dataset}.json"
    try:
        descriptor = Descriptor.load(path)
    except DescriptorError as exc:
        print(f"gate: {exc}", file=sys.stderr)
        return EXIT_ERROR

    context = parse_context(args.context)
    decision = authorize(descriptor, args.action, context)

    log = DecisionLog(args.log)
    log.write(
        decision.as_record(
            runId=args.run_id,
            task=args.task,
            context=context,
            dryRun=args.dry_run,
            wallMicros=int((time.perf_counter() - wall_start) * 1_000_000),
        )
    )

    if decision.permitted:
        print(f"gate: PERMIT {args.dataset}:{args.action}", file=sys.stderr)
        return EXIT_OK

    print(
        f"gate: REFUSE {args.dataset}:{args.action} [{decision.reason_class}] "
        + "; ".join(decision.reasons),
        file=sys.stderr,
    )
    return EXIT_OK if args.dry_run else EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
