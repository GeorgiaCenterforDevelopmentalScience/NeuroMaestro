---
title: Project Configuration
---

# Project Configuration

Each study has its own **project config file**: `{project}_config.yaml`, stored in `config/project_config/`. You specify which project to use with `--project my_study`, and the pipeline loads `my_study_config.yaml` automatically.

A complete annotated example follows.

## Complete Example

:::{dropdown} View full example config (branch_config.yaml)
```yaml
# 1. branch_config.yaml — BRANCH study project configuration

prefix: "sub-"               # Subject directory prefix (always "sub-" for BIDS)
scripts_dir: "scripts/branch"  # Relative (to pipeline/) or absolute path to your scripts

database:
  db_path: "$WORK_DIR/database/pipeline_jobs.db"

# 2. envir_dir paths become $UPPERCASE env vars in every wrapper script
envir_dir:
  container_dir: "/work/cglab/containers"
  virtual_envir: "/work/cglab/conda_env"
  template_dir: "/work/cglab/projects/BRANCH/all_data/for_AFNI/"
  atlas_dir: "/work/cglab/projects/BRANCH/all_data/for_AFNI/"
  freesurfer_dir: "/work/cglab/containers/.licenses/freesurfer"
  config_dir: "/work/cglab/conda_env/config_for_BIDS"
  stimulus_dir: "/work/cglab/projects/BRANCH/all_data/for_AFNI/processing_scripts"

# 3. Loaded on every compute node before the task runs (used for database logging)
global_python:
  - ml Python/3.11.3-GCCcore-12.3.0
  - . /home/$USER/virtual_environ/neuro_pipeline/bin/activate

# 4. Named module sets; tasks reference them by name via their `environ` field
modules:

  afni_24.3.06:
    - ml Flask/2.3.3-GCCcore-12.3.0
    - ml netpbm/10.73.43-GCC-12.3.0
    - ml AFNI/24.3.06-foss-2023a

  fsl_6.0.7.14:
    - ml FSL/6.0.7.14-foss-2023a
    - '[ -n "$FSLDIR" ] && source ${FSLDIR}/etc/fslconf/fsl.sh'

  freesurfer_7.4.1:
    - ml FreeSurfer/7.4.1-GCCcore-12.3.0

  data_manage_1:
    - ml p7zip/17.05-GCCcore-13.3.0
    - ml parallel/20240722-GCCcore-13.3.0

# 5. Keyed by task name (must match names in config.yaml)

tasks:

  unzip:
    environ: ["data_manage_1", "afni_24.3.06"]

  recon:
    container: "dcm2bids_3.2.0.sif"
    config: "branch_config.json"

  volume:
    environ: ["afni_24.3.06"]
    template: "HaskinsPeds_NL_template1.0_SSW.nii"

  rest_preprocess:
    remove_TRs: 6
    template: "MNI152NLin2009cAsym"
    container: "fmriprep_25.1.3.sif"
    license: "license.txt"

  rest_post:
    remove_TRs: 6
    template: "MNI152NLin2009cAsym"
    container: "xcp_d-0.11.0rc1.sif"
    rest_mode: "abcd"
    motion_filter_type: "notch"
    band_stop_min: "15"
    band_stop_max: "25"
    nuisance_regressors: "36P"
    license: "license.txt"

  cards_preprocess:
    remove_TRs: 2
    template: "HaskinsPeds_NL_template1.0_SSW.nii"
    blur_size: 4.0
    environ: ["afni_24.3.06"]
    censor_motion: "0.3"
    censor_outliers: "0.05"

  kidvid_preprocess:
    remove_TRs: 22
    template: "HaskinsPeds_NL_template1.0_SSW.nii"
    blur_size: 4.0
    environ: ["afni_24.3.06"]
    censor_motion: "0.3"
    censor_outliers: "0.05"

  dwi_preprocess:
    environ: ["fsl_6.0.7.14"]
    container: "qsiprep-1.0.0.sif"
    license: "license.txt"

  dwi_post:
    environ: ["fsl_6.0.7.14"]

  mriqc_preprocess:
    container: "mriqc_24.0.2.sif"

  mriqc_post:
    container: "mriqc_24.0.2.sif"
```
:::

## Field Reference

### `prefix`
Subject directory prefix. Almost always `"sub-"` for BIDS datasets.

### `scripts_dir`
Directory where your project's shell scripts live. Two forms are accepted:

