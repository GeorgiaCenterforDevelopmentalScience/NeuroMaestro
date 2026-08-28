---
title: Getting Started
---

# Getting Started

This page will get you from zero to a running pipeline job in about 5 minutes.

## Prerequisites

- Python 3.10+
- Access to an HPC cluster with SLURM
- Neuroimaging software installed on the cluster (fMRIPrep, XCP-D, AFNI, FSL, MRIQC, QSIPrep as needed)
- Singularity containers for containerized tools

## Installation

**1. Clone the repository onto your HPC system:**

```bash
git clone <repository-url>
cd GCDS_Neuro_Pipeline
```

**2. Install the package:**

```bash
pip install -e .
# For development extras:
# pip install -e .[dev]
```

**3. Verify the installation:**

```bash
neuropipe --help
neuropipe-gui --help
```

## Minimal Quickstart (5 minutes)

The fastest way to verify everything works is a **dry-run**: this generates and prints all SLURM commands without submitting any jobs.

### Step 1: Initialise your config directory

Run `neuropipe init` once to create a config directory pre-populated with template files:

```bash
neuropipe init /scratch/my_study
```

This creates:

```
/scratch/my_study/
├── config/                    ← pass this to --config-dir
│   ├── config.yaml
│   ├── hpc_config.yaml
│   ├── project_config/
│   │   ├── template_config.yaml   (start from this one)
│   │   └── (the other bundled configs)
│   └── results_check/
│       ├── template_checks.yaml
│       └── (the other bundled checks)
└── scripts/
    └── (template .sh scripts)
```

All bundled config and check files are copied, not just the template. Copy `template_config.yaml` to `{your_project}_config.yaml` and `template_checks.yaml` to `{your_project}_checks.yaml`, then edit those. The rest are reference bundles and are described in [Dev & Test Config Modes](../internals/dev-test-configs.md). One of them, `ds027`, is a complete published run you can reproduce from public data (see [Reproduce the Published Example](reproduce-ds027.md)).

You then pass `--config-dir /scratch/my_study/config` to every `neuropipe` command. The pipeline uses four config files split into two tiers:

:::{important}
**Skip `--config-dir` by exporting an environment variable.**
If you always work with the same config directory, add this line to your `~/.bashrc` once:

```bash
export NEUROPIPE_CONFIG_DIR=/scratch/my_study/config
```

After that, all `neuropipe` commands will pick it up automatically and you can omit `--config-dir`. You can still override it any time by passing `--config-dir` explicitly.
:::

**Required — create one per project:**

| File | Location inside `--config-dir` | What you do |
|------|--------------------------------|-------------|
| `{project}_config.yaml` | `project_config/` | Per-project settings: HPC paths, module versions, and task parameters. **This is the main file you create for each new study.** |
| `{project}_checks.yaml` | `results_check/` | Output file checks used by `--resume` and `check-outputs`. Required for resume and output verification to work. |

**Shared — review once, rarely touch after that:**

| File | Location inside `--config-dir` | What you do |
|------|--------------------------------|-------------|
| `hpc_config.yaml` | root | Scheduler type (SLURM/PBS), cluster-wide resource profiles, and job submission flag templates. Review when setting up on a new cluster. |
| `config.yaml` | root | Global task definitions and resource profiles shared across all projects. Ships with defaults for the standard task set. **Only edit this when adding a new task type.** |

:::{tip}
**Day-to-day you only edit `{project}_config.yaml`.** The shared configs are a one-time cluster setup — once they're right for your HPC environment, you won't need to touch them again.
:::

The most common setup task is editing `{project}_config.yaml`. Use the GUI to generate a template:

```bash
neuropipe-gui
```

:::{note}
`neuropipe-gui` runs a web server **on the HPC login node**. To view it in a browser:
- **VNC / remote desktop session on the HPC** — open `http://localhost:8050` directly.
- **Terminal-only SSH from your laptop** — run `ssh -L 8050:localhost:8050 user@cluster` to forward the port, then open `http://localhost:8050` in your local browser.

See the [GUI Reference](../gui/index.md) for a full walkthrough including job monitoring and output verification.
:::

Go to **Project Config → Project Config tab → Generate Template**, fill in your cluster paths, module names, and task parameters. See the [Project Config Guide](../configuration/project-config.md) for a full annotated example.

### Step 2: Detect your subjects

```bash
# Standard BIDS dataset (folders named sub-001, sub-002, ...)
neuropipe detect-subjects /data/BIDS --prefix "sub-"

# No prefix (folders named 001, 002, ...)
neuropipe detect-subjects /data/raw --prefix ""
```

Returns subject IDs with the prefix stripped; pass these bare IDs to `--subjects` in all subsequent commands. See [Complete Pipeline Walkthrough](full-pipeline.md#2-detect-subjects) for how the prefix mechanism works.

### Step 3: Dry-run a single subject

```bash
neuropipe run \
  --subjects 001 \
  --input /data/BIDS \
  --output /data/processed \
  --work /data/work \
  --config-dir /scratch/my_study/config \
  --project my_study \
  --session 01 \
  --prep unzip_recon \
  --dry-run
```

Full pipeline — all stages, multiple subjects:

```bash
neuropipe run \
  --subjects 001,002,003 \
  --input /data/raw \
  --output /data/processed \
  --work /data/work \
  --config-dir /scratch/my_study/config \
  --project my_study \
  --session 01 \
  --prep unzip_recon \
  --intermed volume \
  --staged-prep cards,kidvid \
  --bids-prep rest,dwi --bids-post rest,dwi \
  --mriqc all \
  --dry-run
```

`--dry-run` prints the exact `sbatch` commands that would be submitted; no jobs are actually queued. You should see something like:

```
[DRY RUN] Would submit: sbatch --job-name=volume --array=1-1%15 ...
```

If that looks right, remove `--dry-run` to submit for real. See [run command reference](../cli-reference/run.md) for all available flags.

### Step 4: Monitor your jobs

```bash
squeue -u $USER                          # SLURM queue
neuropipe-gui                            # GUI: Job Monitor tab → http://localhost:8050
```

## Next Steps

[Complete Pipeline Walkthrough](full-pipeline.md) covers all seven stages with architecture context. For config details, see the [Project Config Guide](../configuration/project-config.md) and [Pipeline Tasks Reference](../pipeline-reference/index.md). The [GUI Reference](../gui/index.md) walks through Analysis Control, job monitoring, and report generation. Full CLI flag documentation is in the [CLI Reference](../cli-reference/index.md).
