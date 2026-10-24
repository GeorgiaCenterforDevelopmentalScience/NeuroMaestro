---
title: Wrapper Scripts & SLURM Submission
---

# Wrapper Scripts & SLURM Submission

This page covers the HPC backend abstraction, how wrapper scripts are generated and what they contain, how the compute node environment is assembled, and how SLURM array jobs and dependency chains are structured.

For configuring SLURM/PBS resource profiles and flag templates, see [HPC Configuration](../configuration/hpc-config.md).

---

## HPC Backend: Adding a New Scheduler

Internally, all scheduler interaction goes through the abstract base class `HPCBackend` in [hpc_utils.py](../../src/neuromaestro/pipeline/utils/hpc_utils.py). The active backend is selected at runtime by `get_hpc_backend()`, which reads `scheduler:` from `hpc_config.yaml` and instantiates the matching class.

To add support for a new scheduler (e.g. LSF):

1. Subclass `HPCBackend` and implement the three abstract methods:

| Method | Responsibility |
|--------|---------------|
| `build_job_args(resources, array_param, wait_jobs, job_name, log_output, log_error)` | Return a `List[str]` of scheduler flags |
| `submit_job(args, wrapper_script)` | Run the submission command; parse and return the job ID string, or `None` on failure |
| `wait_for_jobs(job_ids, polling_interval)` | Poll until all job IDs leave the active state |

2. Register the new class in `get_hpc_backend()`:

```python
elif scheduler == "lsf":
    return LSFBackend(scheduler_cfg)
```

3. Add an `lsf:` block to `hpc_config.yaml` with the corresponding keys (use the existing `slurm:` block as a template).

---

## Wrapper Script Generation

For each task submission the pipeline generates a self-contained bash script written to:

```
{--work}/{project}/log/wrapper/{script_name}_{timestamp}_wrapper.sh
```

`{timestamp}` is in Unix epoch seconds, and `{work_dir}` elsewhere on this page stands for the same `{--work}/{project}` directory. The wrapper is executable (`chmod 755`) and embeds all configuration as shell variables. It is not fully standalone: it sources `wrapper_functions.sh` from the installed package (`$SCRIPT_DIR`), which calls `job_db.py` with Python for logging. The compute node therefore needs access to the package directory and a Python environment (set up by `global_python`), besides bash and the analysis tools.

### What the wrapper contains

```bash
#!/bin/bash

# ── Paths ────────────────────────────────────────────────────────────────────
export SUBJECTS='001 002 003'
export INPUT_DIR='/data/BIDS'
export OUTPUT_DIR='/data/processed/my_study/AFNI_derivatives'
export WORK_DIR='/data/work/my_study'
export CONTAINER_DIR='/data/containers'
export LOG_DIR='/data/work/my_study/log'
export DB_PATH='/data/work/database/pipeline_jobs.db'
export TASK_NAME='cards_preprocess'
export SCRIPT_DIR='/home/user/NeuroMaestro/src/neuromaestro/pipeline'
export EXECUTION_ID='1735732800000'

# ── Global Python environment (from global_python in project config) ──────────
export GLOBAL_PYTHON_COMMANDS=$(cat << "PYTHON_EOF"
source /etc/profile.d/modules.sh
ml Python/3.11.3-GCCcore-12.3.0
. /home/user/venv/bin/activate
PYTHON_EOF
)

# ── Module load commands (from modules section, resolved via environ) ─────────
export ENV_COMMANDS=$(cat << "ENV_EOF"
ml Flask/2.3.3-GCCcore-12.3.0
ml netpbm/10.73.43-GCC-12.3.0
ml AFNI/24.3.06-foss-2023a
ENV_EOF
)

# ── Global variables (envir_dir.*, session, prefix, project) ──────────────────
export GLOBAL_ENV_VARS=$(cat << "GENV_EOF"
export CONTAINER_DIR='/data/containers'
export TEMPLATE_DIR='/data/templates'
export FREESURFER_DIR='/data/freesurfer'
export STIMULUS_DIR='/data/stimulus'
export SESSION='01'
export PREFIX='sub-'
export PROJECT='my_study'
GENV_EOF
)

# ── Task-specific parameters (from the merged cards_preprocess config) ────────
export TASK_PARAMS=$(cat << "TASK_EOF"
export STAGE='prep'
export MULTI_STAGE='True'
export REMOVE_TRS='2'
export TEMPLATE='HaskinsPeds_NL_template1.0_SSW.nii'
export BLUR_SIZE='4.0'
export CENSOR_MOTION='0.3'
export CENSOR_OUTLIERS='0.05'
TASK_EOF
)

# ── Entry point ───────────────────────────────────────────────────────────────
source "$SCRIPT_DIR/utils/wrapper_functions.sh"
execute_wrapper "/abs/path/to/scripts/afni_cards_preprocessing.sh"
```

