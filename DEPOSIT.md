# Zenodo deposit sheet — corpus v1.0.0

> **State: ready to upload, nothing deposited yet.** One new record at
> `zenodo.org/uploads/new` (not a new version of the profile record), three
> files attached, two DOIs minted. The archive
> `../nfcore-admission-gate-corpus-v1.0.0.tar.gz` is built from tag `v1.0.0`
> and passes `bench/verify_manifest.py` at 154/154 files. Open choice before
> publishing: reserve the DOI first so the Croissant document can cite its own
> record — see the last section.

Field values for Zenodo's upload form. **Deposit by hand.** Zenodo's GitHub
integration produced no record across five tagged releases of
`ok-croissant-policy-profile` on 2026-08-18, including one carrying no
`.zenodo.json` at all, so the fault is not in what a repository carries; that
repository's `RELEASING.md` holds the evidence. The manual upload worked first
time and is the route here too.

## What goes on the record

| File | Why it is there |
|---|---|
| `nfcore-admission-gate-corpus-v1.0.0.tar.gz` | the corpus: `dataset/`, `runs/replicates/`, `results/replicates/`, `descriptors/` — 154 files, 224 905 bytes, 285 decision records |
| `MANIFEST.json` | loose, so a reader can see every file's SHA-256 and record count without downloading the archive |
| `gate-decisions.croissant.json` | loose, for the same reason: the Croissant description is the machine-readable half of the claim |

Two files are deliberately **not** on the record:

- **`DATASET.md`** — the data descriptor manuscript. The corpus is the data; the
  manuscript is the journal's publication, and JBPE's policy on prior posting is
  the one open item that could not be read. Keeping it out costs nothing and
  keeping it in cannot be undone: metadata on a Zenodo record is editable,
  **files are not**.
- **`LICENSE`** — Apache-2.0, which covers the code. This record is CC-BY-4.0
  and an archive that carries a contradicting licence file is exactly the defect
  the profile deposit shipped with.

The code that produced and analyses the corpus stays in the repository, cited
below as a related identifier rather than copied in under a data licence.

## Fields

| Field | Value |
|---|---|
| Resource type | **Dataset** |
| Title | A corpus of prospective admission decisions from a replicated nf-core workflow |
| Creator | Chernov, Alexander |
| ORCID | 0009-0007-3198-2712 |
| Publication date | 2026-08-18 |
| Version | 1.0.0 |
| Licence | **Creative Commons Attribution 4.0 International** (`cc-by-4.0`) |
| Language | English |

**Description** (paste as written):

> Thirty interleaved replicates of three arms of nf-core/demo v1.0.1 under
> Nextflow 24.10.5 and rootless podman, with a prospective admission gate wired
> into the engine through `process.beforeScript` so that a refused task never
> starts: an ungated baseline, a gated arm in which every task is admitted, and
> a refusal arm in which a declared condition is violated and the trimming step
> is stopped before its container starts.
>
> The corpus is 90 execution traces and 285 admission decision records. Each
> decision record carries the verdict, the descriptor version that produced it,
> the refusal class where applicable, and every condition that was evaluated
> with its expected value, its observed value and whether it passed — including
> the conditions that passed on a request that was refused.
>
> Two claims usually asserted rather than measured are measurable from it. The
> policy decision has a median cost of 11 microseconds while the subprocess that
> delivers it costs 30 milliseconds, a separation of nearly four orders of
> magnitude that only replication made visible. And the refusal is total: the
> trimming step completed zero times in thirty refusal replicates.
>
> Files are listed with SHA-256 and record counts in MANIFEST.json. The Croissant
> description carries a condition requiring the full set of 30 replicates, so a
> consumer reusing a subset is refused rather than quietly computing a different
> interval. Generation and analysis code is in the linked repository under
> Apache-2.0.

**Keywords:** admission control, workflow provenance, nextflow, nf-core, data
governance, reproducibility

**Related identifiers:**

| Identifier | Relation |
|---|---|
| `https://github.com/doytsujin/ok-nfcore-admission-gate/tree/v1.0.0` | is supplement to |
| `10.5281/zenodo.22005283` | references — the policy profile the descriptors are decided against |

## Check the record before walking away

Zenodo's form defaults overwrite every field left untouched. On the profile
deposit four came out wrong: licence defaulted to CC-BY-4.0, version was empty,
publication date was stamped UTC (a day ahead of a late-evening deposit in
Toronto), and the related identifiers were dropped. **Here CC-BY-4.0 is the
right answer and the other three still are not.** Re-read the published record
against this sheet; metadata is editable afterwards, files are not.

## The reserved-DOI option

The document validates under mlcroissant 1.1.0 with two warnings, `citeAs` and
`datePublished`, both recommended rather than required. Both are closable, but
only before publication: Zenodo can **reserve** the version DOI while the upload
is still a draft. Reserve it, pass it to `bench/package_corpus.py`'s emit call as
`cite_as` with `date_published`, regenerate, re-validate, rebuild the archive,
then attach and publish. Afterwards it would take a new version, because files
on a published record are frozen.

## Rebuilding the archive

    git archive --prefix=nfcore-admission-gate-corpus-v1.0.0/ v1.0.0 \
      dataset runs/replicates results/replicates descriptors \
      -o ../nfcore-admission-gate-corpus-v1.0.0.tar.gz

The pathspec is exact, not `runs results`. The decision records live under
`results/replicates/` and the first attempt at this archive omitted the
directory entirely — 60 of the 153 files, caught only because the verifier read
the tarball rather than the tree. The three single-run traces at `runs/*.txt`
are from the earlier n=1 study and stay out: the corpus is the replication, and
an unexplained extra file on a permanent record is worse than an absent one.

`bench/verify_manifest.py` re-hashes every file in the archive against
`MANIFEST.json`; run it before uploading, because the manifest is the record's
integrity claim and a stale one would be published permanently.
