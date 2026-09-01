---
title: Quality Control (qc)
---

# Quality Control

CLI flag: `--mriqc [individual | group | all]`

## mriqc_preprocess

**What it does:** Runs MRIQC on a per-subject basis, computing image quality metrics (IQMs) for structural (T1w) and functional (BOLD) scans. Produces an HTML report per subject.

**Tool:** MRIQC (Singularity)  
**SLURM profile:** `heavy_long` (64 GB, 24 h) — array job  
**Script:** `mriqc_individual.sh`  
**Depends on:** `recon`  
**Input:** `{output}/BIDS/`  
**Output:** `{output}/quality_control/mriqc/sub-{subject}/`

**Config entry:**
```yaml
tasks:
  mriqc_preprocess:
    container: "mriqc_24.0.2.sif"
```

## mriqc_post

**What it does:** Aggregates all individual MRIQC results into a group-level report with IQM distributions across subjects.

**Tool:** MRIQC (Singularity)  
**SLURM profile:** `light_short` (16 GB, 4 h) — single job  
**Script:** `mriqc_group.sh`  
**Depends on:** `mriqc_preprocess`  
**Output:** `{output}/quality_control/mriqc/`

**Config entry:**
```yaml
  mriqc_post:
    container: "mriqc_24.0.2.sif"
```

## Usage

```bash
# Run both individual and group QC
neuromaestro run \
  --subjects 001,002,003 \
  --input /data/BIDS \
  --output /data/processed \
  --work /data/work \
  --project my_study \
  --session 01 \
  --mriqc all

# Individual QC only
neuromaestro run ... --mriqc individual

# Group report only (individual already done)
neuromaestro run ... --mriqc group
```

:::{tip}
MRIQC can be run independently of the rest of the pipeline — it operates directly on BIDS data and does not require fMRIPrep or AFNI outputs.
:::
