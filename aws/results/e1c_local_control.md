# E1c/E1d — local positive control (containerised)

Run 2026-08-24 under the repository's Nextflow 24.10.5 with rootless podman,
image `docker.io/library/python:3.12-slim`, host Rocky Linux 10.2
(`capistrano`).

## E1c — observation

```
== task script context (inside the declared image by construction) ==
script_os_id=debian
script_python3=/usr/local/bin/python3
script_bin_on_path=.../probe-container-observe/bin/gate_probe.sh

== beforeScript witness ==
ran=yes
os_id=rocky
os_name=Rocky Linux 10.2 (Red Quartz)
python3=/usr/bin/python3
python3_version=Python 3.12.13
bin_on_path=none
bin_runs=no
cwd=$HOME/.nfgate-work/e1c-control/work/64/b22c72e12a0ff404b8ea99b2cbeda0
uname=Linux capistrano ... x86_64 GNU/Linux
```

**Reference behaviour, and the thing worth naming:** `beforeScript` runs on the
**host**, outside the declared container — Rocky, host kernel, host
`/usr/bin/python3` — while the task script runs **inside** it (debian,
`/usr/local/bin/python3`). Two different execution contexts in one task.

That is exactly why the local gate works as written: `python3 -m gate` with
`PYTHONPATH` pointing at the repository resolves against the *host* interpreter
and the *host* filesystem. A gate written this way is not portable to any engine
that runs `beforeScript` inside the task container instead, because neither the
interpreter path nor the module would be there.

Note also `bin_on_path=none` in the beforeScript context while the task script
sees the bundle's `bin/` on its PATH. Nextflow's `bin/` injection reaches the
container, not the host-side hook.

## E1d — enforcement

Nextflow exit 1, `enforce.out` absent: a non-zero `beforeScript` stops a
containerised task before its script runs, the same as for an uncontainerised
one.

## Why this control exists

The uncontainerised E1 result cannot answer the question this one asks. Running
the probes here first fixed two defects that would otherwise have been read as
findings on AWS: Alpine has no `/bin/bash` for Nextflow's `.command.sh`, and an
unset `$IMAGE` under `bash -ue` aborts the task before its output exists. Both
would have surfaced as a failed HealthOmics run.
