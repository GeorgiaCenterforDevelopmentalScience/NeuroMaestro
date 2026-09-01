#!/usr/bin/env python3

import sqlite3
from datetime import datetime
import os
import json
import time
from typing import Optional
from pathlib import Path
import typer

app = typer.Typer(help="Task database management tool")

def ensure_db_dir(db_path: str):
    """Ensure database directory exists"""
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

def ensure_table_exists(conn, table_name: str):
    """Create table if not exists"""
    c = conn.cursor()
    
    if table_name == "job_status":
        c.execute('''
            CREATE TABLE IF NOT EXISTS job_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                execution_id INTEGER,
                subject TEXT,
                task_name TEXT,
                session TEXT,
                start_time TEXT,
                end_time TEXT,
                status TEXT,
                exit_code INTEGER,
                error_msg TEXT,
                duration_hours REAL,
                log_path TEXT,
                job_id TEXT,
                node_name TEXT
            )
        ''')
    elif table_name == "pipeline_executions":
        c.execute('''
            CREATE TABLE IF NOT EXISTS pipeline_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                execution_id INTEGER,
                execution_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                command_line TEXT,
                project_name TEXT,
                session TEXT,
                input_dir TEXT,
                output_dir TEXT,
                work_dir TEXT,
                subjects TEXT,
                requested_tasks TEXT,
                dry_run BOOLEAN,
                total_jobs INTEGER,
                status TEXT DEFAULT 'RUNNING',
                error_msg TEXT
            )
        ''')
    elif table_name == "command_outputs":
        c.execute('''
            CREATE TABLE IF NOT EXISTS command_outputs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                execution_id INTEGER,
                subject TEXT,
                task_name TEXT,
                session TEXT,
                script_name TEXT,
                command TEXT,
                stdout TEXT,
                stderr TEXT,
                exit_code INTEGER,
                execution_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                log_file_path TEXT,
                job_id TEXT
            )
        ''')
    elif table_name == "wrapper_scripts":
        c.execute('''
            CREATE TABLE IF NOT EXISTS wrapper_scripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                execution_id INTEGER,
                task_name TEXT,
                job_id TEXT,
                submission_time TEXT,
                wrapper_path TEXT,
                full_content TEXT,
                slurm_cmd TEXT,
                basic_paths TEXT,
                global_python TEXT,
                env_modules TEXT,
                global_env_vars TEXT,
                task_params TEXT,
                execute_cmd TEXT
            )
        ''')

    conn.commit()

def ensure_indexes(conn):
    c = conn.cursor()
    c.execute("CREATE INDEX IF NOT EXISTS idx_job_status_lookup ON job_status (subject, task_name, session)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_job_status_execution ON job_status (execution_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_wrapper_execution ON wrapper_scripts (execution_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_command_outputs_lookup ON command_outputs (subject, task_name, session)")
    conn.commit()

def get_db_connection(db_path: str):
    """Get database connection and ensure tables exist"""
    ensure_db_dir(db_path)
    conn = sqlite3.connect(db_path)

    for table in ["job_status", "pipeline_executions", "command_outputs", "wrapper_scripts"]:
        ensure_table_exists(conn, table)
    ensure_indexes(conn)

    return conn

@app.command("init_db")
def init_db(db_path: str = "pipeline_jobs.db"):
    """Initialize database"""
    conn = get_db_connection(db_path)
    conn.close()
    typer.echo(f"Database initialized: {db_path}")


