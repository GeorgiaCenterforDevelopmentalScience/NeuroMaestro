---
title: Logging System & Resume
---

# Logging System & Resume

This page covers the dual JSONL/SQLite logging architecture, the merge and force-rebuild workflows, automatic database backup, and the resume output-checking flow.

---

## Logging System

The pipeline uses a **dual logging** approach: raw JSONL event files are written immediately on compute nodes (crash-safe), and a SQLite database is built from them via `neuromaestro merge-logs`.

### Directory structure

```
{work_dir}/
└── database/
    ├── pipeline_jobs.db               # SQLite (queryable)
    ├── backup/
    │   └── pipeline_jobs.backup_{ts}.db   # auto-backup before each merge-logs (last 10 kept)
    └── json/
        ├── _pipeline/
        │   ├── execution_{id}.jsonl       # pipeline-level events (start + update)
        │   ├── wrapper_{task}_{ts}.jsonl  # wrapper script content per submission
        │   └── archived/                  # moved here after merge
        └── {task_name}/
            ├── {job_id}_{timestamp}.jsonl # per-subject events (start + end + output)
            └── archived/                  # moved here after merge

{work_dir}/log/
    ├── wrapper/
    │   └── {script}_{timestamp}_wrapper.sh
    ├── subjects/
    │   └── sub-{subject}/
    │       └── {task}_{job_id}_{array_task_id}_{timestamp}.log  # per-subject log (array jobs)
    └── {task_name}/
        ├── {task}_%A-%a.out       # SLURM stdout
        ├── {task}_%A-%a.err       # SLURM stderr
        └── {task}_{job_id}_{timestamp}.log  # per-subject log (non-array jobs)
```

`{work_dir}` here is the project-level directory (`--work / --project`, e.g. `/data/work/my_study`). The `database/` path is taken from `database.db_path` in the project config — `json/` and `backup/` sit next to the `.db` file.

### Events logged

Every significant event is written as a JSON line (JSONL) with `fsync()` to survive cluster crashes:

| Event | Written by | Trigger | Key fields |
|-------|-----------|---------|-----------|
| `pipeline_start` | Python (submit host) | `neuromaestro run` begins | command line, subjects, tasks, dry_run |
| `pipeline_update` | Python (submit host) | All tasks submitted | status (COMPLETED/FAILED), total_jobs |
| `wrapper_script` | Python (submit host) | Immediately after `sbatch` | task_name, job_id, full wrapper content split by section |
| `start` | Bash → Python CLI (compute node) | Subject begins executing | subject, task, job_id, node |
| `end` | Bash → Python CLI (compute node) | Subject finishes | subject, task, status, exit_code, duration_hours, error_msg |
| `command_output` | Bash → Python CLI (compute node) | Script completes | stdout and stderr (each truncated to last 50 lines, stored separately) |

Status values in `end` events: `SUCCESS`, `FAILED`, `CANCELLED` (SIGTERM/SIGINT caught via trap).

### SQLite tables

```sql
-- One row per subject per task
CREATE TABLE job_status (
    id             INTEGER PRIMARY KEY,
    execution_id   INTEGER,    -- links to pipeline_executions.execution_id
    subject        TEXT,
    task_name      TEXT,
    session        TEXT,
    start_time     TEXT,
    end_time       TEXT,
    status         TEXT,       -- SUCCESS / FAILED / CANCELLED / RUNNING
    exit_code      INTEGER,
    error_msg      TEXT,
    duration_hours REAL,
    log_path       TEXT,
    job_id         TEXT,
    node_name      TEXT
);

-- One row per neuromaestro run invocation
CREATE TABLE pipeline_executions (
    id             INTEGER PRIMARY KEY,
    execution_id   INTEGER,    -- timestamp-based ID; join target for job_status and wrapper_scripts
    execution_time TIMESTAMP,
    command_line   TEXT,
    project_name   TEXT,
    session        TEXT,
    input_dir      TEXT,
    output_dir     TEXT,
    work_dir       TEXT,
    subjects       TEXT,
    requested_tasks TEXT,
    dry_run        BOOLEAN,
    total_jobs     INTEGER,
    status         TEXT,       -- RUNNING / COMPLETED / FAILED
    error_msg      TEXT
);

-- One row per script execution (stdout/stderr captured)
CREATE TABLE command_outputs (
    id             INTEGER PRIMARY KEY,
    execution_id   INTEGER,    -- links to pipeline_executions.execution_id
    subject        TEXT,
    task_name      TEXT,
    session        TEXT,
    script_name    TEXT,
    command        TEXT,
    stdout         TEXT,
    stderr         TEXT,
    exit_code      INTEGER,
    execution_time TIMESTAMP,
    log_file_path  TEXT,
    job_id         TEXT
);

-- One row per sbatch submission (full wrapper content)
CREATE TABLE wrapper_scripts (
    id              INTEGER PRIMARY KEY,
    execution_id    INTEGER,   -- links to pipeline_executions.execution_id
    task_name       TEXT,
    job_id          TEXT,
    submission_time TEXT,
    wrapper_path    TEXT,
    full_content    TEXT,
    slurm_cmd       TEXT,
    basic_paths     TEXT,
    global_python   TEXT,
    env_modules     TEXT,
    global_env_vars TEXT,
    task_params     TEXT,
    execute_cmd     TEXT
);
```

