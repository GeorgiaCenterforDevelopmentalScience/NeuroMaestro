---
title: Staged Pipelines (--staged-prep / --staged-post)
---

# Staged Pipelines

CLI flags: `--staged-prep [task1,task2,...]`, `--staged-post [task1,task2,...]`

## What is a staged pipeline?

A staged pipeline is any workflow that requires a **preparatory step** to complete before the main analysis can start. The pipeline is "staged" because it is structured in two phases:

1. **Intermed step** (`--intermed`) — preparatory processing that produces intermediate outputs needed by the main analysis. This runs after BIDS conversion and can include multiple tasks running in parallel.
2. **Staged task** (`--staged-prep`) — the main analysis, which waits for all requested intermed tasks before starting.

The canonical example in this pipeline is AFNI-based task fMRI preprocessing:

- **Intermed:** `volume` runs AFNI's `@SSwarper` to perform skull stripping and nonlinear registration to template. The resulting warp files are required before any functional data can be aligned.
- **Staged:** `cards_preprocess` and `kidvid_preprocess` run `afni_proc.py` using those warp files to preprocess the task fMRI data.

`bfc` (bias field correction) is another example of an intermed step — a structural correction that must precede functional preprocessing.

The pattern itself is not specific to AFNI. Any pipeline that requires one or more prerequisite processing steps before the main analysis — whether using FSL, SPM, FreeSurfer, or a custom tool — can be structured as a staged pipeline. The framework only requires:

- The preparatory work is defined as a task under `intermed:` in `config.yaml`
- The main analysis task is defined with `multi_stage: true` in its config section

```
With --intermed:               Without --intermed:

[recon]                        [recon]
   |                               |
[volume]  [bfc]              [cards_preprocess]
   |          |              [kidvid_preprocess]
   +----------+              (no intermed dependency)
        |
[cards_preprocess]
[kidvid_preprocess]
```

Multiple staged tasks run in parallel with each other — they are independent of each other, both waiting for the same set of intermed tasks:

```bash
neuropipe run ... --intermed volume --staged-prep cards,kidvid
```

:::{note}
The `cards` and `kidvid` sections used as examples below come from the `branch` bundle, which runs against a restricted-access dataset. `config.yaml` also ships `emomatching`, `stopsignal`, and `workingmemory`, which follow the same structure and run against public data. If you want to execute a staged pipeline rather than just read about one, use those and follow [Reproduce the Published Example](../getting-started/reproduce-ds027.md).
:::

---

## Built-in staged tasks (AFNI example)

### cards_preprocess

**What it does:** AFNI-based preprocessing for the Cards task — alignment to template using warp files from `volume`, motion correction, spatial smoothing, and censoring of high-motion and outlier volumes.

**Tool:** AFNI (`afni_proc.py`)  
**SLURM profile:** `standard` (32 GB, 20 h) — array job  
**Script:** `afni_cards_preprocessing.sh`  
**Depends on:** all requested intermed tasks, or `recon` if no `--intermed`  
**Input:** `{output}/BIDS/sub-{subject}/`  
**Output:** `{output}/AFNI_derivatives/sub-{subject}/ses-{session}/cards_output/`

**Config entry:**
```yaml
tasks:
  cards_preprocess:
    remove_TRs: 2
    template: "HaskinsPeds_NL_template1.0_SSW.nii"
    blur_size: 4.0
    environ: ["afni_24.3.06"]
    censor_motion: "0.3"
    censor_outliers: "0.05"
```

### kidvid_preprocess

**What it does:** Same AFNI pipeline as Cards, configured for the KidVid task — more dummy TRs removed due to task design.

**Tool:** AFNI (`afni_proc.py`)  
**SLURM profile:** `standard` (32 GB, 20 h) — array job  
**Script:** `afni_kidvid_preprocess.sh`  
**Depends on:** all requested intermed tasks, or `recon` if no `--intermed`  
**Input:** `{output}/BIDS/sub-{subject}/`  
**Output:** `{output}/AFNI_derivatives/sub-{subject}/ses-{session}/kidvid_output/`

**Config entry:**
```yaml
tasks:
  kidvid_preprocess:
    remove_TRs: 22
    template: "HaskinsPeds_NL_template1.0_SSW.nii"
    blur_size: 4.0
    environ: ["afni_24.3.06"]
    censor_motion: "0.3"
    censor_outliers: "0.05"
```

---

## How task parameters become environment variables

Every key in the `tasks` entry (except reserved fields like `name`, `environ`, `profile`) is exported as `$UPPERCASE` in the wrapper script:

```
Config:  blur_size: 4.0
            ↓
Wrapper: export BLUR_SIZE='4.0'
            ↓
Script:  afni_proc.py -blur_size "$BLUR_SIZE" ...
```

This works the same regardless of the underlying tool — an FSL or SPM script would consume `$BLUR_SIZE` the same way. To customize a run, just add or change a key in your project config with no pipeline code changes needed. See [Project Configuration](../configuration/project-config.md#end-to-end-example-cards_preprocess) for a full walkthrough.

---

## Usage

```bash
# Both tasks, with intermed (staged tasks wait for volume)
neuropipe run \
  --subjects 001,002 \
  --input /data/BIDS \
  --output /data/processed \
  --work /data/work \
  --project my_study \
  --session 01 \
  --intermed volume \
  --staged-prep cards,kidvid

# Multiple intermed tasks (staged tasks wait for ALL of them)
neuropipe run ... --intermed volume,bfc --staged-prep cards,kidvid

# Without intermed (staged tasks depend directly on recon)
neuropipe run ... --staged-prep cards,kidvid
```

---

## Adding a new staged task

The steps below use AFNI as an example, but the same pattern applies to any tool.

1. Write a shell script: `scripts/{project}/my_task_preprocess.sh`
   - The script receives the subject ID as `$1` for array jobs
   - All config parameters are available as `$UPPERCASE` environment variables

2. Add a new section in `config.yaml`:
   ```yaml
   my_task:
     - name: my_task_preprocess
       stage: prep
       profile: standard
       array: true
       multi_stage: true        # marks this as a staged task
       input_from: recon
       scripts: [my_task_preprocess.sh]
       output_pattern: "{base_output}/AFNI_derivatives"
   ```

3. Add task parameters in your project config:
   ```yaml
   tasks:
     my_task_preprocess:
       remove_TRs: 4
       blur_size: 4.0
       environ: ["afni_24.3.06"]   # or fsl, spm, etc.
       censor_motion: "0.3"
   ```

4. Run:
   ```bash
   neuropipe run ... --intermed volume --staged-prep my_task
   ```

The key field is `multi_stage: true` — this tells the DAG that the task belongs to a staged pipeline and should wait for all requested intermed tasks. Without it, the task would run in parallel with `recon` regardless of `--intermed`. See [How-To: Add a Custom Task](../how-to/add-custom-task.md) for a full walkthrough.
