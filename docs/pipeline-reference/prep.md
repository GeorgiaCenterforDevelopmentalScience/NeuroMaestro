---
title: Preparation (prep)
---

# Preparation Tasks

CLI flag: `--prep [unzip | recon | unzip_recon]`

## unzip

**What it does:** Extracts every `.zip` archive found under the input directory with 7-Zip, five archives at a time. It then reads one DICOM header from each extracted `e*` folder with AFNI's `dicom_hdr`, takes the first group of digits in the Patient ID as the subject ID, and renames the folder to `{prefix}{id}`. A CSV summary of the folder-to-ID mapping and a rename log are written next to the extracted data.

**Tool:** p7zip + GNU parallel + AFNI (`dicom_hdr`)  
**SLURM profile:** `standard` (32 GB, 20 h) — non-array job (all subjects in one job)  
**Script:** `unzip_rename.sh`  
**Input:** `--input`, a directory containing the `.zip` archives  
**Output:** `{output}/raw/ses-{session}/{prefix}{id}/`

**Config entry** (in `{project}_config.yaml`):
```yaml
tasks:
  unzip:
    environ: ["data_manage_1", "afni_24.3.06"]    # p7zip and parallel, plus AFNI for dicom_hdr
```

:::{note}
`unzip` runs as a **single** SLURM job (not an array). It does not use the subject list: it extracts every `.zip` under `--input`, running five extractions in parallel within that one job.
:::

## recon

**What it does:** Converts DICOM files to BIDS format using `dcm2bids` inside a Singularity container.

**Tool:** dcm2bids (Singularity)  
**SLURM profile:** `light_short` (16 GB, 4 h) — array job  
**Script:** `dcm2bids_convert_BIDS.sh`  
**Depends on:** `unzip` (when requested in the same command)  
**Input:** `{output}/raw/ses-{session}/{prefix}{subject}/` when `unzip` runs in the same command, otherwise `--input/ses-{session}/{prefix}{subject}/`  
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

# Convert already-unzipped data (--input must hold ses-{session}/{prefix}{id}/ DICOM folders)
neuromaestro run ... --prep recon
```
