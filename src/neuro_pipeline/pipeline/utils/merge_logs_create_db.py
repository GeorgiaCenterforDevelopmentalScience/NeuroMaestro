import json
import shutil
import os
from datetime import datetime
from pathlib import Path
from typing import Dict
import typer

app = typer.Typer()

def merge_json_to_db(json_base_dir: str, db_path: str, job_ids: list = None):
    """Merge JSON logs to database
    
    Args:
        json_base_dir: Base directory containing JSON logs
        db_path: Database file path
        job_ids: Optional list of job IDs to filter (only merge logs for these jobs)
    
    Returns:
        int: Number of files merged
    """
    from .job_db import get_db_connection
    
    conn = get_db_connection(db_path)
    merged_count = 0
    incomplete: Dict[str, int] = {}

    for task_dir in Path(json_base_dir).glob("*"):
        if not task_dir.is_dir():
            continue

        if task_dir.name == "_pipeline":
            merged_count += _merge_pipeline(task_dir, conn, job_ids, archive=True)
            merged_count += _merge_wrappers(task_dir, conn, archive=True)
        else:
            merged_count += _merge_jobs(task_dir, conn, job_ids, archive=True)
            n = _count_incomplete(task_dir)
            if n:
                incomplete[task_dir.name] = n

    conn.close()
    _report_incomplete(incomplete)
    return merged_count


def _archive(json_file, task_dir) -> None:
    """Move a merged log aside. Failing here leaves it to be merged twice."""
    try:
        archived = task_dir / "archived"
        archived.mkdir(exist_ok=True)
        shutil.move(str(json_file), str(archived / json_file.name))
    except Exception as e:
        print(
            f"Merged but could not archive {json_file}: {e}\n"
            "  Running merge-logs again would insert these rows a second time. "
            "Use force-rebuild to rebuild the database from the logs instead."
        )


def _count_incomplete(task_dir) -> int:
    """Count logs with a start event but no end event.

    These are jobs the wrapper could not finish logging: SIGKILL, an OOM kill,
    or a dead node. They are never merged, so they are invisible in the
    database unless they are counted here.
    """
    count = 0
    for json_file in task_dir.glob("*.jsonl"):
        try:
            events = set()
            with open(json_file) as f:
                for line in f:
                    if line.strip():
                        events.add(json.loads(line).get("event"))
            if "start" in events and "end" not in events:
                count += 1
        except Exception:
            continue
    return count


def _report_incomplete(incomplete: Dict[str, int]) -> None:
    if not incomplete:
        return
    total = sum(incomplete.values())
    detail = ", ".join(f"{task} ({n})" for task, n in sorted(incomplete.items()))
    print(
        f"Skipped {total} incomplete log(s) with no end event: {detail}\n"
        "  These jobs were killed before the wrapper could finish logging "
        "(SIGKILL, out-of-memory, or node failure) and are absent from the "
        "database. Use check-outputs to see whether their outputs are complete."
    )

