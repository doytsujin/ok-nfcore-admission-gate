# What Your Cloud Provider Says It Does Not Support

**Target: IEEE Software, regular (rolling) submission.**
Limit 4,200 words including 250 per figure/table; ≤ 15 references; 150-word
abstract; three actionable insights required.

---

## Abstract *(150 words max — currently 148)*

Cloud providers publish machine-readable statements about their own services:
supported features, unsupported features, required policies. Engineers treat
these as facts and design around them. We tested one such statement — Amazon's
published list of 23 Nextflow process directives that AWS HealthOmics does not
support, shipped as a linter for exactly this purpose — against the running
service. Of the eight entries for which we could construct a decisive probe,
seven were wrong: the directives work. One was correct. A separate documented
policy, required to make the service run containers at all, is rejected by the
API as written. The list had not been edited in 907 days. We describe the
method, which is ordinary: calibrate every probe against a reference system
where the answer is known, and add a no-directive control before believing any
result. Six of our own probes were defective; three would have produced wrong
findings rather than visible failures.

## Three actionable insights

- **Test the vendor's claims about the vendor.** A published compatibility list
  is a hypothesis with a timestamp, not a specification. This one was wrong
  seven times in eight and had not been touched in two and a half years.
- **Calibrate the probe before you believe it.** Every check we ran was first
  run against a reference implementation where the correct answer was known.
  That step caught three defects that would otherwise have been reported as
  service behaviour.
- **A control is not optional.** Three of our results looked like "the vendor is
  wrong" on evidence that could equally have been the platform default. A
  second run without the feature under test decided each one.

---

## 1. The setup

*(~500 words. To draft.)*

We were porting a policy enforcement mechanism onto AWS HealthOmics, a managed
service for running bioinformatics workflows. The mechanism hooks Nextflow's
`process.beforeScript`, which runs immediately before each task's script; a
non-zero exit fails the task, which is what makes a policy decision into an
actual refusal.

AWS publishes a linter for HealthOmics workflows. It contains a list named
`UNSUPPORTED_NF_PROCESS_DIRECTIVES`, and `beforeScript` is on it, with the
warning: *"It may be ignored or it may cause a workflow run to fail."*

That sentence should be read carefully, because the two outcomes it hedges
between are opposites for anyone deploying a control. A **rejected** workflow is
a loud failure at authoring time. A **silently ignored** enforcement hook makes
a gated pipeline and an ungated pipeline produce byte-identical runs — the
control appears to be present, the logs look the same, and nothing is enforced.

We were about to redesign around this. Then we checked when the file was last
modified: **2024-02-21**. And the current HealthOmics documentation describes
`scratch`, also on the list, as supported, with a behaviour table per value.

A list with one entry the vendor's own documentation contradicts is not
evidence. So we tested it.

## 2. Method

*(~700 words. To draft. Cover: probe construction, the reference-calibration
step, the no-directive control, and the decidability triage.)*

Key points to make:

- Each probe is a minimal workflow that declares the directive and reports an
  observable consequence into a file the service exports.
- **Every probe was run first against stock Nextflow on a laptop**, where the
  documented behaviour is the expected answer. A probe that cannot demonstrate a
  directive working where it demonstrably works is measuring nothing.
- **A no-directive control run** decides whether the observed behaviour is the
  directive's effect or the platform's default.
- **Triage by decidability, and report all three categories.** Of 23 entries: 13
  looked cleanly testable, 3 partially, 7 have no observable surface on a
  managed service at all. We report the untestable ones as untestable. An audit
  that drops what it cannot measure and quotes a percentage of the remainder is
  making the error it is auditing.
- A **positive control** — a directive AWS documents as *supported* — rides in
  every run. If it ever fails, the harness is broken and no other verdict in
  that run is usable.

## 3. Results

Of the 8 entries for which a decisive probe existed, **7 do not hold**.

| Directive | AWS says | Measured | Verdict |
|---|---|---|---|
| `beforeScript` | unsupported | works | **wrong** |
| `afterScript` | unsupported | works | **wrong** |
| `shell` | unsupported | works | **wrong** |
| `scratch` | unsupported | works | **wrong** |
| `stageInMode` | unsupported | works | **wrong** |
| `storeDir` | unsupported | works | **wrong** |
| `maxForks` | unsupported | works | **wrong** |
| `containerOptions` | unsupported | does not work | correct |
| `errorStrategy` *(control)* | supported | works | control passed |

