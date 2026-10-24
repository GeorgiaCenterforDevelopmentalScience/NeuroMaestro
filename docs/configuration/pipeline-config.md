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

`{base_output}` in `output_pattern` is the `run --output` directory with the project name appended (e.g. `/data/processed/my_study`). It is the only placeholder `output_pattern` accepts.

The excerpt below shows the main sections. The bundled `config.yaml` also defines further staged sections (`ica_task`, `ica_rest`, `emomatching`, `stopsignal`, `workingmemory`) laid out like `cards`.

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
# Every staged prep task waits for ALL requested intermed tasks to finish.
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
    scripts: [sdcflows.sh]
    output_pattern: "{base_output}/BIDS_derivatives/sdcflows"

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
# multi_stage: true → the prep task depends on all requested intermed tasks when --intermed is used
cards:
  - name: cards_preprocess
    stage: prep
    profile: standard
    array: true
    input_from: recon
    multi_stage: true
    scripts: [afni_cards_preprocessing.sh]
    output_pattern: "{base_output}/AFNI_derivatives"

  - name: cards_postprocess
    stage: post
    profile: standard
    input_from: cards_preprocess
    multi_stage: true
    scripts: [afni_cards_postprocessing.sh]
    output_pattern: "{base_output}/postprocessing/group/cards"

kidvid:
  - name: kidvid_preprocess
    stage: prep
    profile: standard
    array: true
    input_from: recon
    multi_stage: true
    scripts: [afni_kidvid_preprocess.sh]
    output_pattern: "{base_output}/AFNI_derivatives"

  - name: kidvid_postprocess
    stage: post
    profile: standard
    input_from: kidvid_preprocess
    multi_stage: true
    scripts: [afni_kidvid_postprocessing.sh]
    output_pattern: "{base_output}/postprocessing/group/kidvid"

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
| `profile` | **Yes** | Resource profile from `hpc_config.yaml`. Required on every task, there is no default. Tune freely, changing one only affects future submissions. |
| `scripts` | **Yes** | Shell script filename(s) relative to `scripts_dir`. Update when swapping the underlying analysis script. |
| `stage` | **Set at design time** | `prep` or `post` — controls intra-section dependency order. Do not change after the section is in use. |
| `array` | **Rarely** | `true` = one SLURM array job covering all subjects, with one array element per subject. Nearly always `true` for subject-level tasks, and `false` only for group-level steps like `mriqc_post`. How many of those subjects run at once is set by `array_limit` on the task's resource profile, in [`hpc_config.yaml`](hpc-config.md). |
| `input_from` | **Set at design time** | Name of the upstream task whose output directory becomes this task's `$INPUT_DIR`, but only when that upstream task is requested in the same run. Otherwise `$INPUT_DIR` is the `run --input` directory. It controls where the task reads data from and adds no dependency edge (job dependency order is handled internally by the pipeline). |
| `output_pattern` | **Before first run only** | Directory the task writes to (`$OUTPUT_DIR`), and the `$INPUT_DIR` of downstream tasks requested in the same run. `--resume` does not read it: it checks the `output_path` in your [output checks file](output-checks.md). Changing it after subjects have been processed sends new outputs to a different folder than earlier ones, so update the matching `output_path` in `{project}_checks.yaml` at the same time. |
| `multi_stage` | **Set at design time** | `true` = this task belongs to a staged pipeline. When any `--intermed` tasks are requested, the section's `stage: prep` task waits for **all** of them to finish before starting. Without `--intermed`, the prep task waits for `recon` when `recon` is in the same command, and has no dependency otherwise. The `stage: post` task waits only for its own prep task when both are requested. Set when first creating the section. Do not toggle later. |

---

## Pipeline Types

| Type | CLI flag | Input data from | Examples |
|------|----------|-----------|---------|
| Prep/utility | `--prep` | — | `unzip`, `recon` |
| Intermed | `--intermed volume[,bfc,...]` | `recon` | `volume`, `bfc` |
| BIDS pipeline | `--bids-prep/post <section>` | `recon` | `rest`, `dwi` |
| Staged pipeline | `--staged-prep/post <section>` | all intermed tasks (if `--intermed`), else `recon` (prep task only) | `cards`, `kidvid` |
| QC | `--mriqc` | `recon` | `mriqc_preprocess`, `mriqc_post` |

---

## Intermed Tasks: Parallel Execution

The `intermed` section supports multiple tasks. All tasks listed under `intermed:` in `config.yaml` can be requested individually or together via `--intermed`:

```bash
# Single intermed task
neuromaestro run ... --intermed volume --staged-prep cards

# Two intermed tasks in parallel
neuromaestro run ... --intermed volume,bfc --staged-prep cards
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
- If `--intermed` is omitted entirely, staged prep tasks wait for `recon` when it is in the same command, and have no dependency otherwise.

To add a new intermed task, add an entry under `intermed:` in `config.yaml` and, if the task needs parameters, a matching entry under `tasks:` in your project config. It becomes available as `--intermed <name>` immediately.

---

## Array concurrency

A task with `array: true` submits one array job covering every subject. The cap on how many run simultaneously lives on the resource profile, not here. See [`array_limit`](hpc-config.md#profile-fields) in `hpc_config.yaml`.

---

## Adding a New Pipeline Section

For a full walkthrough (writing the analysis script, registering in `config.yaml`, configuring project parameters, and adding output checks), see [How-To: Add a Custom Task](../how-to/add-custom-task.md).
