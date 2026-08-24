nextflow.enable.dsl = 2

/*
 * E1b -- if `beforeScript` executes, does a non-zero exit stop the task?
 *
 * Only meaningful once E1a has returned EXECUTED. Locally this makes the task
 * fail, which is the entire mechanism the artifact measures: the gate exits 3,
 * Nextflow fails the task, the tool never runs.
 *
 * Outcome is read from the RUN, not from a file:
 *   run FAILED    -> the exit status is honoured; per-task refusal works here
 *   run COMPLETED -> the directive ran but its exit status was discarded
 *
 * The second case is the dangerous one and is the reason this is a separate
 * experiment rather than an assumption: a gate whose refusals are swallowed
 * produces a decision log that reads exactly like a compliant run.
 */

process PROBE_ENFORCE {
    cpus 2
    memory '4 GB'

    beforeScript 'echo refusing >&2; exit 3'

    // HealthOmics exports only this prefix. Overridable so the same probe
    // runs locally as a positive control -- an instrument that has never
    // been read against a known answer is not evidence.
    publishDir params.pubdir

    output:
    path 'enforce.out'

    script:
    """
    # Reached only if the non-zero beforeScript did NOT stop the task.
    echo EXIT_STATUS_DISCARDED > enforce.out
    """
}

workflow {
    PROBE_ENFORCE()
}
