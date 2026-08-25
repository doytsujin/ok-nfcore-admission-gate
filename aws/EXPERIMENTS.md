# The AWS arm: what is being tested, and what would refute it

The local artifact measures a **per-task** admission gate inside a real
workflow engine: `process.beforeScript` runs in the task's own working
directory immediately before the task script, and a non-zero exit fails the
task. That is what makes the refusal prospective — on refusal, the tool never
runs.

This arm asks one question about AWS HealthOmics:

> **Is that enforcement point available on a managed workflow service, and if
> not, what does its absence cost?**

Everything below is written so that each experiment can come out the other way.
A protocol that cannot fail is not a measurement.

---

## The claim under test, and why it needs measuring rather than citing

AWS publishes a linter for HealthOmics workflows. Its
`HealthOmicsNFUtils.UNSUPPORTED_NF_PROCESS_DIRECTIVES` list names the directives
the service ignores or rejects, and `beforeScript` is on it — as is
`afterScript`, `shell`, `executor`, `scratch` and eighteen others.

That is AWS's own statement that the enforcement point does not exist.
**It is not sufficient evidence, for two reasons.**

1. **The list is stale.** It was last modified 2024-02-21. The HealthOmics
   documentation now describes `scratch` as supported, with a table of
   per-value behaviour under `scratchStorageMode: LOCAL`. So the list contains
   at least one entry that the service has since contradicted, and it carries
   no guarantee about the others.
2. **"Ignored" and "rejected" are different results.** The linter's own message
   hedges between them: *"It may be ignored or it may cause a workflow run to
   fail."* A silently dropped gate and a refused workflow definition have
   opposite consequences for a regulated deployment. A gate that is dropped
   without a diagnostic is worse than no gate, because the run log looks
   identical to a run in which everything was checked.

So the claim is tested against the running service, not the linter.

---

## E1 — RESULT (run 2026-08-24): the claim is REFUTED

**HealthOmics executes `beforeScript` and fails the task on a non-zero exit.**

E1a returned `EXECUTED` with the witness file present in the task working
directory; E1b's run FAILED with `refusing` — the beforeScript's own stderr —
as the only line between task start and task failure. Engine: Nextflow 25.10.0.
Evidence: `results/e1_evidence.md`, data: `results/e1_probe.json`.

This is the outcome named below as *"what refutes the position this arm exists
to support"*. It is reported as the finding, per that commitment. Per-task
enforcement is available on HealthOmics, the local gate ports across unchanged,
and the trade-off E3 was designed to price does not exist as stated.

**E3 as specified below is therefore moot** and is retained only as the record
of what was planned. See `README.md` for the trust-boundary reframing that
survives, which is not yet established.

---

## E1 — Is `beforeScript` honoured? (container-free, minutes, cents)

Two workflows, deliberately separated so that each produces an answer whatever
the other does.

### E1a — observation

`aws/workflows/probe-beforescript-observe/` declares a `beforeScript` that
writes a witness file into the task working directory and exits **0**. The task
script then reports whether the witness is there.

The run always succeeds, so E1a always yields a verdict:

| `probe.out` contains | Meaning |
|---|---|
| `EXECUTED` | The directive ran. A per-task hook exists inside the bundle. |
| `DROPPED` | The directive was silently ignored. No per-task hook. |

A third outcome is possible before the run starts: `CreateWorkflow` rejects the
definition. That is recorded as `REJECTED_AT_CREATE` and is a *better* result
for an operator than `DROPPED`, because the failure is loud.

### E1b — enforcement

`aws/workflows/probe-beforescript-enforce/` declares a `beforeScript` that
exits **3**. Meaningful only if E1a returned `EXECUTED`.

| Run status | Meaning |
|---|---|
| `FAILED` at the probe task | Non-zero `beforeScript` fails the task. **Per-task refusal works on HealthOmics, and the design claim is refuted.** |
| `COMPLETED` | The directive runs but its exit status is discarded. Side effects yes, enforcement no — the worst of the three, and worth stating plainly. |