### Parameter → environment variable mapping

The pipeline converts each task parameter key to `UPPER_SNAKE_CASE`:

| Config key | Environment variable |
|------------|----------------------|
| `remove_TRs` | `$REMOVE_TRS` |
| `blur_size` | `$BLUR_SIZE` |
| `censor_motion` | `$CENSOR_MOTION` |
| `template` | `$TEMPLATE` |

Keys consumed by the pipeline itself and **not** exported: `name`, `environ`, `scripts`, `input_from`, `profile`, `array`, `output_pattern`. Every other key of the merged task config is exported, including `stage` and `multi_stage` from `config.yaml` (as `$STAGE` and `$MULTI_STAGE`).

### `input_from` → `INPUT_DIR` substitution

When a task declares `input_from: <upstream_task>` in `config.yaml`, the pipeline may override the wrapper's `$INPUT_DIR` to point at the upstream task's output directory instead of the `--input` CLI value.

The substitution logic in `submit_slurm_job()` ([hpc_utils.py](../../src/neuromaestro/pipeline/utils/hpc_utils.py)):

```python
actual_input_dir = input_dir   # default: the --input CLI value

if task_config and 'input_from' in task_config:
    input_from = task_config['input_from']
    if requested_tasks and input_from in requested_tasks:   # ← key condition
        upstream_config = find_task_config_by_name(input_from)
        if upstream_config and 'output_pattern' in upstream_config:
            actual_input_dir = upstream_config['output_pattern'].format(base_output=output_dir)
```

**The substitution only fires when the upstream task is in `requested_tasks` for the current invocation.** `requested_tasks` is the flat list of task names built from the CLI flags of that specific `neuromaestro run` call.

**Worked example — `rest_post`:**

| Scenario | `requested_tasks` | `input_from` in list? | `$INPUT_DIR` set to |
|----------|------------------|----------------------|---------------------|
| `--bids-prep rest --bids-post rest` | `[rest_preprocess, rest_post]` | Yes | `{output_dir}/BIDS_derivatives/fmriprep` ✓ |
| `--bids-post rest` alone | `[rest_post]` | No | `--input` value (e.g. `/data/BIDS`) ✗ |

In the second scenario, `rest_post` silently receives the raw BIDS directory as its input instead of the fMRIPrep output. The scripts will fail or process the wrong data. **Either include `--bids-prep` and `--bids-post` in the same `neuromaestro run` call, or point `--input` at the upstream output** (e.g. `/data/processed/my_study/BIDS_derivatives/fmriprep`). The same applies to `dwi_post`/`dwi_preprocess` and any other post task. The substitution adds no dependency edge of its own: a post task waits for its prep task only when both are in the same call.

This is a known limitation of the current implementation: the substitution is scoped to a single invocation rather than resolved globally from `config.yaml` regardless of what was requested.

### `wrapper_sections` dict

`create_wrapper_script()` returns a `(wrapper_path, sections)` tuple. The `sections` dict captures each logical block of the wrapper as a separate string (`full_content`, `slurm_cmd`, `basic_paths`, `global_python`, `env_modules`, `global_env_vars`, `task_params`, `execute_cmd`). This dict is immediately passed to `log_wrapper_script()` to be written to JSONL and later merged into the `wrapper_scripts` SQLite table, so the exact submission can always be reconstructed from the database without re-reading the file on disk.

---

## Compute Node Environment Setup

When the wrapper runs on a compute node, `wrapper_functions.sh` builds a **temporary environment file** with `mktemp` (under `umask 077`) in `$TMPDIR`, or `/tmp` when `$TMPDIR` is unset, sources it, and deletes it right away:

```
${TMPDIR:-/tmp}/neuromaestro_env.XXXXXXXXXX
```

The environment is assembled in this order:

