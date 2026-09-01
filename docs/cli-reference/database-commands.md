---
title: Database Commands
---

# Database Commands

Commands for verifying outputs, managing the job log database, and generating reports.

---

## `neuromaestro check-outputs`

Verifies task outputs for a set of subjects without submitting any jobs.

`--session` is required. Its value is written into every row of the output CSV, so requiring it keeps each result attributable to a session; without it, failures in a multi-session study could not be traced back to the session they came from. Projects whose checks config contains no `{session}` placeholder may pass any value.

Subjects are auto-detected from `--work` when `--subjects` is omitted.

```bash
# Auto-detect subjects, check one session
neuromaestro check-outputs \
  --project my_study \
  --work /data/work \
  --config-dir /data/config \
  --session 01

# Check multiple sessions in one run
neuromaestro check-outputs \
  --project my_study \
  --work /data/work \
  --config-dir /data/config \
  --session 01,02

# Filter to specific subjects and tasks
neuromaestro check-outputs \
  --project my_study \
  --work /data/work \
  --config-dir /data/config \
  --subjects 001,002,003 \
  --session 01 \
  --task rest_preprocess \
  --task volume

# Project without sessions: pass any value, it is unused by the path templates
neuromaestro check-outputs \
  --project ds027 \
  --work /data/work \
  --config-dir /data/config \
  --session 01

# Use a custom checks directory
neuromaestro check-outputs \
  --project my_study \
  --work /data/work \
  --config-dir /data/config \
  --session 01 \
  --checks-dir /path/to/custom/checks/
```

**Options:**

| Option | Description |
|--------|-------------|
| `--project` | Project name (required) |
| `--work` | Work/output base directory (required) |
| `--config-dir` | Path to config directory (required) |
| `--subjects` | Subject list or file path — auto-detected from `--work` if omitted |
| `--session` | Session ID(s), comma-separated (e.g. `01,02`) (required). Recorded in every CSV row. Projects without sessions may pass any value. |
| `--task` | Specific task(s) to check; repeatable; defaults to all configured |
| `--checks-dir` | Override the directory searched for `{project}_checks.yaml` |

Terminal output shows only subjects with issues, grouped by task. A full CSV is saved to `{work_dir}/check_results_{timestamp}.csv`.

→ See [Post-Run Verification](../how-to/post-run-verification.md) for a full workflow including report generation.

---

## `neuromaestro merge-logs`

Merges JSONL job logs into the SQLite database. Must be run manually after jobs complete.

```bash
# work_dir is a positional argument (no flag)
neuromaestro merge-logs /data/work/my_study

# Specify database path explicitly
neuromaestro merge-logs /data/work/my_study \
  --db-path /data/work/my_study/database/pipeline_jobs.db
```

**Arguments / Options:**

| Argument/Option | Description |
|-----------------|-------------|
| `work_dir` | Work directory (positional, required) |
| `--db-path` | Database path — auto-detected from `work_dir` if omitted |

JSONL logs are stored in `{work_dir}/database/json/{task_name}/` and `{work_dir}/database/json/_pipeline/`. After merging, processed JSON files are archived.

Only logs containing both a start and an end event are merged. A job killed before
the wrapper could write its end event (SIGKILL, an out-of-memory kill, or a node
failure) leaves an incomplete log, which stays in place and is reported at the end
of the run:

```
Skipped 7 incomplete log(s) with no end event: recon (2), rest_preprocess (5)
```

Those jobs are absent from the database entirely rather than recorded as failed, so
use `check-outputs` to see whether their outputs are complete.

---

## `neuromaestro force-rebuild`

Rebuilds a fresh SQLite database from all JSONL logs, including files already moved to `archived/` subdirectories by a previous `merge-logs`. The original database is never modified.

```bash
# Auto-detect database path from work directory
neuromaestro force-rebuild /data/work/my_study

# Specify database path explicitly
neuromaestro force-rebuild /data/work/my_study \
  --db-path /data/work/my_study/database/pipeline_jobs.db
```