### JSONL vs SQLite

| | JSONL | SQLite |
|--|-------|--------|
| Written by | compute nodes + submit host, in real time | populated from JSONL after jobs complete |
| Survives cluster crash? | Yes (fsync'd immediately) | Only if merge has run |
| Queryable with SQL? | No | Yes |
| Source of truth | Yes | Derived — re-buildable via `neuromaestro force-rebuild` |

### Signal handling

The wrapper registers signal traps for `SIGTERM`, `SIGINT`, and `SIGHUP`. If SLURM kills a job (timeout, `scancel`, node failure), the trap fires and logs a `CANCELLED` status before exit:

```bash
# In wrapper_functions.sh
trap 'cleanup_on_signal SIGTERM 143' SIGTERM
trap 'cleanup_on_signal SIGINT 130'  SIGINT
trap 'cleanup_on_signal SIGHUP 129'  SIGHUP
```

`cleanup_on_signal` calls `log_end` with status `CANCELLED` and the signal name as the error message. Cancelled jobs appear correctly in the database rather than remaining as dangling `RUNNING` records.

---

## Merge Logs: Implementation

`neuromaestro merge-logs` reads unprocessed JSONL files and populates the SQLite database.

### Three merge functions

`merge_json_to_db()` walks `database/json/` and dispatches by directory name:

**`_merge_pipeline(task_dir, conn)`**
Handles `_pipeline/execution_*.jsonl` files. Each file may contain two events: a `pipeline_start` record and a `pipeline_update` record appended later. The function reads all lines, keys them by `event` name, then inserts one row into `pipeline_executions` combining fields from both. Files are moved to `_pipeline/archived/` after processing.

**`_merge_jobs(task_dir, conn)`**
Handles per-subject JSONL files in task directories. A file is only processed when **both** a `start` event and an `end` event are present — files with only a `start` (job still running or crashed mid-execution) are left in place and retried on the next merge. When complete, it inserts a row into `job_status` and, if a `command_output` event is present, a row into `command_outputs`. Files are moved to `{task}/archived/` after processing.

**`_merge_wrappers(task_dir, conn)`**
Handles `_pipeline/wrapper_*.jsonl` files. Each file contains a single `wrapper_script` event. Inserts one row into `wrapper_scripts`. Files are moved to `_pipeline/archived/` after processing.

### `merge_once` vs `rebuild_db`

| | `merge_once` (via `neuromaestro merge-logs`) | `rebuild_db` (via `neuromaestro force-rebuild`) |
|--|------------------------------------------|----------------------------------------------|
| Scans | Active files only (`json/**/*.jsonl`) | Active + `archived/` subdirectories |
| Output | Updates existing `pipeline_jobs.db` | Creates a new `pipeline_jobs_rebuild_{ts}.db` |
| Moves files? | Yes → `archived/` after processing | No — files are never touched |
| Modifies original db? | Yes | Never |

Use `force-rebuild` when the database is corrupted, accidentally deleted, or missing records after a cluster failure. It scans every JSONL file ever written (including already-archived ones) and produces a fresh database.

```bash
# Normal post-run merge
neuromaestro merge-logs /data/work/my_study

# Full rebuild from all historical JSONL (original db untouched)
neuromaestro force-rebuild /data/work/my_study
```

---

## Auto-Backup

Every time `neuromaestro merge-logs` runs, if `pipeline_jobs.db` already exists, it is copied to:

```
{db_dir}/backup/pipeline_jobs.backup_{timestamp}.db
```

The last 10 backups are kept; older ones are deleted automatically.

To restore manually:

```bash
cp {db_dir}/backup/pipeline_jobs.backup_{ts}.db {db_dir}/pipeline_jobs.db
```

---

## Resume: Output Checking Flow

When `--resume` is passed, the pipeline loads `config/project_config/{project}_checks.yaml` and instantiates an `OutputChecker`. Before submitting each task's array job, the checker evaluates every subject:

```
For each subject in the full subject list:
  1. Resolve base_path template ({work_dir}, {prefix}, {subject}, {session})
  2. required_files: each pattern must match at least one file and meet min_size_kb
  3. count_check: glob matches must fall within expected_count ± tolerance
  4. All checks PASS → subject is COMPLETE → excluded from array job
  5. Any check FAILS → subject is PENDING → included in array job
```

The submitted `--array` range covers only pending subjects. Completed subjects are never resubmitted.

If no checks file entry exists for a task, a warning is printed and all subjects are submitted:

```
Warning: No checks defined for task 'flanker_preprocess' — submitting all subjects
```

For the checks config syntax and standalone `check-outputs` command, see [Resume: Skip Completed Subjects](../pipeline-reference/index.md#resume-skip-completed-subjects).
