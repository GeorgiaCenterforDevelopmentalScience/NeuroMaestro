---
title: "neuromaestro run"
---

# `neuromaestro run`

```
neuromaestro run [OPTIONS]
```

---

## Required Arguments

| Argument | Description | Example |
|----------|-------------|---------|
| `--subjects` | Subject IDs — comma-separated string or path to a text file (one ID per line, or comma-separated) | `001,002` or `subjects.txt` |
| `--input` | Input data directory | `/data/BIDS` |
| `--output` | Output base directory | `/data/processed` |
| `--work` | Work base directory (logs, database, temp files) | `/data/work` |
| `--config-dir` | Path to config directory — must contain `config.yaml`, `hpc_config.yaml`, and `project_config/`. Optional if `$NEUROMAESTRO_CONFIG_DIR` is set. | `/data/config` |
| `--project` | Project name — loads `{project}_config.yaml` from `--config-dir/project_config/` | `my_study` |
| `--session` | Session or wave ID | `01` |

:::{important}
**Project name is automatically appended** to `--output` and `--work`:
- Actual output directory: `{--output}/{--project}/`
- Actual work directory: `{--work}/{--project}/`

So `--output /data/processed --project my_study` stores data under `/data/processed/my_study/`.

The database path is resolved differently: `$WORK_DIR` in the project config's
`database.db_path` expands to `--work` **without** the project name. With the default
`$WORK_DIR/database/pipeline_jobs.db`, projects sharing a `--work` also share one
database and one JSON log directory. Use a separate `--work` per project to keep
them apart.
:::

---

## Processing Options

The pipeline uses two categories of multi-step pipelines:

- **BIDS pipelines** (`--bids-prep`/`--bids-post`): containerized tools (fMRIPrep, XCP-D, QSIPrep) that take BIDS input directly. Depend on `recon` when `--prep recon` or `--prep unzip_recon` is also requested.
- **Staged pipelines** (`--staged-prep`/`--staged-post`): AFNI-based task fMRI that optionally depend on the structural step.

| Option | Values | Description |
|--------|--------|-------------|
| `--prep` | `unzip` \| `recon` \| `unzip_recon` | Data preparation |
| `--intermed` | `volume` \| `volume,bfc` \| ... | Intermed tasks (comma-separated); required before `--staged-prep` |
| `--bids-prep` | `rest` \| `dwi` \| `rest,dwi` | BIDS pipeline preprocessing |
| `--bids-post` | `rest` \| `dwi` \| `rest,dwi` | BIDS pipeline postprocessing |
| `--staged-prep` | `emomatching` \| `stopsignal` \| `emomatching,stopsignal,workingmemory` | Staged pipeline preprocessing |
| `--staged-post` | `emomatching` \| `stopsignal` \| `emomatching,stopsignal,workingmemory` | Staged pipeline postprocessing |
| `--mriqc` | `individual` \| `group` \| `all` | Quality control (MRIQC) |

Pipeline section names (e.g. `rest`, `dwi`, `emomatching`) must match section names defined in `config.yaml`.

---

## Task Expansion Rules

For full dependency and parallel execution behavior, see [Pipeline Reference → CLI Flags Overview](../pipeline-reference/index.md#cli-flags-overview).

---

## Execution Options

| Option | Description |
|--------|-------------|
| `--dry-run` | Print SLURM commands without submitting. Wrapper scripts are still written to `log/wrapper/` so you can inspect them. |
| `--resume` | Skip subjects whose outputs already pass checks in `{project}_checks.yaml`. Submits full count with warning if file is missing. |
| `--skip-preflight` | Skip pre-flight config schema and filesystem checks. |
| `--skip-bids-validation` | Skip BIDS format validation (runs automatically when `--bids-prep` or `--mriqc individual/all` is used). |
| `--wait` | Wait for all submitted jobs to complete before exiting |
| `--polling-interval N` | Seconds between SLURM status polls when `--wait` is active (default: 60) |

---

## Passing Subjects

**Comma-separated:**
```bash
--subjects 001,002,003
```

**Repeated flags (both forms are equivalent):**
```bash
--staged-prep emomatching,stopsignal
--staged-prep emomatching --staged-prep stopsignal
```

**From a text file (one ID per line, or comma-separated):**
```bash
# one per line
printf "001\n002\n003" > subjects.txt

# or comma-separated
echo "001,002,003" > subjects.txt

neuromaestro run --subjects subjects.txt ...
```

The subject prefix (`sub-`) comes from the project config `prefix` field; do not include it in subject IDs.

:::{tip}
On HPC systems, pasting a long comma-separated list directly into the terminal can hit the shell's line-length limit and cause an error. If you have more than a few dozen subjects, use a text file instead.
:::

---

## `--dry-run`

Generates all wrapper scripts and prints the exact `sbatch` commands, but does not queue anything. Use it to:
- Verify module names and paths before a large run
- Preview SLURM array sizes
- Inspect generated env-vars in `{work}/log/wrapper/`

---

## `--resume`

Before submitting each task's array job, the pipeline calls `OutputChecker` to find which subjects already have valid outputs. Only pending subjects are included in the array. If a task has no pending subjects at all, it is skipped entirely and downstream tasks lose their `afterok` dependency on it.

If `{project}_checks.yaml` is missing, `--resume` is silently ignored (with a warning) and all subjects are submitted.
