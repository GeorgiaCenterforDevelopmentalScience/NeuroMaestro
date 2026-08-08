---
title: Add a Custom Task
---

# How To: Add a Custom Task

This walkthrough adds a new task called `flanker_preprocess` to the task fMRI pipeline. By the end you will have a fully integrated task that submits SLURM array jobs, receives parameters from config as environment variables, and supports `--resume`.

::::{admonition} Quick reference — config.yaml structure
:class: tip

1. Add a top-level section (e.g. `mid:`) with one or two task entries.
2. Choose the correct type:
   - BIDS-native (depends on `recon`): use `input_from: recon` and run with `--bids-prep/post mid`
   - Staged (depends on intermed): add `multi_stage: true` and run with `--staged-prep/post mid`
3. If the section has both a prep and post step, set `stage: prep` / `stage: post` and chain them with `input_from`.
4. Pick a `name` you won't need to change — it becomes the permanent identifier in the database and checks file.
5. Add a matching entry under `tasks:` in your project's `{project}_config.yaml`.
6. Add an entry in `{project}_checks.yaml` to enable `--resume` for the new task.
::::

## Overview

Adding a task involves three files:

| File | What you do |
|------|-------------|
| `{scripts_dir}/your_script.sh` (or `.py`, `.r`, ...) | Write the analysis logic |
| `<config-dir>/config.yaml` | Register the task in the pipeline task graph |
| `<config-dir>/project_config/{project}_config.yaml` | Set task parameters for your project |
| `<config-dir>/results_check/{project}_checks.yaml` | (Optional) Define output checks for `--resume` |

### Where task definitions live

Task types are defined in `config.yaml` inside your `--config-dir`. Add new pipeline sections directly to this file. Task-specific parameters (resources, paths, tool versions) go in your project config under `tasks`.

## Step 1: Write the Analysis Script

Create the script in the directory set by `scripts_dir` in your project config:

```
{scripts_dir}/afni_flanker_preprocess.sh
```

Scripts can be written in any language. The pipeline dispatches based on file extension: `.py` files are run with `python`, everything else is run with `bash`. The script receives **one argument: the subject ID** (e.g., `001`). Everything else is available as **environment variables** that the pipeline exports automatically.

```bash
#!/bin/bash
set -euo pipefail

subject="$1"

# ── Environment variables always available ───────────────────────────────────
# These come from global project config and envir_dir:
#   $PREFIX          subject prefix, e.g. "sub-"
#   $PROJECT         project name, e.g. "my_study"
#   $SESSION         session label, e.g. "01"
#   $INPUT_DIR       raw BIDS input directory
#   $OUTPUT_DIR      pipeline output root
#   $WORK_DIR        working / log directory
#   $TEMPLATE_DIR    path to MNI templates  (from envir_dir.template_dir)
#   $CONTAINER_DIR   path to .sif containers (from envir_dir.container_dir)
#   $FREESURFER_DIR  FreeSurfer license dir  (from envir_dir.freesurfer_dir)
#
# These come from your task's entry in tasks.flanker_preprocess:
#   $REMOVE_TRS      remove_TRs value
#   $TEMPLATE        template filename
#   $BLUR_SIZE       blur_size value
#   $CENSOR_MOTION   censor_motion value
#   $CENSOR_OUTLIERS censor_outliers value
# ─────────────────────────────────────────────────────────────────────────────

echo "=== Flanker preprocessing: ${PREFIX}${subject} ==="
echo "Template:  ${TEMPLATE_DIR}/${TEMPLATE}"
echo "Blur:      ${BLUR_SIZE} mm"
echo "Remove TRs: ${REMOVE_TRS}"

afni_proc.py \
  -subj_id "${PREFIX}${subject}" \
  -script "proc.${subject}" \
  -dsets "${INPUT_DIR}/${PREFIX}${subject}/ses-${SESSION}/func/"*flanker*bold*.nii.gz \
  -tcat_remove_first_trs "$REMOVE_TRS" \
  -tlrc_base "${TEMPLATE_DIR}/${TEMPLATE}" \
  -blur_size "$BLUR_SIZE" \
  -regress_censor_motion "$CENSOR_MOTION" \
  -regress_censor_outliers "$CENSOR_OUTLIERS" \
  -execute
```

### How parameters become environment variables

Your project config (step 3) lists task parameters like `remove_TRs: 4`. The pipeline converts each key to `UPPER_SNAKE_CASE` and exports it before calling your script:

| Config key | Environment variable |
|------------|----------------------|
| `remove_TRs` | `$REMOVE_TRS` |
| `blur_size` | `$BLUR_SIZE` |
| `censor_motion` | `$CENSOR_MOTION` |
| `template` | `$TEMPLATE` |

Internal keys (`name`, `environ`, `scripts`, `input_from`, `profile`, `array`, `output_pattern`) are **not** exported — they are consumed by the pipeline itself.

