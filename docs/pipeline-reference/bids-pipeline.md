---
title: BIDS Pipelines (--bids-prep / --bids-post)
---

# BIDS Pipelines

CLI flags: `--bids-prep [rest|dwi]`, `--bids-post [rest|dwi]`

## What is a BIDS pipeline?

A BIDS pipeline is any two-step, containerized workflow that operates directly on BIDS-formatted data. The two steps map cleanly onto a preprocessing → postprocessing structure:

- **`--bids-prep`** runs the primary preprocessing container (e.g. fMRIPrep, QSIPrep). This step is computationally heavy and produces minimally preprocessed outputs.
- **`--bids-post`** runs a downstream analysis container on those outputs (e.g. XCP-D for functional connectivity, QSIRecon for tractography). When `--bids-prep` is in the same command, it automatically waits for it to finish and reads its outputs.

The two built-in examples follow this pattern:

| Modality | `--bids-prep` | `--bids-post` |
|----------|--------------|--------------|
| Resting-state fMRI | fMRIPrep (motion correction, normalization) | XCP-D (denoising, functional connectivity) |
| Diffusion MRI | QSIPrep (eddy correction, registration) | QSIRecon (tractography, connectivity matrices) |

Both steps run as SLURM array jobs (one job per subject) and are independent of `--intermed` — they depend only on `recon`. Multiple modalities requested together run in parallel:

```
[recon]
     |
     +-- [rest_preprocess]  →  [rest_post]
     +-- [dwi_preprocess]   →  [dwi_post]
```

You can run prep and post together or separately, and combine multiple modalities in one command. A post step run without its prep step in the same command has no dependency and reads `--input`, so `--input` must then point at the prep step's output (see the usage examples below):

```bash
neuromaestro run ... --bids-prep rest,dwi --bids-post rest,dwi
```

Any containerized two-step pipeline that follows this `recon → prep → post` pattern can be added as a new BIDS section in `config.yaml` — the tool inside the container is irrelevant to the framework.

---

## Resting-State fMRI (`rest`)

### rest_preprocess

**What it does:** Full anatomical and functional preprocessing with fMRIPrep — motion correction, distortion correction, surface/volume normalization.

**Tool:** fMRIPrep (Singularity)  
**SLURM profile:** `heavy_long` (64 GB, 24 h) — array job  
**Script:** `fmriprep_rs.sh`  
**Depends on:** `recon`  
**Input:** `{output}/BIDS/`  
**Output:** `{output}/BIDS_derivatives/fmriprep/`

**Config entry:**
```yaml
tasks:
  rest_preprocess:
    remove_TRs: 6
    template: "MNI152NLin2009cAsym"
    container: "fmriprep_25.1.3.sif"
    license: "license.txt"
```

### rest_post

**What it does:** Post-processing of fMRIPrep outputs with XCP-D — nuisance regression, bandpass filtering, functional connectivity matrix computation.

**Tool:** XCP-D (Singularity)  
**SLURM profile:** `standard_short` (32 GB, 8 h) — array job  
**Script:** `xcpd_rs.sh`  
**Depends on:** `rest_preprocess` (when requested in the same command)  
**Input:** `{output}/BIDS_derivatives/fmriprep/`  
**Output:** `{output}/BIDS_derivatives/xcpd/`

**Config entry:**
```yaml
tasks:
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
```

### Usage

```bash
# Full resting-state pipeline
neuromaestro run \
  --subjects 001,002 \
  --input /data/BIDS \
  --output /data/processed \
  --work /data/work \
  --project my_study \
  --session 01 \
  --bids-prep rest \
  --bids-post rest

# XCP-D only (fMRIPrep already complete): --input must point at the fMRIPrep output
neuromaestro run ... --input /data/processed/my_study/BIDS_derivatives/fmriprep --bids-post rest
```

---

## Diffusion MRI (`dwi`)

### dwi_preprocess

**What it does:** DWI preprocessing with QSIPrep — denoising, susceptibility distortion correction, eddy current correction, motion correction, and template registration.

**Tool:** QSIPrep (Singularity)  
**SLURM profile:** `standard` (32 GB, 20 h) — array job  
**Script:** `qsiprep.sh`  
**Depends on:** `recon`  
**Input:** `{output}/BIDS/`  
**Output:** `{output}/BIDS_derivatives/qsiprep/`

**Config entry:**
```yaml
tasks:
  dwi_preprocess:
    template: "MNI152NLin2009cAsym"
    container: "qsiprep-1.0.0.sif"
    license: "license.txt"
    output_resolution: 2.0
    unringing_method: "mrdegibbs"
```

### dwi_post

**What it does:** Tractography and connectivity matrix computation with QSIRecon.

**Tool:** QSIRecon (Singularity)  
**SLURM profile:** `standard` (32 GB, 20 h) — array job  
**Script:** `qsirecon.sh`  
**Depends on:** `dwi_preprocess` (when requested in the same command)  
**Input:** `{output}/BIDS_derivatives/qsiprep/`  
**Output:** `{output}/BIDS_derivatives/qsirecon/`

**Config entry:**
```yaml
tasks:
  dwi_post:
    container: "qsirecon-1.2.0.sif"
    mode: "dsi_studio_autotrack"
    license: "license.txt"
    atlases: "Gordon333Ext"
```

### Usage

```bash
# Full DWI pipeline
neuromaestro run \
  --subjects 001,002 \
  --input /data/BIDS \
  --output /data/processed \
  --work /data/work \
  --project my_study \
  --session 01 \
  --bids-prep dwi \
  --bids-post dwi

# Preprocessing only
neuromaestro run ... --bids-prep dwi

# QSIRecon only (QSIPrep already complete): --input must point at the QSIPrep output
neuromaestro run ... --input /data/processed/my_study/BIDS_derivatives/qsiprep --bids-post dwi
```

---

## Adding a new BIDS pipeline

Any two-step containerized pipeline that follows the `recon → prep → post` pattern can be added as a new BIDS section in `config.yaml`. See [How-To: Add a Custom Task](../how-to/add-custom-task.md).
