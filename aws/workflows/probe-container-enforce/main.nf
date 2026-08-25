nextflow.enable.dsl = 2

/*
 * E1d -- does a non-zero `beforeScript` stop a CONTAINERISED task?
 *
 * E1 established that HealthOmics honours `beforeScript` for a task that
 * declares no container. The real gate runs on tasks that declare one, and
 * that is a different question in two ways that matter:
 *
 *   1. Does the directive still run when a container is declared?
 *   2. *Where* does it run -- inside the declared image, or outside it in the
 *      engine's own wrapper? That decides whether the gate's interpreter and
 *      code can be reached at all from the point the decision is made.
 *
 * The image is python:3.12-alpine, chosen as a discriminator: if the
 * beforeScript reports `os_id=alpine` it ran inside the declared container; if
 * it reports anything else it ran outside it. Guessing from documentation is
 * exactly what produced the claim this arm has already falsified once.
 */

process PROBE_CONTAINER_ENFORCE {
    cpus 2
    memory '4 GB'
    container params.image

    // Single-quoted Groovy: $(...) must reach the shell, not be interpolated.
    beforeScript '''
    {
      echo "ran=yes"
      echo "os_id=$( . /etc/os-release 2>/dev/null && echo "$ID" )"
      echo "os_name=$( . /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" )"
      echo "python3=$( command -v python3 || echo none )"
      echo "python3_version=$( python3 --version 2>&1 || echo none )"
      echo "bin_on_path=$( command -v gate_probe.sh || echo none )"
      echo "bin_runs=$( gate_probe.sh 2>/dev/null || echo no )"
      echo "cwd=$( pwd )"
      echo "uname=$( uname -a )"
    } > beforescript.witness 2>&1
    echo refusing-container >&2
    exit 3
    '''

    publishDir params.pubdir

    output:
    path 'enforce.out'

    script:
    """
    # Everything here runs inside the declared container, by definition.
    {
      echo "== task script context (inside the declared image by construction) =="
      echo "script_os_id=\$( . /etc/os-release 2>/dev/null && echo \$ID )"
      echo "script_python3=\$( command -v python3 || echo none )"
      echo "script_bin_on_path=\$( command -v gate_probe.sh || echo none )"
      echo
      echo "== beforeScript witness =="
      if [ -f beforescript.witness ]; then
        cat beforescript.witness
      else
        echo "ran=no    # directive dropped for containerised tasks"
      fi
    } > enforce.out 2>&1
    """
}

workflow {
    PROBE_CONTAINER_ENFORCE()
}