**The one correct entry matters as much as the seven wrong ones.** An audit of
someone else's mistakes fails most easily by finding what it went looking for. A
result set with no confirmations would be the best reason to distrust this one.
`containerOptions` was the single negative verdict, and therefore the one where
a transient failure could masquerade as agreement with the vendor, so we
repeated it three further times: unanimous.

### 3.1 Five entries we could not decide, and why that list is published

- **`debug`, `echo`.** Our probe checked whether task output reached the engine
  log. HealthOmics writes task output to the task log *unconditionally*, so the
  probe cannot see the directive's effect at all. **Both would have counted as
  the vendor being right** — the direction least likely to be questioned.
- **`conda`, `spack`.** The probe returned "unsupported" on our reference
  machine too, because conda is not installed there. Nothing is attributable.
- **`cache`.** Deciding whether it is honoured requires resuming a run, which
  the service does not offer.

### 3.2 A second documented artifact that does not work

Separately, HealthOmics cannot pull container images without a resource policy
on each repository. AWS documents that policy. **As published it is rejected by
the API** — it contains a `Resource` element, and repository policies do not
take one. The error is `InvalidParameterException: Invalid repository policy
provided`, which does not say which element is at fault.

We mention it because it is a different failure mode from the stale list: not
out of date, just wrong, and in a document you must follow to use the service.

## 4. What went wrong in our own work

*(~500 words. This section is not optional.)*

Six of our probes were defective. Three would have produced a **wrong finding**
rather than an obvious failure:

1. An `afterScript` probe wrote to a directory the workflow engine manages,
   which is not writable when `afterScript` runs. The task died with an empty
   log — and "ran but could not write" is indistinguishable from "never ran"
   when the task dies either way.
2. The `debug`/`echo` probes read the wrong log stream (§3.1).
3. Three probes produced results that could equally have been the platform
   default until we added no-directive controls.

The other three were visible failures: a base image without `bash`, an unset
shell variable under `set -u`, and a harness bug that overwrote its own results
file.

We report this because a paper that measures someone else's error rate while
concealing its own near-misses is performing the behaviour it criticises. It is
also the practical point: **most of what went wrong while auditing someone
else's errors was ours**, and the only reason we know that is the calibration
step.

## 5. What this does and does not support

**Supported.** On a vendor-published list of 23 unsupported features, last
edited 907 days before the test, 7 of the 8 entries with a decidable probe do
not hold. A published compatibility list decays, and nothing surfaces the decay
to the reader.

**Not supported.** Nothing about the 15 entries we did not decide. No general
claim about this provider's documentation, or anyone's — this is one list, one
service, one day. The seven positive verdicts are single trials, which we
consider adequate because a directive either took effect or did not, and the
single negative verdict was replicated.

**The consequence we do claim**, because it is what changed our own engineering:
a control whose correctness is argued from a provider's documentation inherits
that documentation's error rate — and unlike the documentation, that rate is
measurable.

## 6. What to do about it

*(~400 words. To draft.)*

- Probe the two or three platform behaviours your design actually depends on.
  Ours took an afternoon and about two dollars.
- Keep the probes and re-run them. They are the regression test for the
  assumption, and the assumption is the thing that will change silently.
- Check the modification date of any compatibility list before designing around
  it.
- Write down what you could not test, and do not convert it into a percentage.

---

## Notes, not for submission

- **Repo is public.** `RESULTS.md`, `VENUE.md` and the harness are already
  public in `ok-nfcore-admission-gate`, so this draft discloses nothing new.
  IEEE Software permits preprints; confirm at submission.
- Sources: `aws/audit/RESULTS.md`, `aws/audit/DIRECTIVES.md`,
  `aws/results/e1_evidence.md`, `aws/results/audit_healthomics.json`.
- Word budget: §§1, 2, 4, 6 are outlined and total ~2,100 words when written;
  §§3, 5 are drafted at ~900. Table counts 250. Comfortable inside 4,200.
- **Do not** frame this as an AI/agentic paper to chase a special issue. Both
  themed calls that fit are closed, and a bent frame reads bent.
