"""Probe specifications — one row per directive claim under test.

Each spec generates a complete Nextflow workflow. Keeping them as data rather
than as 23 hand-written directories means the probes are uniform: same output
format, same publishing, same verdict parsing. A bespoke probe per directive
would make a difference in *probe design* indistinguishable from a difference
in *service behaviour*, which is the whole thing being measured.

Every probe writes `key=value` lines to probe.out. `decide()` reads them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Probe:
    name: str
    directive: str          # what goes in the process body
    script: str             # shell emitted into the task script
    decide: Callable[[dict], tuple[str, str]]
    # A directive whose effect is only visible in the engine log rather than in
    # the task's own output.
    needs_engine_log: bool = False
    extra_config: str = ""
    notes: str = ""
    # Probes that need an input, or more than one task, cannot use the plain
    # single-process template.
    process_input: str = ""
    workflow_call: str = ""


def _f(w: dict, k: str, default: str = "") -> str:
    return (w.get(k) or default).strip()


# --- afterScript ------------------------------------------------------------
# Runs after the task script. It cannot be observed from the script that
# precedes it, so it writes directly into the publish directory, which is the
# only surface that outlives the task.
afterscript = Probe(
    name="afterScript",
    # Writes to the workflow-level export path rather than to publishDir:
    # publishDir is Nextflow-managed and is not a writable directory at
    # afterScript time, so the first version of this probe failed the task and
    # produced an ambiguous verdict -- "ran and could not write" is
    # indistinguishable from "did not run" if the task dies either way.
    #
    # `|| true` is load-bearing for the same reason. A probe that can fail the
    # task cannot separate "the directive was honoured and its non-zero exit
    # propagated" from "the directive is unsupported and something else broke".
    directive=('afterScript "mkdir -p ${params.exportdir} 2>/dev/null; '
               'echo ran > ${params.exportdir}/afterscript.witness 2>/dev/null || true"'),
    script='echo "placeholder=1" > probe.out',
    decide=lambda w: (
        ("SUPPORTED", "afterScript executed; witness present in the published output")
        if w.get("_afterscript_witness") else
        ("NOT_SUPPORTED", "afterScript produced no witness in the published output")
    ),
    notes="verdict comes from the presence of a second published file",
)

# --- shell ------------------------------------------------------------------
# Nextflow defaults .command.sh to bash. Setting `shell` should change the
# interpreter, which the script can report from $0.
shell = Probe(
    name="shell",
    # NOT in the process body: `shell` there collides with Nextflow's `shell:`
    # block keyword and fails to compile ("Cannot cast '/bin/sh' to int").
    # Config is also where a real workflow would set it, and HealthOmics
    # documents config selectors as the highest-precedence source.
    directive="",
    extra_config="process { shell = ['/bin/sh', '-eu'] }",
    script='''{
      echo "interpreter=$0"
      echo "bash_version=${BASH_VERSION:-none}"
    } > probe.out''',
    decide=lambda w: (
        ("SUPPORTED", f"interpreter is {_f(w,'interpreter')}, BASH_VERSION={_f(w,'bash_version')}")
        if _f(w, "bash_version") == "none" or "/bin/sh" in _f(w, "interpreter")
        else ("NOT_SUPPORTED",
              f"still bash: interpreter={_f(w,'interpreter')} BASH_VERSION={_f(w,'bash_version')}")
    ),
)

# --- scratch ----------------------------------------------------------------
# With scratch, the task executes in a temporary directory rather than in its
# own work directory. AWS's current documentation says this IS supported, while
# the linter list says it is not -- the direct contradiction that made the whole
# list suspect.
scratch = Probe(
    name="scratch",
    directive="scratch true",
    script='''{
      echo "cwd=$PWD"
      echo "tmpdir=${TMPDIR:-none}"
      echo "in_workdir=$(case "$PWD" in /mnt/workflow/*) echo yes ;; *) echo no ;; esac)"
    } > probe.out''',
    decide=lambda w: (
        ("SUPPORTED", f"executed outside the task work dir: cwd={_f(w,'cwd')}")
        if _f(w, "in_workdir") == "no"
        else ("NOT_SUPPORTED", f"executed in the task work dir: cwd={_f(w,'cwd')}")
    ),
    notes="AWS docs and AWS linter disagree about this one; that is the point",
)

# --- containerOptions -------------------------------------------------------
# A benign option with an observable effect: inject an environment variable and
# have the task report it.
container_options = Probe(
    name="containerOptions",
    directive="containerOptions '-e NFGATE_PROBE=applied'",
    script='''{
      echo "injected=${NFGATE_PROBE:-none}"
    } > probe.out''',
    decide=lambda w: (
        ("SUPPORTED", "container option was applied; env var visible in the task")
        if _f(w, "injected") == "applied"
        else ("NOT_SUPPORTED", f"env var absent: injected={_f(w,'injected')}")
    ),
)

# --- errorStrategy (POSITIVE CONTROL) ---------------------------------------
# NOT on the unsupported list -- AWS documents it as supported. If this probe
# says NOT_SUPPORTED then the harness is wrong, not the service, and no other
# verdict in the run can be trusted.
error_strategy = Probe(
    name="errorStrategy[control]",
    directive="errorStrategy 'retry'\n    maxRetries 1",
    script='''{
      echo "task_attempt=@@GROOVY:task.attempt@@"
    } > probe.out''',
    decide=lambda w: (
        ("SUPPORTED", f"accepted and run completed; task.attempt={_f(w,'task_attempt','1')}")
        if w else ("INCONCLUSIVE", "no output")
    ),
    notes="control: AWS documents this as supported, so it must come back SUPPORTED",
)

PILOT = [afterscript, shell, scratch, container_options, error_strategy]


def _escape(script: str) -> str:
    """Protect the shell from Groovy.

    A Nextflow script block is a Groovy GString: an unescaped `$0` or
    `${BASH_VERSION}` is interpolated at parse time and the workflow fails to
    compile. Every shell `$` is escaped, and the few places that genuinely want
    Groovy use an explicit @@GROOVY:expr@@ marker -- so interpolation is opt-in
    and visible, rather than an accident waiting for a probe that happens to
    mention a variable.
    """
    out = script.replace("$", "\\$")
    while "@@GROOVY:" in out:
        head, _, rest = out.partition("@@GROOVY:")
        expr, _, tail = rest.partition("@@")
        out = head + "${" + expr + "}" + tail
    return out


def render(p: Probe, process_name: str) -> str:
    """Emit a complete single-process workflow for one probe."""
    return f"""nextflow.enable.dsl = 2

