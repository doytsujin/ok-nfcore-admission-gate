# The 23 claims

AWS's Nextflow linter publishes `UNSUPPORTED_NF_PROCESS_DIRECTIVES` — a list of
process directives it states HealthOmics does not support, with the warning
*"It may be ignored or it may cause a workflow run to fail."*

Source: `awslabs/linter-rules-for-nextflow`,
`linter-rules/src/main/groovy/software/amazon/nextflow/rules/utils/HealthOmicsNFUtils.groovy`,
last modified **2024-02-21**.

Two entries are already known false:

- **`beforeScript`** — measured honoured, exit status included (2026-08-24).
- **`scratch`** — contradicted by AWS's own current documentation, which
  publishes a behaviour table per value under `scratchStorageMode: LOCAL`.

That is 2 of 23 without looking hard. This is the audit that looks hard.

## Testability

A claim is only worth counting if a probe can distinguish *supported* from
*ignored* from *rejected*. Not all 23 can.

| Directive | Testable | How the probe decides |
|---|---|---|
| `beforeScript` | **yes** | DONE — witness file + non-zero exit fails task |
| `afterScript` | **yes** | witness written after the script; visible in outputs |
| `cache` | **yes** | set `cache false`, resume the run, see whether the task re-executes |
| `debug` | **yes** | `debug true` echoes task stdout into the run log |
| `echo` | **yes** | deprecated alias of `debug`; same probe |
| `errorStrategy` | n/a | AWS *documents* it as supported; included as a control |
| `maxForks` | **yes** | `maxForks 1` over N parallel tasks; overlap in task timestamps |
| `shell` | **yes** | `shell ['/bin/sh','-eu']`; probe reports `$0` and shell-specific syntax |
| `stageInMode` | **yes** | `copy` vs `symlink`; probe tests whether the input is a symlink |
| `stageOutMode` | partial | observable only via output timing/inode, weak signal |
| `storeDir` | **yes** | second run should skip the task and reuse the stored output |
| `scratch` | **yes** | probe reports whether `$PWD` differs from the task work dir |
| `containerOptions` | **yes** | pass a benign option with an observable effect (e.g. an env var) |
| `disk` | partial | request an implausible size; distinguish rejection from silence |
| `queue` | no | no observable surface on a managed service |
| `executor` | no | setting it would either be ignored or break the run opaquely |
| `clusterOptions` | no | scheduler-specific; nothing to observe |
| `machineType` | no | HealthOmics selects the instance itself |
| `arch` | no | no observable surface |
| `penv` | no | MPI parallel environment; not applicable |
| `pod` | no | Kubernetes-specific |
| `conda` | **yes** | declaring it should either provision an env or be ignored; both observable |
| `spack` | **yes** | same shape as `conda` |
| `module` | partial | environment-modules; observable only if a module system exists |

**Cleanly testable: 13. Partial: 3. Not testable by this method: 7.**

Reporting all three categories matters more than maximising the first. An audit
that quietly drops what it cannot measure and reports a percentage of the
remainder is the same error as the list it is auditing.

## The claim this audit can support

Not "AWS documentation is unreliable" — that is unfalsifiable editorialising.
The claim is narrow and countable:

> Of the *n* cleanly testable directives on a vendor-published list of
> unsupported features, *m* are in fact supported, on a list last edited *d*
> days before the test.

And the consequence, which is the part that generalises past genomics:

> A governance mechanism whose correctness is argued from a provider's
> documentation inherits that documentation's error rate, and that rate is
> measurable rather than assumed.

## Method, unchanged from E1

Every probe is calibrated against the local engine first, where the behaviour
is known. A probe that cannot reproduce the documented Nextflow behaviour
locally is a broken probe, and its result on HealthOmics means nothing.
