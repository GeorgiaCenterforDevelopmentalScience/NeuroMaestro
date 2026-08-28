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

The `scripts_dir` field in each project config points to the corresponding scripts subdirectory. Results checks are loaded by `--resume` to validate outputs; see [DAG Execution & Preflight](dag-execution.md) for how checks are consumed.

---

## Bundle Purposes

### `dagtest`
Tests only the job scheduling and pre/post logic — DAG wiring, SLURM dependency chains, database state transitions. The shell scripts are stubs or near-stubs that exit quickly without running real neuroimaging tools. Use this when changing the execution engine or logging layer and you need fast feedback without waiting for actual compute.

### `test`
A closer-to-real integration test: scripts run the actual tools but skip or shorten expensive preprocessing steps (e.g. reduced TR counts, skipped resampling passes). Intended for end-to-end validation on a small dataset where full runtime would be impractical. Use this before merging pipeline logic changes.

### `branch`
The production config for the real BRANCH dataset. Scripts are the full-fidelity versions used in live runs. This is the reference for all task parameters (TR counts, container versions, motion thresholds, etc.).

### `ds027`
The published demonstration run on AOMIC-PIOP2 (OpenNeuro `ds002790`), covering 13 tasks over 30 participants. Shipped exactly as it ran, so its paths and module names are specific to the original cluster and must be substituted before use. This is the bundle a reader reproduces in [Reproduce the Published Example](../getting-started/reproduce-ds027.md). Do not retrofit changes into it that were not part of the reported run, since the config is the reference for what that run did.

### `template`
A blank-slate copy of `branch` with all site-specific paths replaced by `/path/to/...` placeholders. Intended as a starting point for new deployments. Not used in any automated run.

---

## Adding or Modifying a Bundle

When adding a new task or changing a script interface, update the bundles consistently:

1. Add/edit the task entry in each `*_config.yaml` under `tasks:`.
2. Add/edit the corresponding shell script in each `scripts/*/` subdirectory.
3. Add/edit the output check entry in each `*_checks.yaml`.

`dagtest` and `test` scripts may be simplified versions. `branch` must match production behaviour. `template` should use placeholder paths only. `ds027` is frozen as a published record and is excluded from this rule, so leave it alone unless a change is genuinely required for the bundle to keep loading.
