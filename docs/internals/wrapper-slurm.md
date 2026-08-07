---
title: Wrapper Scripts & SLURM Submission
---

# Wrapper Scripts & SLURM Submission

This page covers the HPC backend abstraction, how wrapper scripts are generated and what they contain, how the compute node environment is assembled, and how SLURM array jobs and dependency chains are structured.

For configuring SLURM/PBS resource profiles and flag templates, see [HPC Configuration](../configuration/hpc-config.md).

---

## HPC Backend: Adding a New Scheduler

Internally, all scheduler interaction goes through the abstract base class `HPCBackend` in [hpc_utils.py](../../src/neuro_pipeline/pipeline/utils/hpc_utils.py). The active backend is selected at runtime by `get_hpc_backend()`, which reads `scheduler:` from `hpc_config.yaml` and instantiates the matching class.

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
{work_dir}/log/wrapper/{script_name}_{timestamp}_wrapper.sh
```

The wrapper is executable (`chmod 755`) and embeds all configuration as shell variables so the compute node needs no access to Python or the pipeline source; it only needs bash and the analysis tools.

### What the wrapper contains

```bash
#!/bin/bash

# ── Paths ────────────────────────────────────────────────────────────────────
export SUBJECTS='001 002 003'
export INPUT_DIR='/data/BIDS'
export OUTPUT_DIR='/data/processed/my_study'
export WORK_DIR='/data/work/my_study'
export LOG_DIR='/data/work/my_study/log'
export DB_PATH='/data/work/my_study/database/pipeline_jobs.db'
export TASK_NAME='flanker_preprocess'
export SCRIPT_DIR='/home/user/GCDS_Neuro_Pipeline/src/neuro_pipeline/pipeline'

# ── Global Python environment (from global_python in project config) ──────────
export GLOBAL_PYTHON_COMMANDS=$(cat << "PYTHON_EOF"
source /etc/profile.d/modules.sh
ml Python/3.11.3-GCCcore-12.3.0
. /home/user/venv/bin/activate
PYTHON_EOF
)

# ── Module load commands (from modules section, resolved via environ) ─────────
export ENV_COMMANDS=$(cat << "ENV_EOF"
ml AFNI/25.1.01-foss-2023a
ENV_EOF
)

# ── Global variables (prefix, project, envir_dir.*) ──────────────────────────
export GLOBAL_ENV_VARS=$(cat << "GENV_EOF"
export PREFIX='sub-'
export PROJECT='my_study'
export SESSION='01'
export TEMPLATE_DIR='/work/cglab/projects/my_study/templates'
export CONTAINER_DIR='/work/cglab/containers'
export FREESURFER_DIR='/work/cglab/freesurfer'
GENV_EOF
)

# ── Task-specific parameters (from tasks.flanker_preprocess) ──────────────────
export TASK_PARAMS=$(cat << "TASK_EOF"
export REMOVE_TRS='4'
export TEMPLATE='HaskinsPeds_NL_template1.0_SSW.nii'
export BLUR_SIZE='4.0'
export CENSOR_MOTION='0.3'
export CENSOR_OUTLIERS='0.05'
TASK_EOF
)

# ── Entry point ───────────────────────────────────────────────────────────────
source "$SCRIPT_DIR/utils/wrapper_functions.sh"
execute_wrapper "/abs/path/to/scripts/branch/afni_flanker_preprocess.sh"
```

### Parameter → environment variable mapping

The pipeline converts each task parameter key to `UPPER_SNAKE_CASE`:

| Config key | Environment variable |
|------------|----------------------|
| `remove_TRs` | `$REMOVE_TRS` |
| `blur_size` | `$BLUR_SIZE` |
| `censor_motion` | `$CENSOR_MOTION` |
| `template` | `$TEMPLATE` |

Keys consumed by the pipeline itself and **not** exported: `name`, `environ`, `scripts`, `input_from`, `profile`, `array`, `output_pattern`.

### `input_from` → `INPUT_DIR` substitution

When a task declares `input_from: <upstream_task>` in `config.yaml`, the pipeline may override the wrapper's `$INPUT_DIR` to point at the upstream task's output directory instead of the `--input` CLI value.

The substitution logic in `submit_slurm_job()` ([hpc_utils.py](../../src/neuro_pipeline/pipeline/utils/hpc_utils.py)):

```python
actual_input_dir = input_dir   # default: the --input CLI value

if task_config and 'input_from' in task_config:
    input_from = task_config['input_from']
    if requested_tasks and input_from in requested_tasks:   # ← key condition
        upstream_config = find_task_config_by_name(input_from)
        if upstream_config and 'output_pattern' in upstream_config:
            actual_input_dir = upstream_config['output_pattern'].format(base_output=output_dir)