- **Relative path** — resolved relative to `src/neuro_pipeline/pipeline/`. Use this when scripts are stored inside the package (default for bundled projects):
  ```yaml
  scripts_dir: "scripts/branch"   # → src/neuro_pipeline/pipeline/scripts/branch/
  ```
- **Absolute path** — use this when scripts live outside the package, e.g. on a shared lab directory:
  ```yaml
  scripts_dir: "/scratch/cglab/projects/my_study/scripts"
  ```

If the script is not found the error message shows the resolved full path so you can diagnose the problem immediately.

### `envir_dir`
All paths become `$UPPERCASE_ENV_VARS` inside wrapper scripts:

| Field | Env var | Purpose |
|-------|---------|---------|
| `container_dir` | `$CONTAINER_DIR` | Singularity `.sif` files |
| `virtual_envir` | `$VIRTUAL_ENVIR` | Conda/venv base |
| `template_dir` | `$TEMPLATE_DIR` | MRI templates and atlases |
| `atlas_dir` | `$ATLAS_DIR` | Parcellation atlases |
| `freesurfer_dir` | `$FREESURFER_DIR` | FreeSurfer license |
| `config_dir` | `$CONFIG_DIR` | BIDS conversion configs |
| `stimulus_dir` | `$STIMULUS_DIR` | Task timing/stimulus files |

### `global_python`
Shell commands run on the compute node before every task, used to activate the Python environment for database logging. Needs: `typer`, `pandas`, `sqlite3`.

### `modules`
Named groups of `module load` commands. Reference them by name in `tasks.<name>.environ`. This way you define module versions once and reuse them across tasks.

### `tasks`
Task-specific parameters keyed by task name. The key must exactly match a task `name` defined in `config.yaml`.

Common per-task fields:

| Field | Description |
|-------|-------------|
| `environ` | List of module group names to load |
| `container` | Singularity `.sif` filename (looked up in `container_dir`) |
| `license` | License file (e.g., FreeSurfer) relative to `freesurfer_dir` |
| `template` | Template filename (looked up in `template_dir`) |
| `remove_TRs` | Number of dummy TRs to drop at the start |
| `blur_size` | Smoothing kernel FWHM in mm |
| `censor_motion` | Motion threshold for censoring (mm) |
| `censor_outliers` | Outlier voxel fraction threshold |

:::{important}
**All fields are exported as `$UPPERCASE` environment variables in the wrapper script and are accessible inside your shell scripts.**
:::

:::{note}
The field names under `envir_dir:` and `tasks:` are not hardcoded — you can add or rename them freely. Every key you define becomes a `$UPPERCASE` variable available in your analysis scripts. The pipeline does not care what you call them; it just uppercases every key and exports it. Your scripts are responsible for using the variable names that match what you put in the config.
:::

## How `tasks` and `modules` Relate

```
tasks.cards_preprocess.environ = ["afni_24.3.06"]
        ↓
modules.afni_24.3.06 = [ml Flask/..., ml netpbm/..., ml AFNI/...]
        ↓
Wrapper script: runs those module commands before executing the analysis script
```

This indirection lets you update the AFNI version in one place (`modules`) and have all tasks pick it up automatically.

---

## End-to-End Example: `cards_preprocess`

This section traces exactly how config values flow from `branch_config.yaml` into your analysis script.

### 1. Config entries (branch_config.yaml)

```yaml
envir_dir:
  container_dir: "/work/cglab/containers"
  template_dir:  "/work/cglab/projects/BRANCH/all_data/for_AFNI/"

modules:
  afni_24.3.06:
    - ml Flask/2.3.3-GCCcore-12.3.0
    - ml netpbm/10.73.43-GCC-12.3.0
    - ml AFNI/24.3.06-foss-2023a

tasks:
  cards_preprocess:
    remove_TRs: 2
    template:   "HaskinsPeds_NL_template1.0_SSW.nii"
    blur_size:  4.0
    environ:    ["afni_24.3.06"]
    censor_motion:    "0.3"
    censor_outliers:  "0.05"
```

### 2. Generated wrapper script (auto-created per submission)

The pipeline writes a temporary wrapper in `$WORK_DIR/log/wrapper/` before calling `sbatch`. You normally never need to read this file; it exists for debugging and reproducibility records.