def _merge_pipeline(task_dir, conn, job_ids=None, archive=True):
    """Merge pipeline executions.

    Args:
        task_dir: Pipeline task directory (_pipeline/ or _pipeline/archived/)
        conn: Database connection
        job_ids: Optional job IDs filter (not used for pipeline logs)
        archive: Move processed files to archived/ when True (default)

    Returns:
        int: Number of pipeline logs merged
    """
    count = 0
    # Named by log_pipeline_execution. _pipeline/ also holds the much larger
    # wrapper_*.jsonl files, which _merge_wrappers handles.
    for json_file in task_dir.glob("execution_*.jsonl"):
        try:
            records = {}
            with open(json_file) as f:
                for line in f:
                    if line.strip():
                        r = json.loads(line)
                        records[r.get("event")] = r

            if "pipeline_start" in records:
                r = records["pipeline_start"]
                u = records.get("pipeline_update", {})

                conn.execute('''
                    INSERT INTO pipeline_executions
                    (execution_id, execution_time, command_line, project_name, session,
                     input_dir, output_dir, work_dir, subjects, requested_tasks, dry_run,
                     total_jobs, status, error_msg)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (r.get("execution_id"), r.get("timestamp"), r.get("command_line"),
                      r.get("project_name"), r.get("session"), r.get("input_dir"),
                      r.get("output_dir"), r.get("work_dir"), r.get("subjects"),
                      r.get("requested_tasks"), r.get("dry_run"),
                      u.get("total_jobs", r.get("total_jobs")),
                      u.get("status", r.get("status")), u.get("error_msg")))
                conn.commit()

                if archive:
                    _archive(json_file, task_dir)
                count += 1
        except Exception as e:
            conn.rollback()
            print(f"Error: {json_file}: {e}")
    return count


def _merge_jobs(task_dir, conn, job_ids=None, archive=True):
    """Merge job status logs.

    Args:
        task_dir: Task directory containing JSONL files
        conn: Database connection
        job_ids: Optional list of job IDs to filter (supports base job_id for array jobs)
        archive: Move processed files to archived/ when True (default)

    Returns:
        int: Number of job logs merged
    """
    count = 0
    for json_file in task_dir.glob("*.jsonl"):
        try:
            records = {}
            with open(json_file) as f:
                for line in f:
                    if line.strip():
                        r = json.loads(line)
                        records[r.get("event")] = r

            # Only merge complete logs
            if "start" not in records or "end" not in records:
                continue

            job_id = records["start"].get("job_id")

            # Filter by job_ids if provided
            if job_ids is not None:
                # Support both exact match and prefix match (for array jobs)
                # e.g., job_id='41693293_1' matches filter='41693293'
                matched = bool(job_id) and any(
                    job_id == fid or job_id.startswith(fid + '_')
                    for fid in job_ids
                )
                if not matched:
                    continue

            # Insert job start
            r = records["start"]
            cur = conn.execute('''
                INSERT INTO job_status
                (execution_id, subject, task_name, session, start_time, status, log_path, job_id, node_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (r.get("execution_id"), r.get("subject"), r.get("task_name"), r.get("session"),
                  r.get("timestamp"), "RUNNING", r.get("log_path"),
                  r.get("job_id"), r.get("node_name")))
            row_id = cur.lastrowid

            # Update job end. Targets the row just inserted; matching on
            # subject/task/session would also hit rows from earlier runs.
            r = records["end"]
            conn.execute('''
                UPDATE job_status
                SET end_time=?, status=?, error_msg=?, duration_hours=?, exit_code=?
                WHERE id=?
            ''', (r.get("timestamp"), r.get("status"), r.get("error_msg"),
                  r.get("duration_hours"), r.get("exit_code"), row_id))

            # Insert command output if available
            if "command_output" in records:
                r = records["command_output"]
                conn.execute('''
                    INSERT INTO command_outputs
                    (execution_id, subject, task_name, session, script_name, command, stdout, stderr,
                     exit_code, log_file_path, job_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (records["start"].get("execution_id"),
                      r.get("subject"), r.get("task_name"), r.get("session"),
                      r.get("script_name"), r.get("command"), r.get("stdout"),
                      r.get("stderr"), r.get("exit_code"), r.get("log_file_path"),
                      r.get("job_id")))

            conn.commit()

            if archive:
                _archive(json_file, task_dir)
            count += 1
        except Exception as e:
            conn.rollback()
            print(f"Error: {json_file}: {e}")
    return count


def _merge_wrappers(task_dir, conn, archive=True):
    """Merge wrapper_script events from _pipeline/ into the wrapper_scripts table.

    Wrapper JSONL files are named wrapper_<task>_<timestamp>.jsonl and contain
    a single 'wrapper_script' event written by job_db.log_wrapper_script().

    Args:
        task_dir: Directory to scan for wrapper_*.jsonl files
        conn: Database connection
        archive: Move processed files to archived/ when True (default)
    """
    count = 0
    for json_file in task_dir.glob("wrapper_*.jsonl"):
        try:
            with open(json_file) as f:
                line = f.readline()
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("event") != "wrapper_script":
                continue

            conn.execute(
                """
                INSERT INTO wrapper_scripts
                    (execution_id, task_name, job_id, submission_time, wrapper_path, full_content,
                     slurm_cmd, basic_paths, global_python, env_modules,
                     global_env_vars, task_params, execute_cmd)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r.get("execution_id"), r.get("task_name"), r.get("job_id"),
                    r.get("timestamp"), r.get("wrapper_path"), r.get("full_content"),
                    r.get("slurm_cmd"), r.get("basic_paths"),
                    r.get("global_python"), r.get("env_modules"),
                    r.get("global_env_vars"), r.get("task_params"),
                    r.get("execute_cmd"),
                ),
            )
            conn.commit()

            if archive:
                _archive(json_file, task_dir)
            count += 1
        except Exception as e:
            conn.rollback()
            print(f"Error merging wrapper log {json_file}: {e}")
    return count


def rebuild_db(work_dir: str, db_path: str = None) -> tuple:
    """Rebuild a fresh database from all JSONL logs, including archived files.

    Scans both log/json/*/*.jsonl and log/json/*/archived/*.jsonl.
    Creates a new database file next to the original with a timestamp suffix;
    the original database is never modified. Files are not moved or re-archived.

    Args:
        work_dir: Pipeline work directory
        db_path: Path to the original database (auto-detected if not provided)

    Returns:
        Tuple of (new_db_path, record_count)
    """
    from .job_db import get_db_connection

    if not db_path:
        db_path = os.path.join(work_dir, "database", "pipeline_jobs.db")

    db_dir = os.path.dirname(os.path.abspath(db_path))
    json_dir = os.path.join(db_dir, "json")

    if not os.path.exists(json_dir):
        raise FileNotFoundError(f"No JSON log directory found: {json_dir}")

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    new_db_path = os.path.join(db_dir, f"pipeline_jobs_rebuild_{ts}.db")

    conn = get_db_connection(new_db_path)
    count = 0

    for task_dir in Path(json_dir).glob("*"):
        if not task_dir.is_dir():
            continue

        # Scan active dir and archived/ subdir
        dirs_to_scan = [task_dir]
        archived_dir = task_dir / "archived"
        if archived_dir.is_dir():
            dirs_to_scan.append(archived_dir)

        if task_dir.name == "_pipeline":
            for scan_dir in dirs_to_scan:
                count += _merge_pipeline(scan_dir, conn, archive=False)
                count += _merge_wrappers(scan_dir, conn, archive=False)
        else:
            for scan_dir in dirs_to_scan:
                count += _merge_jobs(scan_dir, conn, archive=False)

    conn.close()
    return new_db_path, count


@app.command("merge")
def merge_once(work_dir: str, db_path: str = None):
    """Merge JSON logs to database"""
    if not db_path:
        db_path = os.path.join(work_dir, "database", "pipeline_jobs.db")

    json_dir = os.path.join(os.path.dirname(db_path), "json")
    if not os.path.exists(json_dir):
        typer.echo(f"No JSON logs: {json_dir}")
        return

    if Path(db_path).exists():
        from .db_backup import backup_database
        try:
            backup_path = backup_database(db_path, backup_dir=None)
            typer.echo(f"Database backed up to: {backup_path}")
        except Exception as e:
            typer.echo(f"Warning: Backup failed: {e}", err=True)

    count = merge_json_to_db(json_dir, db_path)
    typer.echo(f"Merged {count} files")


if __name__ == "__main__":
    app()