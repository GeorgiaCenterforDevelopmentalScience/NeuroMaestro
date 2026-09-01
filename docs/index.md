---
title: NeuroMaestro
---

# NeuroMaestro

A lightweight **meta-pipeline** — a pipeline that manages other pipelines. Rather than reimplementing any analysis, it sits above your existing tools and scripts and handles the orchestration layer: dependency ordering, job submission, subject-level parallelism, output verification, logging, and summary HTML reports.

Designed for labs that run multiple modalities and want to go from raw DICOMs to processed outputs without writing custom job management code from scratch.

Supports both a web-based GUI and a command-line interface (CLI).

---

## What it does

The tools listed below are the **default templates** shipped with this pipeline. Because the pipeline is tool-agnostic, any of them can be swapped out — what actually runs depends on which modules are installed on your HPC cluster and what you configure in your project's YAML files.

| Pipeline | Default Tools | Description |
|----------|--------------|-------------|
| **Preparation** | p7zip, dcm2bids | Unzip raw data, convert DICOM to BIDS |
| **Intermediate MRI** | AFNI | Volume-based structural analysis |
| **Resting-State fMRI** | fMRIPrep, XCP-D | Preprocessing and functional connectivity |
| **Task fMRI** | AFNI | Task-based preprocessing and postprocessing |
| **DWI** | QSIPrep, QSIRecon | Diffusion MRI preprocessing and reconstruction |
| **Quality Control** | MRIQC | Individual and group QC reports |

---

## Who is this for

### Experienced researchers and pipeline maintainers

If you already have analysis scripts and want a structured way to run them at scale:

- **Config-driven parameter management** — all analysis parameters (`blur_size`, `remove_TRs`, container paths, etc.) live in versioned YAML files, not hardcoded in scripts. Switching between study parameters or comparing two configurations is a matter of swapping a config file.
- **Reproducibility records** — every pipeline run writes a structured log capturing the full command line, subject list, task list, job IDs, execution times, exit codes, stdout/stderr, and the exact wrapper environment (module versions, exported variables) at submission time. *These records persist in both human-readable JSONL files and a queryable SQLite database, making it straightforward to answer "what exact parameters did we use for subject 031 six months ago?"*
- **Extensible** — adding a new task means adding a config entry and a shell script. No pipeline code needs to change.

### New lab members and students

Once a lab maintainer has set up the project config, anyone can run the full pipeline through the GUI without needing to understand SLURM, bash scripting, or the underlying tools:

- Open the GUI, select subjects, tick the stages you want, click **Execute Pipeline**
- Monitor job progress from the same interface
- Check output completeness with one click


:::{note}
The goal is that an undergraduate with no HPC or fMRI processing experience can run a complete analysis after a 15-minute walkthrough — and the outputs are just as traceable and reproducible as if an expert had submitted manually from the CLI.
:::


---

## Design philosophy

- **Bring your own scripts** — the pipeline ships with default analysis scripts for each supported modality. These work out of the box if your HPC environment has the required modules or Singularity containers; they are also the starting point you modify when you need different parameters, tools, or workflows.
- **Lightweight** — a thin coordination layer. It does not reimplement any analysis; it organizes how your existing tools and scripts are called.
- **Flexible** — tasks, dependencies, resource profiles, processing scripts, and scheduler settings are all configurable.
- **Fail-safe** — JSONL logs are written with `fsync` on compute nodes independently of the database. If the cluster crashes mid-run, no records are lost. The database can always be rebuilt from raw logs.

---

## Before you start

This pipeline coordinates job submission and logging — it does not bundle any analysis software. Two things need to be in place on your HPC cluster before you run:

- **Analysis software or singularity** — either as environment modules (`module load fmriprep/23.2`) or Singularity/Apptainer containers. The default scripts reference specific module names and container paths; you update these in the project config YAML.
- **A project config** — a YAML file that tells the pipeline where your data lives, which tasks to run, and which HPC resource profiles to use. The config generator (`neuromaestro generate-config`) produces a commented template to start from.


:::{note}
The config requires some upfront work, but that is intentional: it is the tradeoff for being able to mix tools, sessions, and modalities freely without the pipeline imposing its own structure.
:::


---

## Quick navigation

::::{grid} 2
:::{card} Getting Started
:link: getting-started/index
Install the pipeline and run your first job in 5 minutes.
:::
:::{card} Complete Pipeline Walkthrough
:link: getting-started/full-pipeline
End-to-end example: config → submit → verify → re-run.
:::
:::{card} Reproduce the Published Example
:link: getting-started/reproduce-ds027
Run the AOMIC-PIOP2 demonstration from public data.
:::
:::{card} Configuration Guide
:link: configuration/project-config
Project config, HPC profiles, and output checks.
:::
:::{card} Pipeline Tasks Reference
:link: pipeline-reference/index
What each task does, its inputs, outputs, and dependencies.
:::
:::{card} GUI Reference
:link: gui/index
Web dashboard walkthrough — Analysis Control, Project Config, Job Monitor.
:::
:::{card} CLI Reference
:link: cli-reference/index
All command-line options explained.
:::
:::{card} How-To Guides
:link: how-to/rerun-subjects
Step-by-step recipes for common scenarios.
:::
:::{card} Debug & Troubleshoot
:link: how-to/debug-failures
Common errors and how to fix them.
:::
::::