**What refutes the position this arm exists to support:** E1a returning
`EXECUTED` *and* E1b returning `FAILED`. That would mean HealthOmics does expose
a per-task enforcement point, the local gate ports across unchanged, and the
"managed provenance or per-task enforcement, not both" trade-off dissolves.

If that is the result, it should be reported as the finding. It is a better
outcome for anyone deploying the gate and a worse one for the paper, and those
are not the same axis.

---

## E2 — The `StartRun` gate, and the permission that makes it a gate

`aws/startrun_gate/handler.py` is the same `gate/` package, invoked in Lambda,
deciding immediately before `omics:StartRun`.

The Lambda is not the gate. **The IAM policy is the gate.** A decision function
that a caller can walk around is a logging statement with extra steps, so the
deployment pairs:

- `aws/iam/gate-role-policy.json` — the gate role may call `omics:StartRun`.
- `aws/iam/deny-startrun-except-gate.json` — every other principal is explicitly
  denied `omics:StartRun`, with a condition on the calling role. At
  organisation scale this belongs in an SCP; it is written here as a role
  policy so the experiment runs in one account.

Measured: decision latency in Lambda, cold and warm, against the local 11 µs
policy evaluation and 119 µs gate process. These are **different quantities** —
the local figure is a process, the Lambda figure is an invocation — and the
comparison is only honest if it says so.

**What refutes it:** if a principal without the gate role can start a run while
the deny policy is attached, the enforcement point is not sound and the design
is wrong as written.

---

## E3 — What whole-run granularity costs

This is the measurement the design document could only assert.

The local refusal scenario refuses `SEQTK_TRIM` on `minReadLength = 10`
(the descriptor requires ≥ 20). Locally, `FASTQC` completes for every sample and
only the trim is refused — permitted work proceeds, forbidden work does not.

`StartRun` granularity cannot express that. It has exactly two branches:

- **Refuse the run.** The forbidden trim does not happen, and neither does the
  permitted QC. Cost = the vCPU-seconds of legitimate work that were forbidden.
- **Permit the run.** The QC happens, and so does the trim. Cost = the
  vCPU-seconds of forbidden work that were admitted.

Both branches are run on HealthOmics, `N` replicates each, and both costs are
reported in vCPU-seconds and in dollars. The claim is arithmetic, not rhetoric:
coarse enforcement is not merely less precise, it has a price, and the price is
one of two specific numbers.

**What refutes it:** if the per-task condition turns out to be decidable before
the run starts — i.e. `minReadLength` is knowable from run parameters alone —
then whole-run granularity is sufficient for this policy and the example is
badly chosen. That is a real risk and is checked explicitly in
`bench/run_arm.py` rather than assumed away. The general case survives
regardless (a condition on an *intermediate* dataset's state cannot be decided
at `StartRun`), but this artifact's specific example has to earn it.

---

## E4 — Nextflow on AWS Batch (the fidelity arm)

Keeps `beforeScript` and therefore keeps the measured system exactly, at the
cost of operating Batch. Scaffolded here, not built: it is the control that
shows the loss in E3 is HealthOmics's, not the cloud's.

Deferred deliberately — E1 through E3 answer the question this arm was created
for, and E4 costs an order of magnitude more setup for a control that only
matters once E3 has a number.

---

## Cost

E1 is two container-free runs of one trivial task: cents.
E3 is `N` runs of nf-core/demo (7 tasks) on `omics.m.xlarge` at $0.2592/hour
plus dynamic run storage at $0.0004110 per GB-hour — the refused arm starts
nothing and costs nothing, which is the finding rather than an accounting
convenience. At `N = 30` the arm comes to **about $2.30**, dominated by
per-task provisioning rather than by the work.

`aws/preflight.sh` prints the estimate against live pricing before anything
starts, and nothing in this directory calls `StartRun` without `--confirm`.