/*
 * Audit probe: {p.name}
 *
 * {p.notes or 'Generated from aws/audit/probes.py -- do not edit by hand.'}
 */

process {process_name} {{
    cpus 2
    memory '4 GB'
    container params.image

    {p.directive}

    publishDir params.pubdir, mode: 'copy'
{("    input:" + chr(10) + "    " + p.process_input + chr(10)) if p.process_input else ""}
    output:
    path 'probe.out'

    script:
    \"\"\"
    {_escape(p.script)}
    \"\"\"
}}

workflow {{
    {p.workflow_call.replace("PROC", process_name) if p.workflow_call else process_name + "()"}
}}
"""


CONFIG = """manifest {
    nextflowVersion = '!>=24.04.0'
}

params.pubdir = '/mnt/workflow/pubdir'
params.image  = null

// HealthOmics exports only this prefix for content produced outside a task,
// which is exactly what an afterScript witness is. Overridden locally.
params.exportdir = '/mnt/workflow/output'
"""


# ============================================================================
# Round 2 -- the remaining cleanly testable entries.
#
# Two of these degrade honestly rather than pretend to a verdict they cannot
# reach. `cache` needs a resume to observe a skip and HealthOmics has no
# resume, so the probe can only distinguish "accepted" from "rejected", never
# "honoured". It is reported as ACCEPTED_ONLY, not as SUPPORTED.
# ============================================================================

MARKER = "NFGATE_DEBUG_MARKER_7f3a"

debug = Probe(
    name="debug",
    directive="debug true",
    script=f'''echo "{MARKER}"
    echo "emitted=yes" > probe.out''',
    decide=lambda w: (
        ("SUPPORTED", "task stdout was echoed into the engine log")
        if w.get("_engine_marker") else
        ("NOT_SUPPORTED", "task stdout did not reach the engine log")
    ),
    needs_engine_log=True,
    notes="debug true echoes task stdout into the Nextflow log; verdict is read from there",
)

echo_ = Probe(
    name="echo",
    directive="echo true",
    script=f'''echo "{MARKER}"
    echo "emitted=yes" > probe.out''',
    decide=lambda w: (
        ("SUPPORTED", "deprecated alias honoured; stdout reached the engine log")
        if w.get("_engine_marker") else
        ("NOT_SUPPORTED", "no stdout in the engine log")
    ),
    needs_engine_log=True,
    notes="deprecated alias of debug; removal in a newer engine would show as REJECTED_AT_CREATE",
)

stage_in_mode = Probe(
    name="stageInMode",
    directive="stageInMode 'copy'",
    process_input="path 'staged.cfg'",
    workflow_call='PROC(channel.fromPath("${projectDir}/nextflow.config"))',
    script='''{
      echo "is_symlink=$( [ -L staged.cfg ] && echo yes || echo no )"
      echo "is_file=$( [ -f staged.cfg ] && echo yes || echo no )"
    } > probe.out''',
    decide=lambda w: (
        ("SUPPORTED", "input was copied, not symlinked")
        if _f(w, "is_symlink") == "no" and _f(w, "is_file") == "yes"
        else ("NOT_SUPPORTED", f"input is a symlink: is_symlink={_f(w,'is_symlink')}")
    ),
    notes="needs an input to stage; the workflow stages the bundle's own config",
    extra_config="",
)

store_dir = Probe(
    name="storeDir",
    directive="storeDir \"${params.exportdir}/stored\"",
    script='echo "produced=1" > probe.out',
    decide=lambda w: (
        ("SUPPORTED", "output was written into the storeDir")
        if w.get("_storedir_hit") else
        ("NOT_SUPPORTED", "nothing appeared in the storeDir")
    ),
    notes="verdict from whether the declared output lands under storeDir in the exported tree",
)

conda = Probe(
    name="conda",
    directive="conda 'bioconda::seqtk=1.4'",
    script='''{
      echo "seqtk=$( command -v seqtk || echo none )"
    } > probe.out''',
    decide=lambda w: (
        ("SUPPORTED", "conda environment was provisioned; seqtk present")
        if _f(w, "seqtk", "none") != "none"
        else ("NOT_SUPPORTED", "directive ignored; seqtk absent from the task")
    ),
    notes="HealthOmics tasks have no outbound network, so resolution could not succeed anyway",
)

spack = Probe(
    name="spack",
    directive="spack 'seqtk'",
    script='''{
      echo "seqtk=$( command -v seqtk || echo none )"
    } > probe.out''',
    decide=lambda w: (
        ("SUPPORTED", "spack environment was provisioned; seqtk present")
        if _f(w, "seqtk", "none") != "none"
        else ("NOT_SUPPORTED", "directive ignored; seqtk absent from the task")
    ),
)

cache = Probe(
    name="cache[acceptance-only]",
    directive="cache false",
    script='echo "ran=1" > probe.out',
    decide=lambda w: (
        ("ACCEPTED_ONLY",
         "definition accepted and the run completed; whether the directive is "
         "HONOURED cannot be observed without a resume, which HealthOmics does "
         "not offer")
        if w else ("INCONCLUSIVE", "no output")
    ),
    notes="deliberately cannot reach SUPPORTED; reported as acceptance only",
)

max_forks = Probe(
    name="maxForks",
    directive="maxForks 1",
    process_input="val i",
    workflow_call="PROC(channel.of(1, 2, 3))",
    script='''{
      echo "task=$( date +%s%N )"
    } > probe.out''',
    decide=lambda w: (
        ("SUPPORTED", "tasks did not overlap in time")
        if w.get("_no_overlap") == "yes"
        else ("NOT_SUPPORTED", f"tasks overlapped: {w.get('_overlap_detail','')}")
    ),
    notes="three parallel tasks; verdict from task start/stop times via the API",
)

ROUND2 = [debug, echo_, stage_in_mode, store_dir, conda, spack, cache, max_forks]
ALL = PILOT + ROUND2


# --- controls forced by round 2 ---------------------------------------------
# maxForks: "three tasks did not overlap" only means something if three tasks
# WOULD overlap without the directive. HealthOmics might serialise them anyway.
max_forks_control = Probe(
    name="maxForks[control-no-directive]",
    directive="",
    process_input="val i",
    workflow_call="PROC(channel.of(1, 2, 3))",
    script='''{
      echo "task=$( date +%s%N )"
    } > probe.out''',
    decide=lambda w: (
        ("OVERLAPPED", "tasks ran concurrently without the directive, so the "
                       "maxForks probe can detect a difference")
        if w.get("_no_overlap") == "no" else
        ("NO_OVERLAP", "tasks did not overlap even without maxForks -- the "
                       "maxForks verdict is UNDECIDABLE, not supported")
    ),
    notes="control: without this, a no-overlap result proves nothing",
)

CONTROLS = [max_forks_control]
ALL = ALL + CONTROLS

# stageInMode: "not a symlink" is only evidence if the DEFAULT is a symlink.
# HealthOmics stages from S3 and may copy regardless.
stage_in_mode_control = Probe(
    name="stageInMode[control-no-directive]",
    directive="",
    process_input="path 'staged.cfg'",
    workflow_call='PROC(channel.fromPath("${projectDir}/nextflow.config"))',
    script='''{
      echo "is_symlink=$( [ -L staged.cfg ] && echo yes || echo no )"
      echo "is_file=$( [ -f staged.cfg ] && echo yes || echo no )"
    } > probe.out''',
    decide=lambda w: (
        ("DEFAULT_IS_SYMLINK", "default stages a symlink, so the stageInMode "
                               "probe can detect a difference")
        if _f(w, "is_symlink") == "yes" else
        ("DEFAULT_IS_COPY", "default already copies -- the stageInMode verdict "
                            "is UNDECIDABLE, not supported")
    ),
    notes="control: without this, 'input was copied' proves nothing",
)

# shell: BASH_VERSION=none is only evidence if the DEFAULT sets it.
shell_control = Probe(
    name="shell[control-no-directive]",
    directive="",
    script='''{
      echo "interpreter=$0"
      echo "bash_version=${BASH_VERSION:-none}"
    } > probe.out''',
    decide=lambda w: (
        ("DEFAULT_IS_BASH", "default is bash, so the shell probe can detect a difference")
        if _f(w, "bash_version", "none") != "none" else
        ("DEFAULT_NOT_BASH", "default already lacks BASH_VERSION -- the shell "
                             "verdict is UNDECIDABLE, not supported")
    ),
    notes="control: without this, BASH_VERSION=none proves nothing",
)

CONTROLS = CONTROLS + [stage_in_mode_control, shell_control]
ALL = ALL + [stage_in_mode_control, shell_control]
