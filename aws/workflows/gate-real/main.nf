nextflow.enable.dsl = 2

/*
 * The real gate, on HealthOmics, per task.
 *
 * Not a probe. This is `gate/` from this repository -- the same package the
 * local arm measures, byte-identical, shipped inside the workflow bundle and
 * invoked from `beforeScript` exactly as it is locally. Only two things change,
 * and both are consequences of the measurement in aws/results/e1c_container.json:
 *
 *   - the module is reached at /mnt/workflow/definition/, because HealthOmics
 *     runs beforeScript INSIDE the task container, where this repository does
 *     not exist;
 *   - it is invoked by absolute path, because the bundle's bin/ is not on PATH
 *     at the time the hook runs.
 *
 * Two processes so that per-task granularity is demonstrable rather than
 * asserted. With minReadLength=30 both are permitted. With 10, QC is still
 * permitted and TRIM is refused -- so a run should show QC completing and TRIM
 * never starting. That is the behaviour a whole-run gate cannot produce.
 */

process GATED_QC {
    cpus 2
    memory '4 GB'
    container params.image

    beforeScript """
    PYTHONPATH=/mnt/workflow/definition python3 -m gate \\
      --descriptors /mnt/workflow/definition/descriptors \\
      --dataset raw-reads --action qc \\
      --log gate-decision.jsonl \\
      --run-id ${params.runLabel} --task GATED_QC \\
      --context platform=illumina
    """

    publishDir params.pubdir, mode: 'copy'

    output:
    path 'qc.done'

    script:
    """
    cp gate-decision.jsonl qc.done
    echo "GATED_QC ran" >> qc.done
    """
}

process GATED_TRIM {
    cpus 2
    memory '4 GB'
    container params.image

    beforeScript """
    PYTHONPATH=/mnt/workflow/definition python3 -m gate \\
      --descriptors /mnt/workflow/definition/descriptors \\
      --dataset raw-reads --action trim \\
      --log gate-decision.jsonl \\
      --run-id ${params.runLabel} --task GATED_TRIM \\
      --context platform=illumina minReadLength=${params.minReadLength}
    """

    publishDir params.pubdir, mode: 'copy'

    input:
    path upstream

    output:
    path 'trim.done'

    script:
    """
    cp gate-decision.jsonl trim.done
    echo "GATED_TRIM ran" >> trim.done
    """
}

workflow {
    // Sequenced deliberately: QC must be able to complete before TRIM is
    // refused, or the refusal proves nothing about granularity.
    GATED_TRIM(GATED_QC())
}
