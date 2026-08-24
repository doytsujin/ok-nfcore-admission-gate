nextflow.enable.dsl = 2

/*
 * E1a -- does AWS HealthOmics execute `process.beforeScript` at all?
 *
 * The directive writes a witness into the task working directory and exits 0,
 * so the run completes whatever the answer is. That matters: a probe that
 * fails when the answer is "no" cannot distinguish "the directive stopped the
 * task" from "the definition was rejected" from "the service had a bad day".
 * This one always produces a verdict in an output file.
 *
 * No `container` directive: HealthOmics runs a task without one in a default
 * container, which keeps this probe free of ECR setup entirely.
 */

process PROBE_OBSERVE {
    cpus 2
    memory '4 GB'

    beforeScript 'echo present > beforescript.witness'

    // HealthOmics exports only this prefix. Overridable so the same probe
    // runs locally as a positive control -- an instrument that has never
    // been read against a known answer is not evidence.
    publishDir params.pubdir

    output:
    path 'probe.out'

    script:
    """
    # beforeScript runs in this same directory when the engine honours it.
    if [ -f beforescript.witness ]; then
        echo EXECUTED > probe.out
    else
        echo DROPPED > probe.out
    fi

    # Recorded so the verdict is readable without the run's own logs, which
    # are the thing whose completeness is in question.
    echo "cwd=\$(pwd)" >> probe.out
    ls -a >> probe.out
    """
}

workflow {
    PROBE_OBSERVE()
}