def log_wrapper_script(
    task_name: str,
    job_id: str,
    wrapper_path: str,
    sections: dict,
    execution_id: Optional[int] = None,
    db_path: str = "pipeline_jobs.db",
):
    """
    Write wrapper script content to JSONL (crash-safe).
    Sections are passed directly from create_wrapper_script() — no file parsing needed.
    The JSONL will be merged into SQLite by the user running `neuromaestro merge-logs`.
    """
    try:
        db_dir = os.path.dirname(db_path)
        json_dir = os.path.join(db_dir, "json", "_pipeline")
        os.makedirs(json_dir, exist_ok=True)
        json_file = os.path.join(json_dir, f"wrapper_{task_name}_{int(time.time())}.jsonl")
        record = {
            "event": "wrapper_script",
            "timestamp": datetime.now().isoformat(),
            "execution_id": execution_id,
            "task_name": task_name,
            "job_id": job_id,
            "wrapper_path": wrapper_path,
            **sections,
        }
        with open(json_file, "w") as f:
            f.write(json.dumps(record) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        typer.echo(f"Warning: could not write wrapper JSONL: {e}", err=True)

def _find_job_log(json_dir: str, job_id: Optional[str], subject: str,
                  session: Optional[str]) -> Optional[str]:
    """Locate the JSONL that log_job_start wrote for this job.

    Array tasks of one task_name all write into the same directory, so the
    file has to be identified by subject rather than by taking the most
    recently written one.
    """
    # Same expression log_job_start builds the filename from.
    candidates = sorted(Path(json_dir).glob(f"{job_id or 'unknown'}_*.jsonl"),
                        key=os.path.getmtime, reverse=True)
    for path in candidates:
        try:
            with open(path) as f:
                for line in f:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if record.get("event") != "start":
                        break
                    if (record.get("subject") == subject
                            and record.get("session") == session):
                        return str(path)
                    break
        except (OSError, ValueError):
            continue
    return None


@app.command("log_start")
@app.command("log_job_start")
def log_job_start(
    subject: str,
    task_name: str,
    session: Optional[str] = None,
    log_file_path: Optional[str] = None,
    job_id: Optional[str] = None,
    node_list: Optional[str] = None,
    execution_id: Optional[int] = None,
    db_path: str = "pipeline_jobs.db"
):
    """Log job start to JSON file"""
    try:
        # Setup JSON directory
        db_dir = os.path.dirname(db_path)
        json_dir = os.path.join(db_dir, "json", task_name)
        os.makedirs(json_dir, exist_ok=True)

        json_file = os.path.join(json_dir, f"{job_id or 'unknown'}_{int(time.time())}.jsonl")

        record = {
            "event": "start",
            "timestamp": datetime.now().isoformat(),
            "execution_id": execution_id,
            "subject": subject,
            "task_name": task_name,
            "session": session,
            "log_path": log_file_path,
            "job_id": job_id,
            "node_name": node_list
        }
        
        # Write to JSON
        with open(json_file, 'a') as f:
            f.write(json.dumps(record) + '\n')
            f.flush()
            os.fsync(f.fileno())
        
        typer.echo(f"Job started: {subject} - {task_name} (session: {session})")
    except Exception as e:
        typer.echo(f"Error logging job start: {e}", err=True)
        raise typer.Exit(1)

@app.command("log_end")
@app.command("log_job_end")
def log_job_end(
    subject: str,
    task_name: str,
    status: str,
    session: Optional[str] = None,
    error_msg: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    exit_code: Optional[int] = None,
    job_id: Optional[str] = None,
    db_path: str = "pipeline_jobs.db"
):
    """Log job end to JSON file"""
    # Resolved outside the try: typer.Exit subclasses RuntimeError, so raising
    # it inside would be swallowed by the handler below.
    json_dir = os.path.join(os.path.dirname(db_path), "json", task_name)
    json_file = _find_job_log(json_dir, job_id, subject, session)
    if json_file is None:
        typer.echo(
            f"Error: no start log for {subject}/{task_name} "
            f"(job {job_id or 'unknown'}) under {json_dir}. "
            "This job will be absent from the database.",
            err=True,
        )
        raise typer.Exit(1)

    try:
        # Calculate duration
        duration_hours = None
        if duration_seconds is not None:
            duration_hours = round(duration_seconds / 3600, 3)
        
        record = {
            "event": "end",
            "timestamp": datetime.now().isoformat(),
            "subject": subject,
            "task_name": task_name,
            "session": session,
            "status": status,
            "error_msg": error_msg,
            "duration_hours": duration_hours,
            "exit_code": exit_code
        }
        
        # Append to JSON
        with open(json_file, 'a') as f:
            f.write(json.dumps(record) + '\n')
            f.flush()
            os.fsync(f.fileno())
        
        duration_str = f" ({duration_hours:.3f}h)" if duration_hours else ""
        typer.echo(f"Job ended: {subject} - {task_name} ({status}){duration_str}")
    except Exception as e:
        typer.echo(f"Error logging job end: {e}", err=True)
        raise typer.Exit(1)

@app.command("log_pipeline_execution")
def log_pipeline_execution(
    command_line: str,
    project_name: str,
    input_dir: str,
    output_dir: str,
    work_dir: str,
    session: Optional[str] = None,
    subjects: Optional[str] = None,
    requested_tasks: Optional[str] = None,
    dry_run: bool = False,
    total_jobs: int = 0,
    db_path: str = "pipeline_jobs.db"
):
    """Log pipeline execution to JSON file"""
    try:
        # Setup JSON directory
        db_dir = os.path.dirname(db_path)
        json_dir = os.path.join(db_dir, "json", "_pipeline")
        os.makedirs(json_dir, exist_ok=True)
        
        execution_id = int(time.time() * 1000)
        json_file = os.path.join(json_dir, f"execution_{execution_id}.jsonl")
        
        # Convert lists to strings
        if isinstance(subjects, list):
            subjects_str = ','.join(subjects)
        elif isinstance(subjects, str):
            subjects_str = subjects
        else:
            subjects_str = None
        
        if isinstance(requested_tasks, list):
            tasks_str = ','.join(requested_tasks)
        elif isinstance(requested_tasks, str):
            tasks_str = requested_tasks
        else:
            tasks_str = None
        
        record = {
            "event": "pipeline_start",
            "execution_id": execution_id,
            "timestamp": datetime.now().isoformat(),
            "command_line": command_line,
            "project_name": project_name,
            "session": session,
            "input_dir": input_dir,
            "output_dir": output_dir,
            "work_dir": work_dir,
            "subjects": subjects_str,
            "requested_tasks": tasks_str,
            "dry_run": dry_run,
            "total_jobs": total_jobs,
            "status": "RUNNING"
        }
        
        # Write to JSON
        with open(json_file, 'a') as f:
            f.write(json.dumps(record) + '\n')
            f.flush()
            os.fsync(f.fileno())
        
        typer.echo(f"Pipeline execution logged, ID: {execution_id}")
        return execution_id
    except Exception as e:
        typer.echo(f"Error logging pipeline execution: {e}", err=True)
        return None

@app.command("update_pipeline_execution")
def update_pipeline_execution(
    execution_id: int,
    status: str = "COMPLETED",
    error_msg: Optional[str] = None,
    total_jobs: Optional[int] = None,
    db_path: str = "pipeline_jobs.db"
):
    """Update pipeline execution status to JSON file"""
    try:
        # Find the execution JSON file
        db_dir = os.path.dirname(db_path)
        json_dir = os.path.join(db_dir, "json", "_pipeline")
        json_file = os.path.join(json_dir, f"execution_{execution_id}.jsonl")
        
        if not os.path.exists(json_file):
            typer.echo(f"Warning: Execution file not found: {json_file}", err=True)
            return
        
        record = {
            "event": "pipeline_update",
            "execution_id": execution_id,
            "timestamp": datetime.now().isoformat(),
            "status": status,
            "error_msg": error_msg,
            "total_jobs": total_jobs
        }
        
        # Append update to JSON
        with open(json_file, 'a') as f:
            f.write(json.dumps(record) + '\n')
            f.flush()
            os.fsync(f.fileno())
        
        typer.echo(f"Pipeline execution updated: {execution_id} -> {status}")
    except Exception as e:
        typer.echo(f"Error updating pipeline execution: {e}", err=True)

@app.command("query_pipeline_executions")
def query_pipeline_executions(
    limit: int = 10,
    project_name: Optional[str] = None,
    session: Optional[str] = None,
    status: Optional[str] = None,
    db_path: str = "pipeline_jobs.db"
):
    """Query pipeline execution records from database"""
    conn = get_db_connection(db_path)
    c = conn.cursor()
    
    query = "SELECT * FROM pipeline_executions"
    params = []
    
    conditions = []
    if project_name:
        conditions.append("project_name=?")
        params.append(project_name)
    if session:
        conditions.append("session=?")
        params.append(session)
    if status:
        conditions.append("status=?")
        params.append(status)
    
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    
    query += " ORDER BY execution_time DESC LIMIT ?"
    params.append(limit)
    
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        typer.echo("No matching records found")
        return rows
    
    for row in rows:
        # col order: id, execution_id, execution_time, command_line, project_name,
        #            session, input_dir, output_dir, work_dir, subjects,
        #            requested_tasks, dry_run, total_jobs, status, error_msg
        typer.echo(f"Execution ID: {row[1]}")
        typer.echo(f"Project: {row[4]}")
        typer.echo(f"Session: {row[5] or 'N/A'}")
        typer.echo(f"Status: {row[13]}")
        typer.echo(f"Execution time: {row[2]}")
        typer.echo(f"Subjects: {row[9] or 'N/A'}")
        typer.echo(f"Tasks: {row[10] or 'N/A'}")
        typer.echo(f"Total jobs: {row[12]}")
        if row[14]:
            typer.echo(f"Error: {row[14]}")
        typer.echo("-" * 40)
    
    return rows

@app.command("log_command_output")
def log_command_output(
    subject: str,
    task_name: str,
    script_name: str,
    command: str,
    session: Optional[str] = None,
    stdout: Optional[str] = None,
    stderr: Optional[str] = None,
    exit_code: Optional[int] = None,
    log_file_path: Optional[str] = None,
    job_id: Optional[str] = None,
    execution_id: Optional[int] = None,
    db_path: str = "pipeline_jobs.db"
):
    """Log command output to JSON file"""
    json_dir = os.path.join(os.path.dirname(db_path), "json", task_name)
    json_file = _find_job_log(json_dir, job_id, subject, session)
    if json_file is None:
        typer.echo(
            f"Error: no start log for {subject}/{task_name} "
            f"(job {job_id or 'unknown'}) under {json_dir}",
            err=True,
        )
        raise typer.Exit(1)

    try:
        # Truncate stdout and stderr to last 50 lines
        if stdout:
            lines = stdout.split('\n')
            if len(lines) > 50:
                stdout = '\n'.join(lines[-50:])
        
        if stderr:
            lines = stderr.split('\n')
            if len(lines) > 50:
                stderr = '\n'.join(lines[-50:])
        
        record = {
            "event": "command_output",
            "timestamp": datetime.now().isoformat(),
            "execution_id": execution_id,
            "subject": subject,
            "task_name": task_name,
            "session": session,
            "script_name": script_name,
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "log_file_path": log_file_path,
            "job_id": job_id
        }
        
        # Append to JSON
        with open(json_file, 'a') as f:
            f.write(json.dumps(record) + '\n')
            f.flush()
            os.fsync(f.fileno())
        
        typer.echo(f"Command output logged: {subject} - {task_name}")
    except Exception as e:
        typer.echo(f"Error logging command output: {e}", err=True)

@app.command("query_jobs")
def query_jobs(
    limit: int = 20,
    subject: Optional[str] = None,
    task_name: Optional[str] = None,
    session: Optional[str] = None,
    status: Optional[str] = None,
    db_path: str = "pipeline_jobs.db"
):
    """Query job status records from database"""
    conn = get_db_connection(db_path)
    c = conn.cursor()
    
    query = "SELECT * FROM job_status"
    params = []
    
    conditions = []
    if subject:
        conditions.append("subject=?")
        params.append(subject)
    if task_name:
        conditions.append("task_name=?")
        params.append(task_name)
    if session:
        conditions.append("session=?")
        params.append(session)
    if status:
        conditions.append("status=?")
        params.append(status)
    
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    
    query += " ORDER BY start_time DESC LIMIT ?"
    params.append(limit)
    
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        typer.echo("No matching records found")
        return rows
    
    for row in rows:
        # col order: id, execution_id, subject, task_name, session, start_time,
        #            end_time, status, exit_code, error_msg, duration_hours,
        #            log_path, job_id, node_name
        typer.echo(f"Subject: {row[2]} | Task: {row[3]} | Session: {row[4] or 'N/A'}")
        typer.echo(f"Status: {row[7]} | Exit code: {row[8]}")
        typer.echo(f"Start: {row[5]}")
        typer.echo(f"End: {row[6] or 'Running'}")
        if row[10]:
            typer.echo(f"Duration: {row[10]:.3f}h")
        if row[9]:
            typer.echo(f"Error: {row[9]}")
        typer.echo(f"Log: {row[11]}")
        typer.echo(f"Job ID: {row[12]} | Node: {row[13]}")
        typer.echo("-" * 60)
    
    return rows

@app.command("read_log")
def read_log(
    log_file_path: str = typer.Argument(..., help="Log file path"),
    max_lines: int = typer.Option(100, "--max-lines", "-n", help="Maximum lines to read"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log in real-time")
):
    """Read log file content"""
    if not os.path.exists(log_file_path):
        typer.echo(f"Log file not found: {log_file_path}", err=True)
        raise typer.Exit(1)
    
    try:
        if follow:
            typer.echo(f"Following log file: {log_file_path}")
            typer.echo("Press Ctrl+C to exit")
            typer.echo("-" * 60)
            
            import subprocess
            subprocess.run(['tail', '-f', log_file_path])
        else:
            with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                total_lines = len(lines)
                
                if total_lines > max_lines:
                    lines = lines[-max_lines:]
                    typer.echo(f"Showing last {max_lines} lines (total {total_lines} lines):")
                else:
                    typer.echo(f"Showing all {total_lines} lines:")
                
                typer.echo("-" * 60)
                
                for line in lines:
                    typer.echo(line.rstrip())
                
    except KeyboardInterrupt:
        typer.echo("\n\nStopped following log")
    except Exception as e:
        typer.echo(f"Failed to read log file: {e}", err=True)
        raise typer.Exit(1)

if __name__ == "__main__":
    app()