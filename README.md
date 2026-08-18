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

At n=1 the negative numbers read as noise rather than a speedup, and the
conclusion drawn was that the overhead sits below the measurement floor.
**Thirty replicates say that conclusion was half right, and the half that was
wrong is the interesting half.** See the next section.

Either way it is a different and stronger claim than the paper's modelled 3.2%,
because it comes from a clock.

## Replication (n = 30)

`./bench/replicate.sh` runs 30 replicates of all three arms, **interleaved
rather than blocked** — replicate 1 of each arm, then replicate 2 of each — so
that machine state drifting over the hour lands on every arm equally instead of
on whichever arm ran last. `bench/aggregate.py` then pairs by replicate index,
which removes the drift both arms of a replicate share. Numbers from
`results/replication.json`; 90 runs, 285 decision records.

### The microsecond claims replicate

| | published (n=1, 7 decisions) | replicated (210 decisions) |
|---|---:|---:|
| Policy evaluation, median | 11 µs | **11 µs** (mean 10.6, p95 15, max 30) |
| Gate process, median | 122 µs | **119 µs** (mean 127, p95 155, max 260) |

### End to end, the overhead is now resolvable — and it is not the policy

| paired delta, gated − baseline | mean | 95% CI | resolves? |
|---|---:|---:|:--:|
| Per run, task `realtime` total | +0.197 s | [−0.323, +0.716] | no |
| Per run, task `duration` total | +0.180 s | [+0.042, +0.319] | **yes** |
| Per task, `duration` | +25.7 ms | [+3.3, +48.2] | **yes** |
| Per task, `realtime` | +28.1 ms | [−50.0, +106.2] | no |

The two fields agree on the size of the effect and disagree on whether it can
be seen: Nextflow writes `realtime` at one-second granularity and `duration` at
one-tenth, and only the finer one resolves ~26 ms. So the n=1 statement — that
the overhead is below the measurement floor — was a statement about the floor,
not about the overhead.

**What the ~26 ms is.** Not policy evaluation, which is 11 µs. The gate is
deployed as one `python3 -m gate` subprocess per task, and
`bench/subprocess_cost.py` measures that invocation end to end:

| | median |
|---|---:|
| `python3 -m gate`, whole process | **30.2 ms** |
| bare `python3 -c pass` | 9.6 ms |
| the gate's own imports and work | 20.6 ms |

30.2 ms sits inside the [+3.3, +48.2] ms interval the replication measured, so
the per-task delta is accounted for by the mechanism rather than left to
speculation. Against ~2.8 s tasks it is about 0.9%.

The separation is the result worth having. **The decision costs 11 µs; the
decision's delivery costs 30 ms — 2700× more than the thing it delivers.** A
resident gate, or a hook that is not a fresh interpreter, would recover nearly
all of it, and the 11 µs figure says there is nothing else to recover. The
artifact's headline claim survives for the policy engine and fails for the
deployment, which is a distinction the single run could not draw.

### The refusal holds in every replicate

`SEQTK_TRIM` completed **0 times in 30 refusal-arm replicates**. That claim is
not statistical — one counterexample would falsify the whole artifact — so
`bench/aggregate.py` checks it rather than assuming it. The refusal arm produced
37 refusals across 30 runs, all `CONDITION_VIOLATED`, alongside 38 permits;
more than one refusal per run occurs because three samples reach `SEQTK_TRIM`
and Nextflow has submitted the next before the first refusal stops the run.

Refusals cost more than permits inside the gate process — 146 µs median against
119 — because a refusal record carries reasons and the full condition list.

### The corpus

`bench/package_corpus.py` writes `dataset/MANIFEST.json`: every trace, decision
log and descriptor with a SHA-256 and a record count, so a reader can tell
whether the corpus they have is the corpus that was described. It also emits
`dataset/gate-decisions.croissant.json` — the corpus described with the policy
profile from [dk-croissant-policy-profile](../dk-croissant-policy-profile),
which is the cheapest available check that the profile survives contact with a
dataset it was not designed around.

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
./bench/replicate.sh      # 30 replicates of all three arms, interleaved
./bench/aggregate.py      # paired intervals from the replicates
./bench/subprocess_cost.py  # what the gate costs as a process, not a function
./bench/package_corpus.py   # manifest + Croissant description of the corpus
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

- ~~**n = 1 per arm.**~~ Closed: 30 replicates per arm, interleaved and paired.
  It cost the original headline half its claim, which is what replication is
  for.
- **The per-task interval is wide and quantized.** [+3.3, +48.2] ms is a factor
  of fifteen, and the underlying per-task deltas are quantized to Nextflow's
  0.1 s `duration` resolution — 102 of 210 paired tasks show exactly zero, and
  the signal is the asymmetry between 71 tasks at +0.1 s and 19 at −0.1 s. The
  direction and the rough magnitude are sound; the interval should not be read
  as a precise figure.
- **The subprocess cost is machine-specific.** 30.2 ms is this interpreter on
  this host. It is the right order of magnitude for CPython process startup plus
  imports, not a portable constant.
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
