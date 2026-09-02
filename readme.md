<p align="center">
  <img src="docs/images/neuromaestro.jpg" alt="NeuroMaestro" width="240">
</p>

# NeuroMaestro

A modular neuroimaging preprocessing pipeline for HPC clusters, with both a GUI and CLI. Pipeline parameters and analysis workflows are configured through YAML files, allowing flexible customization without modifying the underlying code.

Full handbook: https://georgiacenterfordevelopmentalscience.github.io/NeuroMaestro/

---

## Supported Pipelines

The pipeline is organized into four stages. The software used at each stage is configured per-project and can be customized; the examples below reflect our defaults.

| Stage | Description | Example software |
|-------|-------------|-----------------|
| **Data preparation** | Unzip raw data, convert DICOM to BIDS | dcm2bids |
| **Intermediate steps** | Any intermediate step required before modality pipelines (staged pipelines only) | AFNI `@SSwarper` |
| **BIDS pipelines** | Modality preprocessing that runs directly on BIDS data | fMRIPrep, XCP-D, QSIPrep, QSIRecon |
| **Quality control** | Image quality metrics | MRIQC |

The key distinction between pipeline types:
- **Staged pipelines** (`--staged-prep`) require an intermediate structural or bias field correction step before modality preprocessing. Designed for workflows like AFNI that operate on locally processed data, but can be adapted to any pipeline requiring intermediate steps.
- **BIDS pipelines** (`--bids-prep`) run directly on BIDS-formatted data without intermediate steps (e.g. fMRIPrep, QSIPrep).

---

## Installation

**Prerequisites:** Python 3.10+, HPC cluster with SLURM or PBS, neuroimaging software installed on the cluster.

```bash
git clone https://github.com/GeorgiaCenterforDevelopmentalScience/NeuroMaestro.git
cd NeuroMaestro
pip install -e .

# Or developmental mode
# pip install -e .[dev]

# Verify
neuromaestro --help
neuromaestro-gui --help
```

---

## Configuration

Each project requires a `{project}_config.yaml` in `src/neuromaestro/config/project_config/`. Copy `template_config.yaml` as a starting point, then fill in paths, HPC modules, and pipeline options. Output folder names are defined in this file and can be changed freely.

Modalities available under `--bids-prep` and `--staged-prep` are declared in `config.yaml`.

Expected output files for `--resume` are defined in `config/results_check/{project}_checks.yaml`. Edit this file to specify which files should exist (and optionally their minimum size) for a subject to be considered complete.

HPC scheduler, resource profiles (memory, walltime, CPU), and submission flags are configured in `hpc_config.yaml`. Recommended values are pre-filled; update partition names and resource limits to match your cluster.

---

## Quick Start

**First-time setup:** scaffold config and script templates into your study directory.

```bash
neuromaestro init /path/to/my_study
# Optionally export to ~/.bashrc so you can omit --config-dir on every command.
# If you skip this, pass --config-dir /path/to/my_study/config explicitly instead.
export NEUROMAESTRO_CONFIG_DIR=/path/to/my_study/config
```

This copies `config.yaml`, `hpc_config.yaml`, `project_config/`, `results_check/`, and script templates. Edit them to match your cluster and project before running.

---

```bash
# Launch the GUI
neuromaestro-gui   # open http://localhost:8050 in your browser
```

Or use the CLI. Start with a dry-run on one subject to verify the plan:

```bash
neuromaestro run \
  --subjects 001 \
  --input /data/BIDS \
  --output /data/processed \
  --work /data/work \
  --config-dir /data/config \
  --project my_study \
  --session 01 \
  --bids-prep rest \
  --dry-run
```

Full pipeline — all stages, multiple subjects:

```bash
neuromaestro run \
  --subjects subjects.txt \
  --input /data/raw \
  --output /data/processed \
  --work /data/work \
  --config-dir /data/config \
  --project my_study \
  --session 01 \
  --prep unzip_recon \
  --intermed volume \
  --staged-prep cards,kidvid \
  --staged-post cards,kidvid \
  --bids-prep rest,dwi \
  --bids-post rest,dwi \
  --mriqc all
```

Dependencies are enforced automatically by the scheduler.

---

## CLI Reference

### Core options

| Option | Description |
|--------|-------------|
| `--subjects` | Comma-separated subject IDs or path to a `.txt` file |
| `--input` | Input BIDS directory |
| `--output` | Output directory |
| `--work` | Work directory (logs, database, intermediate files) |
| `--config-dir` | Path to config directory (contains `config.yaml`, `hpc_config.yaml`, `project_config/`). Optional if `$NEUROMAESTRO_CONFIG_DIR` is exported. |
| `--project` | Project name (must match a `{project}_config.yaml`) |
| `--session` | Session label (e.g. `01`) |

### Pipeline options

| Option | Description |
|--------|-------------|
| `--prep` | Data preparation: `unzip`, `recon`, `unzip_recon` |
| `--intermed <tasks>` | Intermed tasks to run (comma-separated, e.g. `volume`); required before `--staged-prep` |
| `--bids-prep <modalities>` | BIDS pipeline preprocessing (comma-separated, e.g. `rest,dwi`) |
| `--bids-post <modalities>` | BIDS pipeline postprocessing (comma-separated, e.g. `rest,dwi`) |
| `--staged-prep <modalities>` | Staged pipeline preprocessing (comma-separated, e.g. `cards,kidvid`) |
| `--staged-post <modalities>` | Staged pipeline postprocessing (comma-separated, e.g. `cards,kidvid`) |
| `--mriqc` | Quality control: `individual`, `group`, `all` |

### Run options

| Option | Description |
|--------|-------------|
| `--dry-run` | Preview the execution plan without submitting jobs |
| `--resume` | Skip subjects whose expected outputs already exist |
| `--skip-bids-validation` | Skip pre-run BIDS validation |

---

## Resume a Partial Run

```bash
neuromaestro run \
  --subjects subjects.txt \
  --input /data/BIDS \
  --output /data/processed \
  --work /data/work \
  --config-dir /data/config \
  --project my_study \
  --session 01 \
  --bids-prep rest \
  --resume
```

`--resume` checks each subject's expected output files (defined in `config/results_check/{project}_checks.yaml`) before submitting. Subjects that already have valid outputs are skipped silently.

---

## Directory Structure

### Input (BIDS)

```
input_directory/
├── sub-001/
│   └── ses-01/
│       ├── anat/
│       ├── func/
│       └── ...
└── sub-002/
    └── ...
```

### Output Example

```
output_directory/
└── project_name/
    ├── raw/
    ├── BIDS/
    ├── AFNI_derivatives/
    ├── BIDS_derivatives/
    │   ├── fmriprep/
    │   ├── xcpd/
    │   ├── qsirecon/    
    │   └── qsiprep/
    └── quality_control/
        └── mriqc/

work_directory/
└── project_name/
    ├── log/
    └── database/
```

---

**Version**: 0.15.0-alpha | **Updated**: July 2026  
For questions or issues, contact [QiuyuYu](https://github.com/QiuyuYu3) or open a repository issue.
