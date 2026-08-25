# E1 — raw evidence

Run 2026-08-24 (task timestamps 2026-08-25 UTC), account `AWS_ACCOUNT`,
region `us-east-1`, HealthOmics engine **Nextflow 25.10.0**, storage `DYNAMIC`.

## E1a — observation

Workflow `4700382` (`nfgate-probe-observe`) — `CreateWorkflow` **ACCEPTED** a
definition containing `beforeScript`; status `ACTIVE`. Run `7520549`
**COMPLETED**.

`probe.out`, retrieved from the run's S3 output:

```
EXECUTED
cwd=/mnt/workflow/61/26ba10e8e77effee369d7a299e1c2c
.
..
.command.begin
.command.err
.command.out
.command.run
.command.sh
beforescript.witness
probe.out
```

`beforescript.witness` is present in the task's own working directory. The
directive ran, in the task's working directory, before the task script.

## E1b — enforcement

Workflow `1626894` (`nfgate-probe-enforce`), run `9958245` **FAILED**.

Task `7241923` (`PROBE_ENFORCE`), `FAILED`, 2026-08-25T01:43:26 →
01:43:44 UTC, 2 vCPU / 4 GiB.

CloudWatch `/aws/omics/WorkflowLog`, stream `run/9958245/task/7241923`, in
full — three lines:

```
Task started
refusing
Task failed
```

`refusing` is what the `beforeScript` writes to stderr immediately before
`exit 3`. The task script would have written `EXIT_STATUS_DISCARDED` to
`enforce.out`; no such file exists in the run output. The script never ran.

## Attribution

The failure is attributable to the directive rather than to anything else in
the run: the only log line between "Task started" and "Task failed" is the
string emitted by the `beforeScript` itself.

The probes were calibrated against the local engine first
(`e1_local_control.json`, same day): E1a `EXECUTED`, E1b nextflow exit 1 with
the task stopped. Both engines agree, which is the point — the probe reads the
same on a known-positive control.

## Scope of this result

Verified for tasks that declare **no** `container` directive, which HealthOmics
runs in its default container. Not yet verified for tasks declaring an ECR
image — the case the real gate operates in. E3 covers that, and until it runs
this result should be stated with that boundary attached.
