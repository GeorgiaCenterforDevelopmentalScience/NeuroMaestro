---
title: Rerun Specific Subjects
---

# How To: Rerun Specific Subjects

## Scenario

Some subjects failed or produced incomplete outputs and you want to reprocess only them, without resubmitting the subjects that already completed successfully.

## Option 1: Explicit Subject List

Pass only the failing subjects to `--subjects`:

```bash
neuropipe run \
  --subjects 003,007,012 \
  --input /data/BIDS \
  --output /data/processed \
  --work /data/work \
  --config-dir /data/config \
  --project my_study \
  --session 01 \
  --intermed volume \
  --bids-prep rest
```

### Finding which subjects failed

Query the job database:

```bash
sqlite3 /data/work/my_study/database/pipeline_jobs.db \
  "SELECT DISTINCT subject FROM job_status
   WHERE task_name = 'rest_preprocess' AND status = 'FAILED';"
```

Or use `check-outputs` to find subjects with missing files:

```bash
neuropipe check-outputs \
  --project my_study \
  --work /data/work \
  --config-dir /data/config \
  --subjects $(cat all_subjects.txt | tr '\n' ',') \
  --session 01 \
  --task rest_preprocess
```

Then create a file with just those IDs and pass it:

```bash
# subjects_failed.txt
003
007
012

neuropipe run --subjects subjects_failed.txt ...
```

## Option 2: `--resume` Flag

If you want the pipeline to automatically skip subjects that already have valid outputs:

```bash
neuropipe run \
  --subjects 001,002,003,007,012 \   # pass all subjects
  --input /data/BIDS \
  --output /data/processed \
  --work /data/work \
  --config-dir /data/config \
  --project my_study \
  --session 01 \
  --intermed volume \
  --resume
```

The pipeline checks `{project}_checks.yaml` for each task and silently excludes subjects that already passed. Subjects with missing or incomplete outputs are submitted as normal.

:::{note}
`--resume` requires `{project}_checks.yaml` to exist inside `<config-dir>/results_check/`. See [Output Checks Configuration](../configuration/output-checks.md) for how to define check rules.
:::

## Option 3: Dry-Run First

Always validate your subject list before a large rerun:

```bash
neuropipe run --subjects subjects_failed.txt \
  --project my_study --config-dir /data/config ... \
  --intermed volume --dry-run
```

This shows exactly which SLURM array jobs would be submitted without actually queuing anything.
