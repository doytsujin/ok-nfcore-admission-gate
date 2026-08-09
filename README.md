# dk-nfcore-admission-gate

A **prospective admission gate** in front of a **real nf-core pipeline**, with
**real Workflow Run RO-Crate provenance** and **measured** overhead.

This exists to close one specific gap. The published EMBC 2026 paper
(*Dataset Descriptors for Autonomous and Observable Biomedical Data Pipelines*,
`dk-embc2026-paper`) models everything: the descriptor engine is real Python,
but the "Nextflow baseline" it is compared against is a Python file imitating
Nextflow, and the 3.2% latency overhead comes from cost constants rather than a
clock. Here nothing is modelled. Nextflow runs, containers run, FASTQ files are
read, and the numbers come out of Nextflow's own trace file.

## What it does

`nf-core/demo` v1.0.1 is a real three-stage pipeline — FASTQC, SEQTK_TRIM,
MULTIQC — over real Illumina amplicon test reads from `nf-core/test-datasets`.
Three datasets are described by JSON descriptors in [`descriptors/`](descriptors/),
each declaring its state and the operations permissible on it.

The gate is wired in through `process.beforeScript`. Nextflow runs that hook in
the task's own working directory, immediately before the task script, and a
non-zero exit fails the task. That is what makes this prospective rather than
retrospective: **when the gate refuses, the tool never runs.**

```
descriptor  ──►  gate.authorize()  ──►  PERMIT ──► task script runs
   (state,          (before the           │
    conditions)      script)              └─ REFUSE ──► task never starts
                          │
                          └──► decision record written either way
```

## Measured results

One baseline run and one gated run of the same pipeline on the same inputs,
both with warm container caches, `executor.queueSize = 1`, 7 tasks each, all
completing. Numbers from `results/overhead.json`, produced by
[`bench/measure.py`](bench/measure.py) from Nextflow's trace files.

| | baseline | gated | delta |
|---|---:|---:|---:|
| Tasks completed | 7 | 7 | — |
| Total task realtime | 19.8 s | 19.6 s | −0.2 s (−1.0%) |
| Total task duration | 21.2 s | 20.4 s | −0.8 s (−3.8%) |
| Median per-task delta | — | — | 0.0 s |

The gate's own cost, measured inside the gate process across all 7 decisions:

| | median |
|---|---:|
| Policy evaluation | **11 µs** |
| Gate process, argument parse to record written | **122 µs** |

**The headline is that the overhead is below the measurement floor, and the
negative numbers are noise rather than a speedup.** Nextflow reports per-task
`realtime` at one-second granularity, so a 122 µs hook cannot appear in it at
all; run-to-run variance in container startup is several orders of magnitude
larger than the thing being measured. The honest statement is that a gate
costing ~10⁻⁴ s per task, against tasks costing ~10⁰ s, is not observable in
end-to-end pipeline timing.

That is a different and stronger claim than the paper's modelled 3.2%, and it
is the claim the evidence here supports.

### Refusal

`./bench/run.sh refuse` offers `minReadLength=10` against a descriptor
requiring `>= 20`. Result:

```
REFUSE raw-reads:trim CONDITION_VIOLATED  minReadLength: 10 violates >= 20
PERMIT raw-reads:qc
```

SEQTK_TRIM never executes; the pipeline stops. The refusal and the conditions
that produced it are in `results/decisions_refuse.jsonl` and are carried
through into the RO-Crate.

### Provenance

[`wrapper/wrroc.py`](wrapper/wrroc.py) emits a Workflow Run RO-Crate from the
Nextflow trace and attaches the gate's decisions to it.

The join is the interesting part. Workflow Run RO-Crate is retrospective — it
describes actions that occurred, as `CreateAction` entities. A refusal has no
`CreateAction`, because nothing ran. Refusals are therefore emitted as
`ControlAction` entities, so one crate shows both what executed and what was
stopped:

```json
{
  "@type": "ControlAction",
  "gateVerdict": "REFUSE",
  "gateDataset": "raw-reads",
  "gateDescriptorVersion": "1.2.0",
  "gateAction": "trim",
  "gateReasonClass": "CONDITION_VIOLATED",
  "gateReasons": ["minReadLength: 10 violates >= 20"],
  "gateConditionsChecked": [
    {"name": "minReadLength", "operator": ">=", "expected": 20,
     "observed": 10, "passed": false},
    {"name": "platform", "operator": "in", "expected": ["illumina"],
     "observed": "illumina", "passed": true}
  ]
}
```

Note that the passing condition is recorded too. A refusal record that lists
only what failed cannot show that the other rules were evaluated.

## Running it

```bash
./bench/run.sh all        # baseline, gated, refusal, then measure
./bench/run.sh baseline   # ungated reference
./bench/run.sh gated      # gate admits every task
./bench/run.sh refuse     # gate refuses SEQTK_TRIM
./bench/run.sh measure    # overhead report from the two traces
```

Nothing is installed system-wide. `toolchain/` holds a portable Temurin JDK 21
and the Nextflow launcher, both fetched into the repo.

### Environment notes

Three real obstacles were hit getting this to run, all recorded because they
cost time and will recur:

1. **Nextflow 26.04 writes `.command.run` without an execute bit** and
   `nf-core/demo` 1.0.1's config fails its strict parser. Pinned to
   `NXF_VER=24.10.5`, which is the right call for a reproducible artifact
   regardless.
2. **Rootless podman on SELinux** needs the work-directory bind mount
   relabelled or every task dies with exit 126 and a misleading
   "Permission denied" that looks like a file-mode problem. Fixed by
   `podman.mountFlags = 'z'` in [`bench/common.config`](bench/common.config).
3. **The work directory cannot live on the external drive.** Removable media
   mounts as SELinux `unlabeled_t` and containers cannot execute from it.
   `bench/run.sh` puts work under `$HOME/.nfgate-work` by default; override
   with `NFGATE_WORK`.

## Honest limits

- **n = 1 per arm.** One baseline and one gated run. Enough to establish that
  the gate's cost is below the trace's resolution; not enough to put a
  confidence interval on the end-to-end difference. Repeated runs are the
  first thing to add.
- **The pipeline is small.** Three processes, three samples, ~20 s of task
  time. It demonstrates the mechanism on real execution; it is not a
  production-scale workload.
- **`wallMicros` excludes interpreter startup.** It is measured inside the
  Python process, so `python3 -m gate` process creation (tens of ms) is not in
  it. The end-to-end trace comparison does include that cost, and still cannot
  resolve it.
- **The descriptors gate public test data.** Conditions have the shape of a
  regulated descriptor applied to data carrying no actual restriction, so that
  anyone can run this.
- **No GA4GH endpoint is involved.** The crate conforms to the Workflow Run
  Crate profile shape but has not been validated against a profile validator,
  and nothing here speaks DRS, TES or WES.

## Why it matters beyond this repo

The "designed, not measured" caveat recurs across several manuscripts —
`dk-electronics-agentic-retrieval-paper` (TKDE), `dk-agentic-twins-paper`,
`dk-etfa-batch-agentic-paper`, `dk-supervisory-admission-gate-paper`. This is
the first place where a descriptor-driven refusal happens inside a real,
third-party, public workflow engine and produces a standards-shaped provenance
record. The harness is domain-agnostic; only `descriptors/` and the
process-to-action mapping in `bench/gate.config` are genomics-specific.
