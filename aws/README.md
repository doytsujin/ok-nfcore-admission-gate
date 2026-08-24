# The AWS arm

Runs this repository's admission gate against **AWS HealthOmics**, to answer one
question with a measurement instead of a design document:

> Is the per-task enforcement point the local artifact depends on available on a
> managed workflow service, and if not, what does its absence cost?

`EXPERIMENTS.md` is the protocol, including what would refute each claim.
This file is how to run it.

## Status

| | |
|---|---|
| Probes, drivers, IAM, packaging | **written and dry-run clean** |
| E1 positive control (local Nextflow) | **run, calibrated** — `results/e1_local_control.json` |
| E1, E2, E3 against AWS | **not run** — no working credentials on this machine |

Every AWS profile on this machine returns `InvalidClientTokenId`. Nothing here
has touched an AWS account. The moment a working profile exists this is
`preflight` → `setup` → three commands.

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
