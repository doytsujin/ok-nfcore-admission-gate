# Audit results — pilot

HealthOmics, account `426674444486`, `us-east-1`, engine **Nextflow 25.10.0**,
image `nfgate/probe:py312-slim`. Measured 2026-08-24.

Every probe was calibrated against the local engine first and returned
`SUPPORTED` there, as it must — these are all documented Nextflow behaviours.
A probe that cannot show a directive working locally proves nothing.

## Verdicts

| Directive | On AWS's unsupported list | Measured on HealthOmics | Claim |
|---|---|---|---|
| `errorStrategy` | **no** — documented supported | SUPPORTED | *control passed* |
| `beforeScript` | yes | **SUPPORTED** | **false** |
| `afterScript` | yes | **SUPPORTED** | **false** |
| `shell` | yes | **SUPPORTED** | **false** |
| `scratch` | yes | **SUPPORTED** | **false** |
| `containerOptions` | yes | NOT_SUPPORTED | correct |

**Five list entries tested. Four are false.**

## Evidence

- `beforeScript` — witness file in the task work dir; non-zero exit fails the
  task and the script never runs. See `../results/e1_evidence.md`.
- `afterScript` — run `1293674`; witness exported to
  `output/afterscript.witness`.
- `shell` — run `1902912`; `BASH_VERSION=none`, so `['/bin/sh','-eu']` took
  effect. `$0` reports the script path, not the interpreter, so
  `BASH_VERSION` is the signal.
- `scratch` — run `2576123`; task executed at `/tmp/nxf.umatDhrf3v`, outside
  `/mnt/workflow/`. Confirms AWS's current documentation against AWS's linter.
- `containerOptions` — run `6055504`; `-e NFGATE_PROBE=applied` produced no
  environment variable in the task.

## The control matters, and so does the negative

`errorStrategy` is not on the list; AWS documents it as supported. It returned
SUPPORTED, so the harness was not simply reporting "everything works".

`containerOptions` is on the list and is **correct**. An audit of someone
else's errors is most likely to fail by finding what it went looking for, and a
result set with no confirmations would be the strongest reason to distrust this
one.

## What this does and does not support

**Supported:** on a vendor-published list of 23 unsupported features, last
edited 2024-02-21, four of the five entries tested do not hold. The list is not
a reliable basis for a design decision.

**Not supported:** any claim about the remaining 18 entries, or any general
statement about AWS documentation quality. Thirteen entries are cleanly
testable and eight of those are still untested; seven cannot be tested by this
method at all and are listed as such in `DIRECTIVES.md`.

## Probe defects caught by calibration, not mistaken for findings

Three so far, and each would have looked like a service verdict:

1. Alpine has no `/bin/bash`, which Nextflow's `.command.sh` requires.
2. An unset `$IMAGE` under `bash -ue` aborts the task before its declared
   output exists.
3. The first `afterScript` probe wrote to `publishDir`, which Nextflow manages
   and which is not writable at `afterScript` time — the task died with an
   empty log, and "ran but could not write" is indistinguishable from "never
   ran" when the task dies either way.

This is the reason the method is worth reporting alongside the numbers: three
of the failures encountered in auditing someone else's errors were mine.