```

**The substitution only fires when the upstream task is in `requested_tasks` for the current invocation.** `requested_tasks` is the flat list of task names built from the CLI flags of that specific `neuropipe run` call.

**Worked example — `rest_post`:**

| Scenario | `requested_tasks` | `input_from` in list? | `$INPUT_DIR` set to |
|----------|------------------|----------------------|---------------------|
| `--bids-prep rest --bids-post rest` | `[rest_preprocess, rest_post]` | Yes | `{output_dir}/BIDS_derivatives/fmriprep` ✓ |
| `--bids-post rest` alone | `[rest_post]` | No | `--input` value (e.g. `/data/BIDS`) ✗ |

In the second scenario, `rest_post` silently receives the raw BIDS directory as its input instead of the fMRIPrep output. The scripts will fail or process the wrong data. **Always include `--bids-prep` and `--bids-post` in the same `neuropipe run` call.** The same applies to `dwi_post`/`dwi_preprocess` and any other post task.

This is a known limitation of the current implementation: the substitution is scoped to a single invocation rather than resolved globally from `config.yaml` regardless of what was requested.

### `wrapper_sections` dict

`create_wrapper_script()` returns a `(wrapper_path, sections)` tuple. The `sections` dict captures each logical block of the wrapper as a separate string (`full_content`, `slurm_cmd`, `basic_paths`, `global_python`, `env_modules`, `global_env_vars`, `task_params`, `execute_cmd`). This dict is immediately passed to `log_wrapper_script()` to be written to JSONL and later merged into the `wrapper_scripts` SQLite table, so the exact submission can always be reconstructed from the database without re-reading the file on disk.

---

## Compute Node Environment Setup

When the wrapper runs on a compute node, `wrapper_functions.sh` builds a **temporary environment file** in `/tmp` and sources it:

```
/tmp/env_{TASK_NAME}_{SLURM_JOB_ID}_{SLURM_ARRAY_TASK_ID}_{subject}_{RANDOM}.sh
```

The environment is assembled in this order:

```
1. source /etc/profile.d/modules.sh   ← from $GLOBAL_PYTHON_COMMANDS
   ml Python/3.11.3-GCCcore-12.3.0
   . /home/user/venv/bin/activate

2. ml AFNI/25.1.01-foss-2023a         ← from $ENV_COMMANDS (modules.environ)

3. export PREFIX='sub-'               ← from $GLOBAL_ENV_VARS
   export TEMPLATE_DIR='...'
   ...

4. export REMOVE_TRS='4'              ← from $TASK_PARAMS
   export BLUR_SIZE='4.0'
   ...

5. export SUBJECT_ID='001'            ← computed at runtime from array index
   export SLURM_ARRAY_TASK_ID=...
   export LOG_PATH="{work_dir}/log/{task}/sub-{subject}/{task}_{job_id}_{array_task_id}_{timestamp}.log"
```

After sourcing the env file, `wrapper_functions.sh` calls the analysis script:

```bash
bash "/abs/path/to/scripts/branch/afni_flanker_preprocess.sh" "$SUBJECT_ID"
```

The script receives the subject ID as `$1`; everything else comes through the environment.

### How JSONL events are written on compute nodes

The logging functions (`log_start`, `log_end`, `log_command_output`) are **not imported as a Python library** on compute nodes. `wrapper_functions.sh` calls them as CLI commands:

```bash
python -m neuro_pipeline.pipeline.utils.job_db log_start \
    "$SUBJECT_ID" "$TASK_NAME" --session "$SESSION" \
    --job-id "$SLURM_JOB_ID" --db-path "$DB_PATH"
```

This means the compute node must have Python and the `neuro_pipeline` package available — which is why `$GLOBAL_PYTHON_COMMANDS` (the `module load` + `activate` block) is sourced first. The `$DB_PATH` variable carries the SQLite path, but `log_start` and `log_end` **only write JSONL files** at that location — they never open or write to the SQLite database directly.

---

## SLURM Job Submission

### sbatch command structure

```bash
sbatch \
  --partition=batch \
  --nodes=1 \
  --ntasks=1 \
  --cpus-per-task=16 \
  --mem=64G \
  --time=48:00:00 \
  --job-name=afni_flanker_preprocess \
  --output={work_dir}/log/flanker_preprocess/flanker_preprocess_%A-%a.out \
  --error={work_dir}/log/flanker_preprocess/flanker_preprocess_%A-%a.err \
  --array=1-50%15 \
  --dependency=afterany:12345 \
  {work_dir}/log/wrapper/afni_flanker_preprocess_20250101_120000_wrapper.sh
```

Key details:

- **`%A`** in log filenames = the array job ID (same for all subjects in one submission)
- **`%a`** = the array task index (1-based, one per subject)
- **`%15`** = maximum 15 subjects running simultaneously (configurable per profile in `hpc_config.yaml` → `resource_profiles.<name>.array_limit`; omit it and no `%N` is emitted)
- **`--dependency=afterany:{job_id}`** is added when a task has upstream dependencies. The downstream job starts after the upstream job reaches any terminal state (completed, failed, or cancelled).

### Non-array jobs

Tasks with `array: false` (e.g. `mriqc_post`, `recon`) submit a **single job** for all subjects. The log filenames use `%A.out` (no `%a`). The wrapper iterates over subjects internally.

### Dependency chaining

The pipeline tracks submitted job IDs in a dict keyed by task name. When a downstream task is about to submit, it collects all upstream job IDs and passes them together:

```
--dependency=afterany:12345:12346:12347
```

This means: "start after **all** upstream jobs have finished (in any state)." The downstream job is not cancelled if an upstream job fails; it always runs once the upstream array completes.

**Multiple intermed tasks (`--intermed volume,bfc`):** `volume` and `bfc` are submitted independently (parallel, no dependency between them). A staged task like `cards_preprocess` collects job IDs from *all* intermed tasks and concatenates them into a single `--dependency=afterany` string, so it waits for every intermed job before starting.
