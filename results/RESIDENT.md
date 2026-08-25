# The resident gate — measured

Three arms, **interleaved and paired by replicate index**, n = 30 each, 90 runs,
2026-08-25. Baseline, subprocess gate (`python3 -m gate` per task), resident
gate (daemon + bash `/dev/tcp` client). Nextflow 24.10.5, rootless podman,
`nf-core/demo` 1.0.1.

## Result

Paired per-task `duration` delta against the same baseline replicates,
n = 210 tasks:

| Arm | Per-task delta | 95% CI | Resolves? |
|---|---|---|---|
| Subprocess gate | **+51.0 ms** | [+30.1, +71.8] | yes |
| Resident gate | **+30.5 ms** | [−0.7, +61.6] | **no** |

Gate-internal figures from the decision records themselves:

| | Subprocess | Resident |
|---|---|---|
| Policy evaluation, median | 17 µs | 27 µs |
| Gate wall time in-process, median | 155 µs | **48 µs** |

## Reading, and it is not the one the artifact predicted

**The resident gate removes about 20 ms per task and leaves about 30 ms.**
20 ms is close to the independently measured cost of creating a `python3`
process on this host (30.2 ms median, bare interpreter 9.6 ms), so the part
that was attributed to interpreter startup is the part that went away. That
much is consistent.

**But the artifact has asserted since the replication that "a resident gate
recovers nearly all of it". That is not what happened.** Roughly 40% of the
per-task delta was recovered, not nearly all. The remaining +30.5 ms is *not*
the interpreter and is currently unexplained — candidates are the added
`beforeScript` itself (an extra shell body Nextflow must write and execute per
task, present in both gated arms) and socket setup, neither of which has been
isolated.

The claim that should be made is the weaker, supported one: **the resident gate
reduces the per-task cost enough that it no longer resolves at n = 30.** Its
interval includes zero; the subprocess arm's does not. For a deployment that is
the operative difference. For an explanation it is not, and the residual should
be stated as open rather than assumed to be noise.

## A between-session discrepancy that has to be reported

The subprocess arm measured **+25.7 ms** on 2026-08-18 and **+51.0 ms** today,
on the same host, same pipeline, same harness. Every gate-internal figure moved
the same way — policy evaluation 11 → 17 µs, gate process 119 → 155 µs — so the
machine was systematically slower today rather than the gate being different.

**Consequence: the absolute millisecond figure is not a property of the gate.**
It is a property of the gate on a host on a day. Only the *within-sweep*
comparison is valid, because only there are the arms interleaved against a
shared baseline. Any cross-session comparison of these numbers — including
comparing today's +51.0 ms against the published +25.7 ms — is measuring the
session.

This is why the arms are interleaved rather than blocked, and it is the second
time this artifact's headline number has moved when the sample changed. The
first cost it the "below the measurement floor" claim. Both times the fix was
more replication, and both times the corrected claim was narrower.

## Sources

`results/replication_2026-08-25.json` (subprocess),
`results/replication_resident.json` (resident),
`results/replicates/decisions_resident.jsonl` (210 records, all
`transport: resident`). The earlier figures remain in
`results/replication.json` and are not overwritten.
