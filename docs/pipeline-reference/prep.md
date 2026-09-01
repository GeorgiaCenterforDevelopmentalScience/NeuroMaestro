---
title: Preparation (prep)
---

# Preparation Tasks

CLI flag: `--prep [unzip | recon | unzip_recon]`

## unzip

**What it does:** Extracts all compressed archives (`.zip`, `.7z`, `.tar.gz`) from the input directory using parallel decompression. After extraction it checks for `{prefix}{subject_id}` directories and prepares them for downstream processing.

**Tool:** p7zip + GNU parallel  
**SLURM profile:** `standard` (32 GB, 20 h) — non-array job (all subjects in one job)  
**Script:** `unzip_rename.sh`  
**Input:** Any directory containing compressed data files  
**Output:** `{output}/raw/`

**Config entry** (in `{project}_config.yaml`):
```yaml
tasks:
  unzip:
    environ: ["data_manage_1"]    # loads p7zip and parallel modules
```

:::{note}
`unzip` runs as a **single** SLURM job (not an array), processing all subjects sequentially. This avoids I/O contention when unpacking many large archives simultaneously.
:::

## recon

**What it does:** Converts DICOM files to BIDS format using `dcm2bids` inside a Singularity container.

**Tool:** dcm2bids (Singularity)  
**SLURM profile:** `light_short` (16 GB, 4 h) — array job  
**Script:** `dcm2bids_convert_BIDS.sh`  
**Depends on:** `unzip`  
**Input:** `{output}/raw/{subject}/`  
**Output:** `{output}/BIDS/sub-{subject}/ses-{session}/`

**Config entry** (in `{project}_config.yaml`):
```yaml
tasks:
  recon:
    container: "dcm2bids_3.2.0.sif"   # must be in container_dir
    config: "branch_config.json"        # dcm2bids BIDS config file
```

The `config` file maps DICOM series descriptions to BIDS modality labels. Store it in `config_dir`.

## Common Usage

```bash
# Unzip and convert in one step
neuromaestro run \
  --subjects 001,002,003 \
  --input /data/zip_files \
  --output /data/processed \
  --work /data/work \
  --project my_study \
  --session 01 \
  --prep unzip_recon

# Unzip only
neuromaestro run ... --prep unzip

# Convert already-unzipped data
neuromaestro run ... --prep recon
```