```
1. source /etc/profile.d/modules.sh   ← from $GLOBAL_PYTHON_COMMANDS
   ml Python/3.11.3-GCCcore-12.3.0
   . /home/user/venv/bin/activate

2. ml AFNI/24.3.06-foss-2023a         ← from $ENV_COMMANDS (modules named in the task's environ)

3. export PYTHONNOUSERSITE=1          ← Python isolation, re-applied after the environment setup
   unset PYTHONPATH

4. export SUBJECT_ID='001'            ← computed at runtime from the array index
   export INPUT_DIR=... OUTPUT_DIR=... WORK_DIR=... DB_PATH=... SESSION=...
   export LOG_PATH="{work_dir}/log/{task}/sub-{subject}/{task}_{job_id}_{array_task_id}_{timestamp}.log"

5. export CONTAINER_DIR='...'         ← from $GLOBAL_ENV_VARS
   export PREFIX='sub-'
   ...

6. export REMOVE_TRS='2'              ← from $TASK_PARAMS
   export BLUR_SIZE='4.0'
   ...
```

After sourcing the env file, `wrapper_functions.sh` calls the analysis script, appending its output to `$LOG_PATH` (a `.py` script is run with `python` instead of `bash`):

```bash
bash "/abs/path/to/scripts/afni_cards_preprocessing.sh" "$SUBJECT_ID"
```

The script receives the subject ID as `$1`; everything else comes through the environment.

### How JSONL events are written on compute nodes

The logging functions (`log_start`, `log_end`, `log_command_output`) are **not imported as a Python library** on compute nodes. `wrapper_functions.sh` calls them as CLI commands:

```bash
python3 "$SCRIPT_DIR/utils/job_db.py" log_start \
    "$subject" "$task_name" --log-file-path "$LOG_PATH" \
    --job-id "$full_job_id" --session "$SESSION" --db-path "$DB_PATH"
```

`$full_job_id` is `{array_job_id}_{array_task_id}` for an array task and the plain job ID otherwise. This means the compute node must reach the installed package directory and run a Python that can import the package's dependencies (such as `typer`), which is why `$GLOBAL_PYTHON_COMMANDS` (the `module load` + `activate` block) is sourced first. The `$DB_PATH` variable carries the SQLite path, but `log_start` and `log_end` **only write JSONL files** next to it (under `json/`). They never open or write to the SQLite database directly.

---

## SLURM Job Submission

### sbatch command structure

```bash
sbatch \
  --partition=batch \
  --nodes=1 \
  --ntasks=1 \
  --cpus-per-task=16 \
  --time=20:00:00 \
  --job-name=afni_cards_preprocessing \
  --output={work_dir}/log/cards_preprocess/cards_preprocess_%A-%a.out \
  --error={work_dir}/log/cards_preprocess/cards_preprocess_%A-%a.err \
  --mem=32gb \
  --array=1-50%15 \
  --dependency=afterany:12345 \
  {work_dir}/log/wrapper/afni_cards_preprocessing_1735732800_wrapper.sh
```

Key details:

- **`%A`** in log filenames = the array job ID (same for all subjects in one submission)
- **`%a`** = the array task index (1-based, one per subject)
- **`%15`** = maximum 15 subjects running simultaneously (configurable per profile in `hpc_config.yaml` → `resource_profiles.<name>.array_limit`; omit it and no `%N` is emitted)
- **`--dependency=afterany:{job_id}`** is added when a task has upstream dependencies. The downstream job starts after the upstream job reaches any terminal state (completed, failed, or cancelled).

### Non-array jobs

Tasks without `array: true` (e.g. `unzip`, `mriqc_post`, and the staged post tasks) submit a **single job** for all subjects. The log filenames use `%A.out` (no `%a`). The wrapper does not loop over subjects: it runs the script once, with the first subject as `$1` and the full list in `$SUBJECTS`, so a non-array script handles all subjects itself.

### Dependency chaining

The pipeline tracks submitted job IDs in a dict keyed by task name. When a downstream task is about to submit, it collects all upstream job IDs and passes them together:

```
--dependency=afterany:12345:12346:12347
```

This means: "start after **all** upstream jobs have finished (in any state)." The downstream job is not cancelled if an upstream job fails; it always runs once the upstream array completes.

**Multiple intermed tasks (`--intermed volume,bfc`):** `volume` and `bfc` are submitted independently (parallel, no dependency between them). A staged task like `cards_preprocess` collects job IDs from *all* intermed tasks and concatenates them into a single `--dependency=afterany` string, so it waits for every intermed job before starting.
