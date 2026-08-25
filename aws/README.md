# The AWS arm

Runs this repository's admission gate against **AWS HealthOmics**, to answer one
question with a measurement instead of a design document:

> Is the per-task enforcement point the local artifact depends on available on a
> managed workflow service, and if not, what does its absence cost?

`EXPERIMENTS.md` is the protocol, including what would refute each claim.
This file is how to run it.

## The account has been torn down

Everything this arm created in AWS was deleted on 2026-08-25: runs, workflows,
the ECR repository, the gate Lambda, three IAM roles and both buckets. The
account is clean and is costing nothing.

**The evidence survived the teardown.** `aws/archive_evidence.sh` pulled 52
files (212 KB) into `aws/results/archive/` first — run and task metadata, the
CloudWatch task logs carrying the refusal lines, and every published text
artefact. Deleting the account without that would have left the papers'
central claims unverifiable by anyone, including us.

`aws/teardown.sh` reproduces the deletion; `aws/setup.sh` reproduces the
account. Re-running the whole arm costs about two dollars.

## Status

| | |
|---|---|
| Positive controls (local Nextflow) | run, calibrated — `e1_local_control.json`, `e1c_local_control.md` |
| **E1 — `beforeScript`, no container** | **RUN — honoured. The claim is REFUTED** |
| **E1c/E1d — `beforeScript`, containerised** | **RUN — honoured, and it runs INSIDE the image** |
| **The real gate, per task** | **RUN — it permits, it refuses, and the refused task never starts** |
| E2 (`StartRun` gate + IAM deny) | not run |
| E3 (nf-core/demo, 30 replicates) | not run; blocked on interpreter-bearing images |

## The headline

**The admission gate runs unchanged on AWS HealthOmics, per task, and its
refusals are real.** In one run with `minReadLength=10`: `GATED_QC` completed
and published its PERMIT record; `GATED_TRIM` failed with

```
Task started
gate: REFUSE raw-reads:trim [CONDITION_VIOLATED] minReadLength: 10 violates >= 20
Task failed
```

and produced no output. Permitted work proceeded, forbidden work did not, in
the same run — the outcome a `StartRun`-level gate structurally cannot produce.
Evidence: [`results/gate_real_evidence.md`](results/gate_real_evidence.md).

## The E1 result

**AWS HealthOmics honours `process.beforeScript`, including its exit status.**
Per-task admission control is available on the managed service. The claim this
arm was built to test does not hold.

Account `426674444486`, `us-east-1`, HealthOmics engine **Nextflow 25.10.0**.
Full evidence in [`results/e1_evidence.md`](results/e1_evidence.md).

- **E1a** — `CreateWorkflow` accepted a definition containing `beforeScript`;
  the run **COMPLETED**; `probe.out` reads `EXECUTED` and
  `beforescript.witness` is present in the task's own working directory.
- **E1b** — the run **FAILED** at the probe task. Its CloudWatch stream is
  three lines: `Task started` / `refusing` / `Task failed`. `refusing` is what
  the `beforeScript` writes before `exit 3`. The task script never ran.

So AWS's linter list is wrong about `beforeScript` in exactly the way it was
already wrong about `scratch`. That list was the sole basis for the claim, and
treating it as a hypothesis rather than as evidence is what made this
detectable.

**Scope — since closed.** E1c/E1d repeated this for a task declaring an ECR
image and the directive is still honoured. But **it runs inside the declared
container**, where the local engine runs it on the host. That is a real
portability constraint: the gate's code and descriptors must ship in the
workflow bundle (reached at `/mnt/workflow/definition/`, by absolute path,
because `bin/` is not on `PATH` at hook time), and **every task image must
carry a Python interpreter**. Many biocontainers do not, which is what now
blocks the nf-core/demo arm.

## What this does to the argument

The granularity claim — *managed provenance or per-task enforcement, not both*
— is dead as stated. What survives, and is worth testing next, is a **trust
boundary** claim rather than a granularity one: the `beforeScript` gate lives
inside the workflow bundle **the caller supplies**, so it protects a caller
from their own pipeline but cannot be enforced *against* that caller, who can
simply submit an ungated definition. Service-side, `omics:StartRun` remains the
only place a policy can be imposed on someone else.

That is a different and narrower contribution, and it is not yet established —
IAM can condition `StartRun` on a specific workflow ID, which may close it
entirely. It should be tested, not asserted.

The measured result makes that question sharper rather than softer: the gate
demonstrably works, so the only remaining question about it is who it protects.

## The finding this arm exists to test