:::{important}
If you are editing on Windows, convert line endings before pushing to HPC:
```bash
dos2unix afni_flanker_preprocess.sh
```
Windows CRLF line endings cause `$'\r': command not found` errors on Linux compute nodes.
:::

## Step 2: Register in `config.yaml`

Open `config.yaml` in your `--config-dir` and add your task as a new top-level section. For a staged task fMRI pipeline, add it like `cards` or `kidvid`:

```yaml
# Add a new section for the flanker task
flanker:
  - name: flanker_preprocess
    stage: prep
    profile: standard          # resource profile (required, no default)
    array: true                # true = one array job per subject
    multi_stage: true          # staged pipeline: depends on intermed if requested
    scripts: [afni_flanker_preprocess.sh]
    input_from: recon     # wait for recon (--dependency=afterany)
    output_pattern: "{base_output}/AFNI_derivatives"
```

**Key fields:**

| Field | Description |
|-------|-------------|
| `profile` | **Required.** Resource profile from the `resource_profiles` section in `hpc_config.yaml`, such as `standard`, `heavy_long`, or `light_short`. There is no default: a task without it fails at submission, listing the available profile names. |
| `array` | `true` = SLURM array job (one task per subject). `false` = single job for all subjects. |
| `scripts` | List of shell scripts to run, relative to `scripts_dir`. |
| `input_from` | Name of an upstream task. The pipeline adds `--dependency=afterany:{upstream_job_id}` automatically. |
| `output_pattern` | Used for display / bookkeeping. |

For the full list of resource profiles and their CPU/memory/time limits, see [HPC Configuration](../configuration/hpc-config.md).

## Step 3: Configure in Your Project Config

Add parameters to your project's `{project}_config.yaml` under `tasks`, keyed by task name:

```yaml
tasks:
  flanker_preprocess:        # must match exactly what you put in config.yaml
    remove_TRs: 4
    template: "HaskinsPeds_NL_template1.0_SSW.nii"
    blur_size: 4.0
    environ: ["afni_24.3.06"]       # module names to load (from your modules section)
    censor_motion: "0.3"
    censor_outliers: "0.05"
```

The `environ` list is resolved against your `modules` section. For example:

```yaml
modules:
  afni_24.3.06:
    - ml AFNI/25.1.01-foss-2023a
```

At runtime the pipeline inserts those `ml` commands into the wrapper script's environment block before calling your script.

### Parameter naming rules

- Config key → environment variable: `remove_TRs` → `REMOVE_TRS` (dots and hyphens also become underscores)
- **All values are strings** in the environment. Use `"0.3"` not `0.3` if your script does string comparison.
- Nested dicts are not supported — keep task parameters flat.

## Step 4: Wire the CLI flag

The pipeline routes `--staged-prep flanker` to `flanker_preprocess` by looking up the `flanker` section in `config.yaml` and selecting tasks with `stage: prep`. Run `neuropipe list-tasks` to verify.

## Step 5: Run a Dry-Run Test

```bash
neuropipe run \
  --subjects 001 \
  --input /data/BIDS \
  --output /data/processed \
  --work /data/work \
  --config-dir /data/config \
  --project my_study \
  --session 01 \
  --staged-prep flanker \
  --dry-run
```

The dry-run prints the exact `sbatch` command and the generated wrapper script path without submitting anything. Check:

- `--job-name` matches your task name
- `--array=1-1%15` (1 subject, limit 15 concurrent)
- `--dependency=afterany:...` if you set `input_from`
- The wrapper script in `{work_dir}/log/wrapper/` exports the right `$REMOVE_TRS`, `$TEMPLATE`, etc.

```bash
# Inspect the generated wrapper
cat /data/work/my_study/log/wrapper/afni_flanker_preprocess_*.sh
```

If the dry-run looks correct, remove `--dry-run` to submit.

## Step 6: Add Output Checks for `--resume`

Without a checks entry, `--resume` will always resubmit this task with a warning. Add a rule to `<config-dir>/results_check/{project}_checks.yaml`:

```yaml
flanker_preprocess:
  output_path: "{work_dir}/AFNI_derivatives/{prefix}{subject}/"
  required_files:
    - pattern: "proc.{subject}"
      min_size_kb: 100
    - pattern: "{prefix}{subject}.results/stats.{prefix}{subject}+tlrc.HEAD"
      min_size_kb: 1000
  count_check:
    bold_runs:
      pattern: "pb0*.r0*.scale+orig.HEAD"
      expected_count: 4        # number of runs expected
      tolerance: 0             # must match exactly
```

With this file in place, `--resume` will check each subject's AFNI output directory and only resubmit subjects whose files are missing or too small.

For the full syntax — check types, placeholders, and a real-project example — see [Output Checks Configuration](../configuration/output-checks.md).
