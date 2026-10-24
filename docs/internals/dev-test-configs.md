---
title: Dev & Test Config Modes
---

# Dev & Test Config Modes

The pipeline ships with five named config/script/check bundles used at different stages of development and deployment. Each bundle consists of three matched files:

| Bundle | Project config | Scripts dir | Results checks |
|--------|---------------|-------------|----------------|
| `dagtest` | `project_config/dagtest_config.yaml` | `scripts/dagtest/` | `results_check/dagtest_checks.yaml` |
| `test` | `project_config/test_config.yaml` | `scripts/test/` | `results_check/test_checks.yaml` |
| `branch` | `project_config/branch_config.yaml` | `scripts/branch/` | `results_check/branch_checks.yaml` |
| `ds027` | `project_config/ds027_config.yaml` | `scripts/ds027/` | `results_check/ds027_checks.yaml` |
| `template` | `project_config/template_config.yaml` | `scripts/template/` | `results_check/template_checks.yaml` |

In `dagtest`, `test` and `branch`, the `scripts_dir` field is the relative path `scripts/<bundle>`, which is resolved against the directory `neuromaestro run` is started from. `ds027` keeps the absolute scripts path of the cluster it ran on, and `template` has the placeholder `path/to/scripts/`. Results checks are loaded by `--resume` and `check-outputs` to validate outputs. See [Logging System & Resume](logging-resume.md#resume-output-checking-flow) for how checks are consumed.

---

## Bundle Purposes

### `dagtest`
Tests the job scheduling and pre/post logic: DAG wiring, SLURM dependency chains, database state transitions. Most scripts are cut down to finish quickly. `unzip_rename.sh` only prints its environment, `dcm2bids_convert_BIDS.sh` runs `dcm2bids_helper`, the T1w warp script only checks that its inputs exist, `afni_proc.py` writes its proc script without `-execute`, the group-level AFNI scripts stop after setup, MRIQC and SDCFlows run with `--dry-run`, and QSIPrep and QSIRecon run with `--sloppy --boilerplate`. Two scripts are exceptions: `fmriprep_rs.sh` and `xcpd_rs.sh` run fMRIPrep (with `--fs-no-reconall`) and XCP-D in full. The bundle also carries `one_sample_ttest.sh`, which no task in `config.yaml` references. Use this when changing the execution engine or logging layer and you need fast feedback without waiting for most of the compute.

### `test`
A closer-to-real integration test: scripts run the actual tools but skip or shorten expensive preprocessing steps (e.g. `--sloppy` for QSIPrep, QSIRecon and SDCFlows, fMRIPrep with `--fs-no-reconall` and no CIFTI output, MRIQC on T1w only, and a two-condition `afni_proc.py` model for Cards). Intended for end-to-end validation on a small dataset where full runtime would be impractical. Use this before merging pipeline logic changes.

### `branch`
The production config for the real BRANCH dataset. Scripts are the full-fidelity versions used in live runs. This is the reference for all task parameters (TR counts, container versions, motion thresholds, etc.).

### `ds027`
The published demonstration run on AOMIC-PIOP2 (OpenNeuro `ds002790`), covering 13 tasks over 30 participants. Shipped exactly as it ran, so its paths and module names are specific to the original cluster and must be substituted before use. This is the bundle a reader reproduces in [Reproduce the Published Example](../getting-started/reproduce-ds027.md). Do not retrofit changes into it that were not part of the reported run, since the config is the reference for what that run did.

### `template`
The starting point for new deployments, with all site-specific paths replaced by `/path/to/...` placeholders. It follows `branch` and adds the `bfc`, `ica_task` and `ica_rest` tasks with their scripts (`sdcflows.sh`, `ica_*.sh`). `neuromaestro init` copies its scripts into a new study, and the end-to-end dry-run test (`tests/test_e2e_dry_run.py`) runs against those copies.

---

## Adding or Modifying a Bundle

When adding a new task or changing a script interface, update the bundles consistently:

1. Add/edit the task entry in each `*_config.yaml` under `tasks:`.
2. Add/edit the corresponding shell script in each `scripts/*/` subdirectory.
3. Add/edit the output check entry in each `*_checks.yaml`.

`dagtest` and `test` scripts may be simplified versions. `branch` must match production behaviour. `template` should use placeholder paths only. `ds027` is frozen as a published record and is excluded from this rule, so leave it alone unless a change is genuinely required for the bundle to keep loading.