AWS's own Nextflow linter lists the process directives HealthOmics does not
support, in
[`HealthOmicsNFUtils.groovy`](https://github.com/awslabs/linter-rules-for-nextflow/blob/main/linter-rules/src/main/groovy/software/amazon/nextflow/rules/utils/HealthOmicsNFUtils.groovy):

```groovy
def static UNSUPPORTED_NF_PROCESS_DIRECTIVES = [
        'afterScript', 'arch', 'beforeScript', 'cache', 'clusterOptions',
        'conda', 'containerOptions', 'debug', 'disk', 'echo', 'executor',
        'machineType', 'maxForks', 'module', 'penv', 'pod', 'queue',
        'scratch', 'shell', 'spack', 'stageInMode', 'stageOutMode', 'storeDir',
]
```

`beforeScript` is the hook this artifact's gate is wired into. On AWS's own
account it is unsupported.

**That is not sufficient evidence, and the reason is checkable.** That file was
last modified **2024-02-21**. The current HealthOmics documentation describes
`scratch` — also on the list — as supported, with a behaviour table per value
under `scratchStorageMode: LOCAL`. So the list has at least one entry the
service has since contradicted, and the linter's own message hedges between two
very different outcomes: *"It may be ignored or it may cause a workflow run to
fail."*

Silently ignored and loudly rejected are opposite results for a regulated
deployment. A dropped gate is worse than no gate, because the run log of a
gated definition and an ungated one are then identical.

So it gets measured.

## Running it

```bash
export AWS_PROFILE=your-profile
export AWS_REGION=us-east-1

./aws/preflight.sh                    # credentials, region, permissions, quotas, cost
./aws/setup.sh --bucket my-nfgate-bucket

# E1 -- two container-free runs, cents, minutes
python3 aws/bench/run_probe.py --bucket my-nfgate-bucket \
    --role-arn arn:aws:iam::ACCOUNT:role/nfgate-omics-run-role --confirm

# E3 -- the granularity cost, 30 replicates
python3 aws/bench/run_arm.py --bucket my-nfgate-bucket \
    --role-arn arn:aws:iam::ACCOUNT:role/nfgate-omics-run-role --reps 30 --confirm
python3 aws/bench/aggregate_aws.py
```

E3 mirrors three biocontainers into ECR with **podman** (rootless), the same
engine the local arm runs its containers under, so the images HealthOmics pulls
are the ones the measured runs used. Set `NFGATE_CONTAINER_CMD=docker` to
override. E1 needs no container engine at all.

E3 needs `pipeline-nfcore-demo/` present. It is gitignored — clone it as the
root README describes before running the demo arm. E1 does not need it, which
is deliberate: the experiment that answers the central question has the fewest
prerequisites.

Every driver is a no-op without `--confirm`. `preflight.sh` creates nothing.
`setup.sh` prints every resource it made to `results/created-resources.txt`.

**E2 needs one deliberate manual step.** `setup.sh` does not attach
`iam/deny-startrun-except-gate.json`, because attaching a `Deny` on
`omics:StartRun` to the wrong principal locks you out of your own account's
HealthOmics. Attach it yourself, to the roles that must not start runs
directly, then verify a direct `StartRun` is refused. Until that is done the
Lambda is a decision, not a gate — see the note in `startrun_gate/handler.py`.

## Cost

`aws/bench/estimate_cost.py` prints it against list prices read on 2026-08-24.
At 30 replicates the whole arm is **about $2.30**, dominated by per-task
provisioning rather than by the work. The uncertain input is HealthOmics task
startup, assumed at 90 s and marked as an assumption in the script.

## What is here

```
EXPERIMENTS.md            the protocol, and what refutes each claim
preflight.sh              is this account able to run the arm, and what will it cost
setup.sh                  buckets, IAM, ECR mirrors, the gate Lambda (idempotent)
iam/                      four policy documents; the deny policy IS the gate
startrun_gate/handler.py  gate/ unchanged, invoked before omics:StartRun
workflows/
  probe-beforescript-observe/   E1a -- does the directive execute
  probe-beforescript-enforce/   E1b -- does a non-zero exit stop the task
  demo/omics.config             nf-core/demo, adjusted for HealthOmics
bench/
  local_control.sh        positive control -- run this first, always
  run_probe.py            E1 driver
  run_arm.py              E3 driver, with the decidability check
  aggregate_aws.py        the granularity cost, paired intervals
  estimate_cost.py        what it costs, with the rates dated
  awscli.py               dependency-free aws CLI wrapper
```

Nothing here imports boto3 outside the Lambda, for the same reason
`bench/aggregate.py` embeds a t-table instead of importing scipy: the artifact
should run for anyone who has the AWS CLI and nothing else.

## The one thing to do first

`./aws/bench/local_control.sh`. It runs both probes under the repository's own
Nextflow, where the answers are known, and writes
`results/e1_local_control.json`. It has been run and it passes: E1a returns
`EXECUTED`, E1b stops the task with exit 1.

That calibration is what lets a `DROPPED` on HealthOmics mean something about
HealthOmics.