:::{dropdown} View example wrapper script
```bash
#!/bin/bash
# Auto-generated wrapper script — cards_preprocess
# Submission Command:
# sbatch --partition=general ... cards_preprocess_1234567890_wrapper.sh

# Standard paths (always present)
export SUBJECTS='001 002 003 ...'
export INPUT_DIR='/work/cglab/BRANCH/BIDS'
export OUTPUT_DIR='/work/cglab/BRANCH/derivatives'
export WORK_DIR='/work/cglab/BRANCH'
export CONTAINER_DIR='/work/cglab/containers'
export LOG_DIR='/work/cglab/BRANCH/log'
export DB_PATH='/work/cglab/BRANCH/database/pipeline_jobs.db'
export TASK_NAME='cards_preprocess'

# Global Python (for database logging)
export GLOBAL_PYTHON_COMMANDS=$(cat << "PYTHON_EOF"
ml Python/3.11.3-GCCcore-12.3.0
. /home/$USER/virtual_environ/neuro_pipeline/bin/activate
PYTHON_EOF
)

# Module load commands (from modules.afni_24.3.06)
export ENV_COMMANDS=$(cat << "ENV_EOF"
ml Flask/2.3.3-GCCcore-12.3.0
ml netpbm/10.73.43-GCC-12.3.0
ml AFNI/24.3.06-foss-2023a
ENV_EOF
)

# envir_dir paths
export GLOBAL_ENV_VARS=$(cat << "GENV_EOF"
export CONTAINER_DIR='/work/cglab/containers'
export TEMPLATE_DIR='/work/cglab/projects/BRANCH/all_data/for_AFNI/'
...
GENV_EOF
)

# Task parameters (every tasks.cards_preprocess key becomes $UPPERCASE)
export TASK_PARAMS=$(cat << "TASK_EOF"
export REMOVE_TRS='2'
export TEMPLATE='HaskinsPeds_NL_template1.0_SSW.nii'
export BLUR_SIZE='4.0'
export CENSOR_MOTION='0.3'
export CENSOR_OUTLIERS='0.05'
TASK_EOF
)

# Execute
source "$SCRIPT_DIR/utils/wrapper_functions.sh"
execute_wrapper "/path/to/scripts/branch/cards_preprocess.sh"
```
:::

:::{warning}
**Two rules for `envir_dir` and `tasks` values.**

*Values are passed through literally.* They are written into the wrapper in
single quotes, so a value containing `$VAR`, a backtick or `$(...)` reaches your
script exactly as written rather than being expanded on the compute node. If you
need something evaluated at run time, put it in `global_python` or `modules`
instead: those are command lists and still expand normally.

*A few key names are reserved.* Every key is upper-cased, so a key named `path`
would become `export PATH=...` and leave the job unable to find any command.
Submission fails with an error if a key maps to `PATH`, `HOME`, `SHELL`, `PWD`,
`OLDPWD` or `IFS`. Rename it, for example to `tool_path`. Other environment
variables are yours to set: a key named `lc_all` or `pythonpath` is accepted,
since a task may legitimately need to override those.
:::

### 3. Your analysis script uses those variables

```bash
#!/bin/bash
# scripts/branch/cards_preprocess.sh
# The wrapper framework passes the current subject as $1.

subject=$1

afni_proc.py \
  -subj_id        sub-${subject} \
  -dsets          $INPUT_DIR/sub-${subject}/func/*.nii.gz \
  -tcat_remove_first_trs $REMOVE_TRS \
  -blur_size      $BLUR_SIZE \
  -tlrc_NL_warp \
  -tlrc_base      $TEMPLATE_DIR/$TEMPLATE \
  -regress_censor_motion   $CENSOR_MOTION \
  -regress_censor_outliers $CENSOR_OUTLIERS \
  -out_dir        $OUTPUT_DIR/sub-${subject}.results
```

### 4. Adding a custom parameter

Any key you add under `tasks.<name>` that is not a reserved field (`name`, `environ`, `profile`, `array`, `container`, `input_from`) is automatically exported as `$UPPERCASE` with no code changes needed:

```yaml
tasks:
  cards_preprocess:
    remove_TRs:  2
    blur_size:   4.0
    censor_motion:   "0.3"
    censor_outliers: "0.05"
    environ: ["afni_24.3.06"]
    polort:    "A"           # → $POLORT  in your script
    bandpass:  "0.01 0.1"   # → $BANDPASS in your script
```

Then in your script:

```bash
3dDeconvolve \
  -polort $POLORT \
  ...
```

This makes every task fully configurable from the YAML without editing any pipeline code.