# The gate, per task, on AWS HealthOmics

Run 2026-08-24, account `426674444486`, `us-east-1`, engine Nextflow 25.10.0,
image `nfgate/probe:py312-slim` (Debian 13). Workflow `nfgate-gate-real`.

`gate/` and `descriptors/` were copied byte-identically from this repository
into the workflow bundle. The gate's logic is unchanged. Only two things differ
from the local arm, and both follow from `e1c_container.json`: the module is
reached at `/mnt/workflow/definition/` because HealthOmics runs `beforeScript`
**inside the task container**, and it is invoked by absolute path because the
bundle's `bin/` is not on `PATH` when the hook runs.

## Permit arm — `minReadLength=30`, run `1144766`, COMPLETED

Both tasks admitted. Decision records published by the gate itself:

```json
{"action":"qc","verdict":"PERMIT","datasetId":"raw-reads",
 "descriptorVersion":"1.2.0","observedState":"QC_PASSED",
 "conditionsChecked":[{"name":"platform","operator":"in","expected":["illumina"],
                       "observed":"illumina","passed":true}],
 "evalMicros":28,"wallMicros":6602,"task":"GATED_QC"}

{"action":"trim","verdict":"PERMIT",
 "conditionsChecked":[{"name":"minReadLength","operator":">=","expected":20,
                       "observed":30,"passed":true},
                      {"name":"platform","operator":"in","expected":["illumina"],
                       "observed":"illumina","passed":true}],
 "evalMicros":43,"wallMicros":7283,"task":"GATED_TRIM"}
```

## Refuse arm — `minReadLength=10`, run `8101547`, FAILED

| Task | Status | Output published |
|---|---|---|
| `GATED_QC` | **COMPLETED** | `qc.done` — PERMIT record, `evalMicros` 28 |
| `GATED_TRIM` | **FAILED** | none — `trim.done` absent |

`GATED_TRIM` CloudWatch stream, in full:

```
Task started
gate: REFUSE raw-reads:trim [CONDITION_VIOLATED] minReadLength: 10 violates >= 20
Task failed
```

**The permitted task completed and the refused task never ran, in the same
run.** That is per-task admission control on a managed workflow service, and it
is the behaviour a `StartRun`-level gate structurally cannot produce: a run gate
must either admit both or refuse both.

## Timing, at n=2 — not a claim

| | Local (n=30) | HealthOmics (n=2) |
|---|---|---|
| Policy evaluation | 11 µs median | 28 µs, 43 µs |
| Gate in-process wall | 119 µs | 6602 µs, 7283 µs |

Same order for evaluation. The in-process wall figure is ~55× worse and the
likely cause is descriptor loading across the bundle mount rather than a warm
page cache — **untested**; it is two observations and is recorded as such.

Note what is *not* comparable: the local per-task cost of +25.7 ms is dominated
by `python3 -m gate` process creation on a host where tasks last ~25 s. Here
tasks are minutes long and provisioning dominates, so the same absolute cost is
a different proportion of a different denominator.

## What this does not show

- One image, which carries a Python interpreter because it was chosen to.
  **Task images without `python3` cannot run this gate**, and many
  biocontainers have none. That is the open constraint for a real nf-core
  pipeline.
- Two runs. No interval, no replication.
- Nothing about whether the gate can be enforced *against* the caller, who
  supplies the bundle and chooses the image.
