---
title: Pipeline Configuration
---

# Pipeline Configuration

`config.yaml` defines the pipeline's task graph: which tasks exist, in what order they run, which resources they request, and where their outputs land.

**Location:** `config/config.yaml`

Most users only need this file when adding a new pipeline section (e.g. a new task-fMRI paradigm). For HPC scheduler settings and resource profiles, see [HPC Configuration](hpc-config.md).

---

## File Structure

Tasks are organized into top-level sections. Each section name is the **pipeline identifier** used in CLI flags.

```yaml
# Preparation (--prep)
prep:
  - name: unzip
    profile: standard
    scripts: [unzip_rename.sh]
    output_pattern: "{base_output}/raw"

  - name: recon
    profile: light_short
    array: true
    scripts: [dcm2bids_convert_BIDS.sh]
    input_from: unzip
    output_pattern: "{base_output}/BIDS"

# Intermed step (--intermed volume / --intermed volume,bfc)
# All listed tasks run in parallel after recon.
# Every staged pipeline waits for ALL intermed tasks to finish.
intermed:
  - name: volume
    profile: standard_short
    array: true
    input_from: recon
    scripts: [sswarp_scratch.sh]
    output_pattern: "{base_output}/AFNI_derivatives"

  - name: bfc
    profile: standard_short
    array: true
    input_from: recon
    scripts: [bfc_scratch.sh]
    output_pattern: "{base_output}/AFNI_derivatives"

# BIDS-native pipelines (--bids-prep rest / --bids-post rest)
rest:
  - name: rest_preprocess
    stage: prep
    profile: heavy_long
    array: true
    input_from: recon
    scripts: [fmriprep_rs.sh]
    output_pattern: "{base_output}/BIDS_derivatives/fmriprep"

  - name: rest_post
    stage: post
    profile: standard_short
    array: true
    input_from: rest_preprocess
    scripts: [xcpd_rs.sh]
    output_pattern: "{base_output}/BIDS_derivatives/xcpd"

# BIDS-native pipelines (--bids-prep dwi / --bids-post dwi)
dwi:
  - name: dwi_preprocess
    stage: prep
    profile: standard
    array: true
    input_from: recon
    scripts: [qsiprep.sh]
    output_pattern: "{base_output}/BIDS_derivatives/qsiprep"

  - name: dwi_post
    stage: post
    profile: standard
    array: true
    input_from: dwi_preprocess
    scripts: [qsirecon.sh]
    output_pattern: "{base_output}/BIDS_derivatives/qsirecon"

# Staged pipelines (--staged-prep cards / --staged-post cards)
# multi_stage: true → depends on volume (intermed) when --intermed is used
cards:
  - name: cards_preprocess
    stage: prep
    profile: standard
    array: true
    input_from: recon
    multi_stage: true
    scripts: [afni_cards_preprocessing.sh]
    output_pattern: "{base_output}/AFNI_derivatives"

  - name: cards_post
    stage: post
    profile: standard
    input_from: cards_preprocess
    multi_stage: true
    scripts: [afni_cards_post.sh]
    output_pattern: "{base_output}/post_analysis/cards"

kidvid:
  - name: kidvid_preprocess
    stage: prep
    profile: standard
    array: true
    input_from: recon
    multi_stage: true
    scripts: [afni_kidvid_preprocess.sh]
    output_pattern: "{base_output}/AFNI_derivatives"

  - name: kidvid_post
    stage: post
    profile: standard
    input_from: kidvid_preprocess
    multi_stage: true
    scripts: [afni_kidvid_post.sh]
    output_pattern: "{base_output}/post_analysis/cards"

# Quality control (--mriqc)
qc:
  - name: mriqc_preprocess
    stage: prep
    profile: heavy_long
    array: true
    input_from: recon
    scripts: [mriqc_individual.sh]
    output_pattern: "{base_output}/quality_control/mriqc"

  - name: mriqc_post
    stage: post
    profile: light_short
    input_from: recon
    scripts: [mriqc_group.sh]
    output_pattern: "{base_output}/quality_control/mriqc"
```