The new database is written as `pipeline_jobs_rebuild_{timestamp}.db` next to the original.

**Arguments / Options:**

| Argument/Option | Description |
|-----------------|-------------|
| `work_dir` | Work directory (positional, required) |
| `--db-path` | Original database path — auto-detected from `work_dir` if omitted |

Use this when:
- The database is corrupted or has missing records that `merge-logs` cannot recover (because the JSONL files were already archived)
- You want a clean historical rebuild after restoring from backup

→ See [Post-Run Verification](../how-to/post-run-verification.md) for when to use this vs `merge-logs`.

---

## `neuromaestro generate-report`

Generates a standalone HTML report from the job tracking database: summary statistics, per-subject status heatmap, and task durations.

```bash
# Minimal — report saved next to the database
neuromaestro generate-report \
  --db-path /data/work/my_study/database/pipeline_jobs.db \
  --project my_study \
  --check-results /data/work/my_study/check_results_20260401_120000.csv

# With --config-dir so tasks are listed in pipeline order
neuromaestro generate-report \
  --db-path /data/work/my_study/database/pipeline_jobs.db \
  --project my_study \
  --config-dir /data/config \
  --check-results /data/work/my_study/check_results_20260401_120000.csv

# Filter by session
neuromaestro generate-report \
  --db-path /data/work/my_study/database/pipeline_jobs.db \
  --project my_study \
  --session 01 \
  --check-results /data/work/my_study/check_results_20260401_120000.csv

# Save to a specific path
neuromaestro generate-report \
  --db-path /data/work/my_study/database/pipeline_jobs.db \
  --project my_study \
  --session 01 \
  --check-results /data/work/my_study/check_results_20260401_120000.csv \
  -o /data/reports/my_study_report.html
```

**Options:**

| Option | Description |
|--------|-------------|
| `--db-path` | Path to `pipeline_jobs.db` (required) |
| `--project` | Project name (required) |
| `--session` | Filter by session ID (recommended when multiple projects share a database) |
| `--output` / `-o` | Output HTML file, or a directory (the `pipeline_report_{project}_{timestamp}.html` name is added inside it). Defaults to that name next to the database |
| `--check-results` | Path to a `check_results_*.csv` from `check-outputs` (required). Run `check-outputs` first to generate this file. |
| `--config-dir` | Path to config directory. Used to list report tasks in pipeline order instead of alphabetically. Defaults to `$NEUROMAESTRO_CONFIG_DIR`; the report still renders without it. |

→ See [Post-Run Verification](../how-to/post-run-verification.md) for a full workflow and report contents description.

---

## Database Schema

The job tracking SQLite database (`{work_dir}/database/pipeline_jobs.db`) has four tables:

### `job_status` — per-subject job records

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-increment primary key (row number) |
| `execution_id` | INTEGER | Links to `pipeline_executions.execution_id` |
| `subject` | TEXT | Subject ID |
| `task_name` | TEXT | Task name |
| `session` | TEXT | Session label |
| `start_time` | TEXT | ISO datetime |
| `end_time` | TEXT | ISO datetime |
| `status` | TEXT | `SUCCESS`, `FAILED`, `CANCELLED`, `RUNNING` |
| `exit_code` | INTEGER | Shell exit code |
| `error_msg` | TEXT | Error message if failed |
| `duration_hours` | REAL | Runtime in hours |
| `log_path` | TEXT | Path to subject log file |
| `job_id` | TEXT | SLURM job/array task ID |
| `node_name` | TEXT | Compute node hostname |

