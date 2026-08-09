# Journal paper scope

Target: **Journal of Biomedical Informatics** (Elsevier). Fallback: **IEEE
JBHI**. Both verified 2026-08-09 to have a traditional, non-OA submission route
carrying no article charge — JBI is hybrid with delayed OA after 12 months;
JBHI states plainly that "No OA payment is required for Traditional
submission", with OA optional at $2,800.

This is the journal extension of the published EMBC 2026 paper
(`dk-embc2026-paper`, *Dataset Descriptors for Autonomous and Observable
Biomedical Data Pipelines*, IEEE EMBC 2026, Toronto). EMBC is prior art, not a
duplicate-publication risk; a journal extension of a 6-page conference paper is
standard practice and is expected to carry substantial new material.

## Working title

*A Prospective Admission Gate for GA4GH-Standard Genomic Workflows*

## The one-sentence claim

Attaching policy to the **dataset** and evaluating it **before** each workflow
task — rather than attaching it to the user or reconstructing it after the run
— refuses impermissible operations at a cost too small to measure in pipeline
timing, and produces a provenance record that can express what was stopped as
well as what ran.

## What is new relative to EMBC

EMBC modelled everything. Its Nextflow baseline was a Python file imitating
Nextflow and its 3.2% latency figure came from cost constants. This paper
replaces that entirely:

| | EMBC 2026 | This paper |
|---|---|---|
| Workflow engine | simulated in Python | **real Nextflow 24.10.5** |
| Pipeline | synthetic 4-stage | **nf-core/demo 1.0.1**, real containers, real reads |
| Overhead | 3.2%, modelled from cost constants | **measured**; below trace resolution |
| Provenance | internal JSONL | **Workflow Run RO-Crate** |
| Refusal | asserted | **demonstrated** — the tool does not run |
| Related work | orchestrators only | **GA4GH DRS / TES / WES / Passports, WRROC** |

## Three contributions

**1. A prospective gate inside a production workflow engine.** The gate runs in
Nextflow's `process.beforeScript`, in the task's own working directory,
immediately before the task script; a non-zero exit fails the task. This is not
a wrapper around the engine or a plugin that observes it — it is a refusal
point inside the engine's own execution path, requiring no fork of nf-core and
no change to the pipeline.

**2. A measured cost, honestly bounded.** Policy evaluation 11 µs median, gate
process 122 µs median, across seven real tasks. The end-to-end difference
between gated and ungated runs is −1.0% on task realtime and −3.8% on task
duration, which is **noise, not a speedup** — Nextflow reports per-task
realtime at one-second granularity, so a 122 µs hook is four orders of
magnitude below the measurement floor. The claim the paper makes is that the
overhead is not observable in pipeline timing. That is weaker-sounding and
much more defensible than a modelled percentage.

**3. Refusals in a retrospective provenance format.** Workflow Run RO-Crate
describes actions that occurred, as `CreateAction` entities. A refusal has no
action. Emitting refusals as `ControlAction` entities alongside them lets one
crate carry both, and — critically — records the conditions that *passed* as
well as the one that failed, so a reader can tell "nothing was refused" from
"nothing was checked".

## Positioning, which is where the paper earns its place

The related-work section is the part EMBC could not write and no other
manuscript in the register can write, because no other target domain has a
standards body.

- **GA4GH Passports/Visas** carry policy, but attached to a *person*: this
  researcher, under this data access committee, may see this dataset. The gate
  attaches policy to the *dataset* and evaluates it per operation.
- **DRS** addresses and fetches data objects. **TES/WES** submit tasks and
  workflows. None of them evaluate admissibility.
- **Workflow Run RO-Crate** (PLOS One, 2024) is the state of the art in
  workflow provenance and is *retrospective by construction*.
- **AWS HealthOmics** is the honest industrial comparator, not the archived
  Amazon Genomics CLI. It has run manifests with checksums, CloudTrail per run,
  and workflow versioning since 2025. Its model is still identity-based (IAM
  answers "may this principal touch this resource") and its manifest is still
  written as the run proceeds.

Supporting observation, defensible from public record: **all three hyperscalers
retired their genomics-specific control plane** — Amazon Genomics CLI archived
2024-05-31, Google Cloud Life Sciences off GCP 2025-07-08, Microsoft Genomics
retired with msgen archived — while the generic compute underneath survived in
every case. What outlived them were the community standards. That is an
argument for putting coordination semantics on the data rather than in the
vendor's scheduler.

## What has to be done before submission

The artifact currently supports the claims above, but not at journal weight.
In priority order:

1. **Repeat runs.** n = 1 per arm today. Needs enough repetitions to put a
   confidence interval on the end-to-end difference and to state the noise
   floor empirically rather than by argument.
2. **A second, larger pipeline.** Three processes and ~20 s of task time
   demonstrates the mechanism; a reviewer will ask whether it holds at
   realistic scale. `nf-core/sarek` or `nf-core/rnaseq` on test data.
3. **More refusal classes exercised end to end.** `UNDECLARED_ACTION` and
   `STATE_PRECONDITION` are implemented and unit-covered but only
   `CONDITION_VIOLATED` has been demonstrated inside a real run.
4. **RO-Crate profile validation.** The crate conforms to the Workflow Run
   Crate shape by construction and has not been through a validator.
5. **A real GA4GH surface.** At minimum DRS resolution for the data objects, so
   the positioning claim is demonstrated rather than only argued.

Items 1–3 are the ones a reviewer would reject on. Items 4–5 strengthen the
positioning but nothing else depends on them.

## What the paper must not claim

- Not a genomics contribution. No variant accuracy, no biological validity, no
  clinical validation. Same scoping discipline as EMBC.
- Not a speedup. The negative overhead numbers are noise and must be presented
  as such.
- Not regulatory compliance. The architecture is compatible with what auditors
  ask for; nothing here has been through an inspection.
- Not a HealthOmics benchmark. HealthOmics is discussed as a comparator on
  design, not measured against — doing so would need an AWS account and a
  different experiment.
