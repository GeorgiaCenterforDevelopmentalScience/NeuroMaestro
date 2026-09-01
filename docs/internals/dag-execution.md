---
title: DAG Execution & Preflight
---

# DAG Execution & Preflight

This page covers the run lifecycle, config layer merging, DAG implementation, and preflight validation.

For user-facing behavior (dependency rules, output checks config syntax, pre-flight check list), see [Pipeline Reference](../pipeline-reference/index.md).

---

## Lifecycle of a `neuromaestro run` Call

```
neuromaestro run [flags]
      │
      ▼
 1. Parse flags; validate --input directory exists
 2. Adjust paths: work_dir → work_dir/project, output_dir → output_dir/project
 3. Load project config  (config/project_config/{project}_config.yaml)
 4. [--skip-preflight?] PreflightChecker.run_all() → validate schema + task/module references
      └─ any ERROR → exit (no files written yet)
 5. TaskRegistry.expand_tasks() → flat list of concrete task names
 6. [--bids-prep or --mriqc individual|all, unless --skip-bids-validation]
      └─ run BIDS validator on input_dir
 7. Resolve db_path (expand $WORK_DIR in project config database.db_path)
 8. Create database directory
 9. log_pipeline_execution() → write pipeline_start event to JSONL → return execution_id
10. [--resume] load per-project checks config → initialise OutputChecker
11. DAGExecutor.build_dag() → apply four dependency rules → topological sort → execution_order
      └─ print execution plan to terminal
12. For each task in execution_order:
      a. Collect upstream job IDs for --dependency chaining
      b. [--resume] OutputChecker.get_pending_subjects() → filter subject list
      c. submit_slurm_job() → create wrapper script → sbatch → return job_id
      d. Store job_id keyed by task name for downstream chaining
13. Print submission summary (task → job IDs)
14. [--wait] wait_for_jobs() → poll scheduler until all jobs finish
15. update_pipeline_execution() → append pipeline_update event to same JSONL file
```

Key points:

- Steps 4–6 all run **before** any database or JSONL files are touched. A preflight failure exits cleanly with no side effects.
- `pipeline_start` (step 9) is written to **JSONL only — not directly to SQLite**. SQLite gets it later via `neuromaestro merge-logs`. See [Logging System & Resume](logging-resume.md#jsonl-vs-sqlite).
- The execution plan (step 11) is built and printed **before** the first job is submitted, so you can verify dependencies before anything hits the cluster.

---

## Config Resolution

Every task has a **global config** entry in `config/config.yaml` (shared across all projects) and an optional **project override** in `config/project_config/{project}_config.yaml` under the `tasks:` key.

At submission time, `find_task_config_by_name_with_project()` in [config_utils.py](../../src/neuromaestro/pipeline/utils/config_utils.py) merges the two layers:

```python
merged_config = global_task_config.copy()
merged_config.update(project_task_overrides)   # project values win
```

Any field in the global config can be overridden per project. For example:

```yaml
# config/config.yaml
intermed:
  - name: volume
    profile: standard_short
    blur_size: 4.0

# config/project_config/my_study_config.yaml
tasks:
  volume:
    blur_size: 6.0        # overrides global blur_size
    profile: heavy_long   # overrides global profile
```

The merged result used at submission time: `{name: "volume", profile: "heavy_long", blur_size: 6.0}`.

Fields absent from the project override are inherited unchanged from the global config. The DAG builder calls this merge once per task when registering nodes, so the same merged config drives both dependency resolution and wrapper generation.

---

## DAG: Code Walkthrough

> For what the dependency rules *mean* from a user perspective, see [How the DAG works](../pipeline-reference/index.md#how-the-dag-works). This section covers the implementation in [dag.py](../../src/neuromaestro/pipeline/dag.py).

### Step 1: Task name expansion (`TaskRegistry`)

`TaskRegistry.expand_tasks()` converts CLI flag values into a flat list of concrete task names:

```
--prep unzip_recon   →  ["unzip", "recon"]
--bids-prep rest     →  ["rest_preprocess"]
--staged-prep cards  →  ["cards_preprocess"]
```

BIDS and staged pipelines call `get_tasks_from_section(section, stage)`, which looks up tasks in `config.yaml` by section name and `stage:` field. Intermed names are validated against `get_all_task_names("intermed")`; unknown names are skipped with a warning.

### Step 2: Node registration

`build_dag()` calls `_register_task()` for each name. This calls `find_task_config_by_name_with_project()` (see [Config Resolution](#config-resolution)) and creates a `TaskNode` dataclass holding the merged config and an empty dependency set.

### Step 3: Four dependency rules

Four private methods are called in sequence to populate each node's `dependencies` set:

| Method | Rule applied |
|--------|-------------|
| `_apply_prep_sequence` | `recon` depends on `unzip` when both are requested |
| `_apply_recon_dependencies` | Every non-`multi_stage` downstream task depends on `recon` |
| `_apply_intermed_dependencies` | All requested intermed tasks become dependencies of staged prep tasks (`multi_stage: true` + `stage: prep`) |
| `_apply_section_dependencies` | Within each `config.yaml` section, `stage: post` tasks depend on all `stage: prep` tasks in the same section |

`multi_stage: true` is the flag that distinguishes staged pipelines from BIDS pipelines. `_apply_recon_dependencies` explicitly skips `multi_stage` tasks so they are not wired directly to `recon` — they wait for intermed instead (rule 3). If no intermed was requested, `_apply_intermed_dependencies` returns early (the intermed set is empty), so staged tasks have no upstream dependency and run in parallel with recon.

### Step 4: Topological sort (Kahn's algorithm)

`_topological_sort()` initialises a queue with all zero-in-degree nodes and processes them in FIFO order, decrementing in-degrees as each node is consumed. The result is the submission order. If the result list is shorter than the total node count, a cycle exists and a `ValueError` is raised.

---

## Preflight: Implementation Notes

`PreflightChecker` in [preflight.py](../../src/neuromaestro/pipeline/utils/preflight.py) validates the project config structure before any jobs are submitted. For the list of checks and example output, see [Pre-flight Checks](../pipeline-reference/index.md#pre-flight-checks).

### Why there are no filesystem checks

The module docstring explains the deliberate design choice:

> *Filesystem checks are intentionally omitted: NFS/GPFS/Lustre mounts on HPC clusters can cause `Path.exists()` to block indefinitely at the kernel level.*

On HPC clusters, `Path.exists()` on a network filesystem can stall for minutes or hang permanently if a mount point is degraded. Preflight therefore only validates config schema and cross-references — it never touches the filesystem. Filesystem state is assumed correct at job runtime.

### Adding a new check

Each check is a method on `PreflightChecker` that calls `self._err(category, message)` or `self._warn(category, message)`. Add the method and call it from `run_all()`. Issues are collected into a `PreflightResult`; any `ERROR`-severity issue sets `result.ok = False` and blocks submission.