### `pipeline_executions` — full pipeline run records

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-increment primary key (row number) |
| `execution_id` | INTEGER | Timestamp-based ID generated at submission time; used to link `job_status` and `wrapper_scripts` |
| `execution_time` | TIMESTAMP | When the run was submitted |
| `command_line` | TEXT | Full `neuromaestro run` command |
| `project_name` | TEXT | Project name |
| `session` | TEXT | Session label |
| `input_dir` | TEXT | `--input` path |
| `output_dir` | TEXT | `--output` path |
| `work_dir` | TEXT | `--work` path |
| `subjects` | TEXT | Comma-separated subject list |
| `requested_tasks` | TEXT | Comma-separated task list |
| `dry_run` | BOOLEAN | Whether it was a dry-run |
| `total_jobs` | INTEGER | Number of SLURM jobs submitted |
| `status` | TEXT | `RUNNING`, `COMPLETED`, `FAILED` |
| `error_msg` | TEXT | Error message if submission failed |

### `command_outputs` — captured stdout/stderr

One row per subject per task per run, written when the analysis script finishes.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-increment primary key (row number) |
| `execution_id` | INTEGER | Links to `pipeline_executions.execution_id` |
| `subject` | TEXT | Subject ID |
| `task_name` | TEXT | Task name |
| `session` | TEXT | Session label |
| `script_name` | TEXT | Script filename |
| `command` | TEXT | Full command string executed |
| `stdout` | TEXT | Last 50 lines of the job log (stdout + stderr combined — the wrapper redirects both streams into one log file) |
| `stderr` | TEXT | Always NULL in current wrapper — reserved for future use |
| `exit_code` | INTEGER | Shell exit code |
| `execution_time` | TIMESTAMP | When the script ran |
| `log_file_path` | TEXT | Path to the per-subject `.log` file |
| `job_id` | TEXT | SLURM job/array task ID |

### `wrapper_scripts` — sbatch submission records

One row per `sbatch` call. Stores the full wrapper script content split into sections so the exact submission environment can always be reconstructed. Also carries `execution_id` to link back to the pipeline run. Schema documented in [Logging System & Resume](../internals/logging-resume.md#sqlite-tables).

### Example Queries

```sql
-- Find subjects where the script exited non-zero for a task
-- Note: status='FAILED' only catches non-zero exits; silent failures (exit 0, bad output)
-- require check-outputs. Also query for 'CANCELLED' to see SLURM-killed jobs.
SELECT subject, task_name, status, error_msg, start_time
FROM job_status
WHERE task_name = 'rest_preprocess' AND status != 'SUCCESS'
ORDER BY start_time DESC;

-- Jobs from last 7 days
SELECT subject, task_name, status, duration_hours
FROM job_status
WHERE start_time > datetime('now', '-7 days');

-- Full pipeline run history
SELECT execution_time, command_line, total_jobs, status
FROM pipeline_executions
ORDER BY execution_time DESC
LIMIT 10;

-- All jobs submitted in a specific pipeline run
-- (execution_id is the timestamp-based ID printed at submission time)
SELECT j.subject, j.task_name, j.status, j.duration_hours
FROM job_status j
JOIN pipeline_executions p ON j.execution_id = p.execution_id
WHERE p.execution_id = 1699000000000
ORDER BY j.task_name, j.subject;
```

---

## Log Directory Structure

```
{work_dir}/
├── database/
│   ├── pipeline_jobs.db          # SQLite job database
│   └── backup/
│       └── pipeline_jobs.backup_*.db  # Auto-backups (created before each merge-logs)
│   ├── json/
│       ├── {task_name}/
│       │   ├── {job_id}_*.jsonl    # Per-job JSONL logs (raw, before merge)
│       │   └── archived/
│       └── _pipeline/
│           ├── execution_*.jsonl   # Pipeline-level event logs
│           ├── wrapper_*.jsonl     # Wrapper script content per submission
│           └── archived/
└── log/
    ├── wrapper/
    │   └── {task}_{timestamp}_wrapper.sh   # Generated SLURM scripts
    └── {task_name}/
        ├── {task}_{job_id}.out     # SLURM stdout
        └── {task}_{job_id}.err     # SLURM stderr
```

:::{note}
The database is **automatically backed up** before every `neuromaestro merge-logs`. Backups are stored in `{db_dir}/backup/` with a timestamp suffix; the last 10 are kept.
:::
