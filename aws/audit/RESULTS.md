# Audit results

AWS HealthOmics, account `426674444486`, `us-east-1`, engine **Nextflow
25.10.0**, image `nfgate/probe:py312-slim`. Measured 2026-08-24.

The claim under audit is AWS's own
`UNSUPPORTED_NF_PROCESS_DIRECTIVES` list — 23 process directives the vendor
states its service does not support, published in a linter it ships for the
purpose, last edited **2024-02-21**.

## Result

**Of 8 entries with a decidable probe, 7 do not hold.**

| Directive | AWS says | Measured | Claim | Controlled by |
|---|---|---|---|---|
| `beforeScript` | unsupported | SUPPORTED | **false** | dropped/rejected alternatives |
| `afterScript` | unsupported | SUPPORTED | **false** | no witness without the directive |
| `shell` | unsupported | SUPPORTED | **false** | control: default is bash 5.2.37 |
| `scratch` | unsupported | SUPPORTED | **false** | prior runs: default cwd is `/mnt/workflow/…` |
| `stageInMode` | unsupported | SUPPORTED | **false** | control: default stages a symlink |
| `storeDir` | unsupported | SUPPORTED | **false** | output appears only under storeDir |
| `maxForks` | unsupported | SUPPORTED | **false** | control: tasks overlap without it |
| `containerOptions` | unsupported | NOT_SUPPORTED | **correct** | **replicated 3×, unanimous** |
| `errorStrategy` | *not on the list* | SUPPORTED | *positive control passed* | — |

## Not counted, and why

Excluding these matters more than the headline. Each was a candidate
verdict that the evidence does not support.

| Directive | Verdict withheld | Reason |
|---|---|---|
| `debug` | would have read NOT_SUPPORTED | HealthOmics writes task stdout to the task log **unconditionally**; the probe cannot see whether the directive did anything |
| `echo` | would have read NOT_SUPPORTED | same |
| `conda` | would have read NOT_SUPPORTED | the probe reads NOT_SUPPORTED **locally too** — conda is not installed on the calibration host, so nothing is attributable to HealthOmics |
| `spack` | would have read NOT_SUPPORTED | same |
| `cache` | ACCEPTED_ONLY | observing whether it is *honoured* needs a resume, which HealthOmics does not offer |

`debug` and `echo` are the ones worth dwelling on: both would have counted as
**AWS being right**. An audit of someone else's errors is least likely to
question a result that flatters the audited party, and these two were caught
only by checking where the output actually went.

Seven further entries — `queue`, `executor`, `clusterOptions`, `machineType`,
`arch`, `penv`, `pod` — have no observable surface on a managed service and
were never testable by this method. See `DIRECTIVES.md`.

## Controls

Three verdicts were withheld until a no-directive control proved the probe
could detect a difference at all. Every one of them would otherwise have
counted as a claim being false:

- **`maxForks`** — without the directive, tasks 1 and 3 overlap. With
  `maxForks 1`, three tasks, none overlapping.
- **`stageInMode`** — without the directive the staged input is a symlink; with
  `stageInMode 'copy'` it is a regular file.
- **`shell`** — without the directive `BASH_VERSION=5.2.37(1)-release`; with
  `['/bin/sh','-eu']`, unset.

`errorStrategy` rides along as a positive control: not on the list, documented
supported, and it reads SUPPORTED. Had it not, no verdict in the run would be
usable.

## What this supports

> On a vendor-published list of 23 unsupported features, last edited 907 days
> before the test, **7 of the 8 entries with a decidable probe do not hold**.

And the consequence that travels past genomics:

> A governance mechanism whose correctness is argued from a provider's
> documentation inherits that documentation's error rate — and that rate is
> measurable rather than assumed.

## What it does not support

- Nothing about the 15 entries not decided here.
- No general claim about AWS documentation quality. One list, one service.
- **n = 1 for the seven SUPPORTED verdicts.** These are binary behaviours
  rather than measurements with variance, and a SUPPORTED verdict cannot be a
  transient failure — the directive either took effect or it did not.
- ~~The `NOT_SUPPORTED` verdict is unreplicated.~~ **Closed 2026-08-25.**
  `containerOptions` was repeated three further times and returned
  `NOT_SUPPORTED` on every trial (n = 4, unanimous). That was the one verdict
  where a transient failure would have masqueraded as agreement with the
  vendor, which is why it is the one that was repeated.

## Probe defects caught by calibration rather than reported as findings

Six, across the whole arm. Each would have looked like service behaviour:

1. Alpine has no `/bin/bash`, which Nextflow's `.command.sh` requires.
2. An unset `$IMAGE` under `bash -ue` aborts the task before its output exists.
3. The first `afterScript` probe wrote to `publishDir`, which Nextflow manages
   and which is not writable when `afterScript` runs.
4. `shell` in a process body collides with Nextflow's `shell:` block keyword
   and fails to compile.
5. `debug`/`echo` read the wrong log stream.
6. `--only` overwrote the result file, discarding verdicts that cost money.

Three of the six would have produced a *wrong finding* rather than an obvious
failure. That is the argument for the method, and it is worth reporting beside
the numbers: most of what went wrong in auditing someone else's errors was
mine.