---

## Task Field Reference

| Field | Modifiable? | Description |
|-------|-------------|-------------|
| `name` | **Set once — do not rename** | Internal task identifier used in database logging, `_checks.yaml`, and `input_from` references. Renaming after any jobs have run breaks resume and job history. |
| `profile` | **Yes** | Resource profile from `hpc_config.yaml`. Tune freely — changing only affects future submissions. |
| `scripts` | **Yes** | Shell script filename(s) relative to `scripts_dir`. Update when swapping the underlying analysis script. |
| `stage` | **Set at design time** | `prep` or `post` — controls intra-section dependency order. Do not change after the section is in use. |
| `array` | **Rarely** | `true` = one SLURM array job per subject. Nearly always `true` for subject-level tasks; `false` only for group-level steps like `mriqc_post`. How many of those subjects run at once is set by `array_limit` on the task's resource profile, in [`hpc_config.yaml`](hpc-config.md). |
| `input_from` | **Set at design time** | Name of the upstream task whose output directory becomes this task's input. Controls where the task reads data from — not the job dependency order (that is handled internally by the pipeline). |
| `output_pattern` | **Before first run only** | Output root used by `--resume` to locate existing results. Can be set freely when first creating a task, but changing it after subjects have been processed means the pipeline can no longer find their outputs and will resubmit them. |
| `multi_stage` | **Set at design time** | `true` = this task belongs to a staged pipeline. When any `--intermed` tasks are requested, this task waits for **all** of them to finish before starting. Without `--intermed`, it runs in parallel with `recon`. Set when first creating the section; do not toggle later. |

---

## Pipeline Types

| Type | CLI flag | Input data from | Examples |
|------|----------|-----------|---------|
| Prep/utility | `--prep` | — | `unzip`, `recon` |
| Intermed | `--intermed volume[,bfc,...]` | `recon` | `volume`, `bfc` |
| BIDS pipeline | `--bids-prep/post <section>` | `recon` | `rest`, `dwi` |
| Staged pipeline | `--staged-prep/post <section>` | all intermed tasks (if `--intermed`), else `recon` | `cards`, `kidvid` |
| QC | `--mriqc` | `recon` | `mriqc_preprocess`, `mriqc_post` |

---

## Intermed Tasks: Parallel Execution

The `intermed` section supports multiple tasks. All tasks listed under `intermed:` in `config.yaml` can be requested individually or together via `--intermed`:

```bash
# Single intermed task
neuropipe run ... --intermed volume --staged-prep cards

# Two intermed tasks in parallel
neuropipe run ... --intermed volume,bfc --staged-prep cards
```

**Dependency rules when multiple intermed tasks are requested:**

```
recon
    ├── volume   ┐  (parallel — no dependency between them)
    └── bfc      ┘
                 │
                 └── cards_preprocess   (waits for ALL intermed tasks)
                 └── kidvid_preprocess  (waits for ALL intermed tasks)

rest_preprocess  ← depends only on recon, never on intermed
```

- `volume` and `bfc` both wait for `recon`, but not for each other.
- Every staged prep task (`multi_stage: true`, `stage: prep`) waits for **all** requested intermed tasks.
- BIDS pipelines (`--bids-prep/post`) are unaffected; they never depend on intermed.
- If `--intermed` is omitted entirely, staged pipelines run in parallel with `recon` (no intermed dependency at all).

To add a new intermed task, add an entry under `intermed:` in `config.yaml` and a matching entry under `tasks:` in your project config. It becomes available as `--intermed <name>` immediately.

---

## Array concurrency

A task with `array: true` submits one array job covering every subject. The cap on how many run simultaneously lives on the resource profile, not here. See [`array_limit`](hpc-config.md#profile-fields) in `hpc_config.yaml`.

---

## Adding a New Pipeline Section

For a full walkthrough (writing the analysis script, registering in `config.yaml`, configuring project parameters, and adding output checks), see [How-To: Add a Custom Task](../how-to/add-custom-task.md).
