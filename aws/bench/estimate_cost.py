#!/usr/bin/env python3
"""What the AWS arm costs, before it is run.

Written because the honest answer to "can we afford this" is a number with its
assumptions attached, not a shrug. Every rate below is a published list price
with the date it was read; none of them are inferred.

    python3 aws/bench/estimate_cost.py --reps 30
"""

from __future__ import annotations

import argparse

# Read from https://aws.amazon.com/healthomics/pricing/ on 2026-08-24.
# Instance rates are the omics.* workflow instance prices; run storage is
# charged per GB-hour on top.
PRICES_READ_ON = "2026-08-24"
INSTANCE_USD_PER_HOUR = {
    "omics.m.xlarge": 0.2592,
    "omics.c.4xlarge": 0.9180,
    "omics.r.8xlarge": 2.7216,
}
RUN_STORAGE_USD_PER_GB_HOUR = {
    "dynamic": 0.0004110,
    "static": 0.0001918,
}

# nf-core/demo on the test profile: FASTQC x3, SEQTK_TRIM x3, MULTIQC x1.
# Task durations are taken from the LOCAL replicated runs, which is the best
# available prior and is certainly wrong on AWS -- container pull and instance
# provisioning dominate there and are not in the local trace at all. Marked
# as such rather than quietly used as if it transferred.
DEMO_TASKS = 7
LOCAL_TASK_SECONDS = 25.0
AWS_TASK_OVERHEAD_SECONDS = 90.0   # provisioning + image pull, deliberately generous


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=30,
                    help="replicates per arm in E3")
    ap.add_argument("--instance", default="omics.m.xlarge",
                    choices=sorted(INSTANCE_USD_PER_HOUR))
    ap.add_argument("--storage-gb", type=float, default=20.0)
    args = ap.parse_args()

    rate = INSTANCE_USD_PER_HOUR[args.instance]
    task_hours = (LOCAL_TASK_SECONDS + AWS_TASK_OVERHEAD_SECONDS) / 3600.0

    # E1: two container-free runs of a single trivial task.
    e1_tasks = 2
    e1 = e1_tasks * task_hours * rate

    # E3: two arms (permit-then-run, and the refused-run comparator), N each.
    # The refused arm starts no run at all in the refuse branch, so it is
    # counted at zero compute -- that asymmetry is the finding, not an error.
    e3_runs = args.reps                      # the permitted arm actually runs
    e3 = e3_runs * DEMO_TASKS * task_hours * rate

    # Run storage, charged while a run holds its working volume.
    total_run_hours = (e1_tasks + e3_runs * DEMO_TASKS) * task_hours
    storage = total_run_hours * args.storage_gb * RUN_STORAGE_USD_PER_GB_HOUR["dynamic"]

    # Lambda, S3, ECR and CloudWatch at this volume round to nothing, but
    # saying "negligible" without a figure is how estimates drift.
    incidental = 0.50

    total = e1 + e3 + storage + incidental

    print(f"  rates read on {PRICES_READ_ON}, instance {args.instance} "
          f"at ${rate:.4f}/hour")
    print(f"  assumed per-task wall time: {LOCAL_TASK_SECONDS:.0f}s work "
          f"+ {AWS_TASK_OVERHEAD_SECONDS:.0f}s provisioning")
    print()
    print(f"  E1  probes            {e1_tasks:4d} tasks    ${e1:7.2f}")
    print(f"  E3  permitted arm     {e3_runs:4d} runs     ${e3:7.2f}   "
          f"({args.reps} reps x {DEMO_TASKS} tasks)")
    print(f"  E3  refused arm          0 tasks    $   0.00   "
          f"(the refusal is the point: nothing starts)")
    print(f"      run storage                     ${storage:7.2f}")
    print(f"      lambda/s3/ecr/logs              ${incidental:7.2f}")
    print(f"      {'-' * 40}")
    print(f"      total                           ${total:7.2f}")
    print()
    print("  The provisioning figure is the uncertain one. If HealthOmics task")
    print("  startup is slower than 90s, this scales roughly linearly with it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
