---
title: Intermediate Processing (--intermed)
---
# Intermediate Processing

CLI flag: `--intermed task1,task2,...`

Intermed tasks perform intermediate MRI processing steps (e.g. structural normalization) that staged pipelines depend on. Multiple intermed tasks can be requested in one run — they execute in **parallel** after `recon`, and staged tasks wait for all of them.

```
[recon]
     |
     +-- [volume]  ─┐  (parallel)
     +-- [bfc]    ──┤
                    |
              [cards_preprocess]   (waits for ALL)
              [kidvid_preprocess]
```

## volume

**What it does:** Skull stripping and nonlinear registration to template using AFNI's `@SSwarper`. Produces anatomical warp files used by downstream AFNI task fMRI pipelines.

**Tool:** AFNI (`@SSwarper`, `3dQwarp`)  
**SLURM profile:** `standard_short` (32 GB, 8 h) — array job  
**Script:** `sswarp_scratch.sh`  
**Depends on:** `recon`  
**Input:** `{output}/BIDS/sub-{subject}/ses-{session}/anat/`  
**Output:** `{output}/AFNI_derivatives/sub-{subject}/`

**Config entry:**
```yaml
tasks:
  volume:
    environ: ["afni_24.3.06"]
    template: "HaskinsPeds_NL_template1.0_SSW.nii"
```

The `template` field becomes `$TEMPLATE` in the wrapper script, accessible inside `sswarp_scratch.sh`.

## bfc

**What it does:** Estimates B0 field maps for susceptibility distortion correction (SDC) using [SDCFlows](https://www.nipreps.org/sdcflows/master/cli.html). Produces fieldmap derivatives used by downstream fMRI pipelines.

**Tool:** SDCFlows (via Singularity)  
**SLURM profile:** `standard_short` (32 GB, 8 h) — array job  
**Script:** `sdcflows.sh`  
**Depends on:** `recon`  
**Input:** `{output}/BIDS/`  
**Output:** `{output}/BIDS_derivatives/sdcflows/`

**Config entry:**
```yaml
tasks:
  bfc:
    container: "sdcflows-mriqc-2.10.0.sif"
```

## Adding a new intermed task

Any task defined under the `intermed:` section of `config.yaml` can be requested via `--intermed`. To add one:

1. Add a script in `scripts/{project}/`.
2. Register in `config.yaml` under `intermed:`:
   ```yaml
   intermed:
     - name: bfc
       profile: standard_short
       array: true
       input_from: recon
       scripts: [bias_field_correction.sh]
       output_pattern: "{base_output}/AFNI_derivatives"
   ```
3. Add task parameters in your project config:
   ```yaml
   tasks:
     bfc:
       environ: ["afni_24.3.06"]
   ```
4. Run: `neuromaestro run ... --intermed volume,bfc`

## Usage

```bash
# Single intermed task
neuromaestro run \
  --subjects 001,002 \
  --input /data/BIDS \
  --output /data/processed \
  --work /data/work \
  --project my_study \
  --session 01 \
  --intermed volume

# Multiple intermed tasks (run in parallel)
neuromaestro run ... --intermed volume,bfc

# Combined with staged pipelines
neuromaestro run ... --intermed volume,bfc --staged-prep cards,kidvid
```

:::{note}
When multiple intermed tasks are requested, staged pipelines (`--staged-prep`) wait for **all** of them before submitting. The SLURM dependency becomes `--dependency=afterany:{volume_job}:{bfc_job}`.
:::
