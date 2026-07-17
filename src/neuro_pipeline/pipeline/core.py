import typer
import sys
import os
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass
from .utils.hpc_utils import wait_for_jobs
from .dag import DAGExecutor, TaskRegistry
from .utils.config_utils import (
    PrepChoice,
    MRIQCChoice,
    load_project_config,
    set_config_dir,
    get_config_dir,
    get_config,
)
from .utils.job_db import log_pipeline_execution, update_pipeline_execution
import shutil

app = typer.Typer(pretty_exceptions_enable=False)
config: dict = {}

from .utils.detect_subjects import parse_subjects_input as _parse_subjects


def _resolve_config_dir(config_dir: Optional[str]) -> str:
    resolved = config_dir or os.environ.get("NEUROPIPE_CONFIG_DIR")
    if not resolved:
        typer.echo(
            "Error: --config-dir is required, or set NEUROPIPE_CONFIG_DIR environment variable.",
            err=True,
        )
        raise typer.Exit(1)
    return resolved


def _offer_export_env_var(config_path: str) -> None:
    export_line = f'export NEUROPIPE_CONFIG_DIR="{config_path}"'
    typer.echo(
        f"\nTip: to skip --config-dir on every command, add this to your ~/.bashrc:\n"
        f"  {export_line}"
    )

@dataclass
class TaskOptions:
    # Preprocessing
    prep: Optional[PrepChoice] = typer.Option(None, help="Preprocessing steps")
    
    # intermed
    intermed: Optional[List[str]] = typer.Option(None, "--intermed", help="Intermed tasks (e.g. volume,bfc)")

    # Quality Control
    mriqc: Optional[MRIQCChoice] = typer.Option(None, help="MRIQC processing")

    # Session
    session: Optional[str] = typer.Option('01', help="Session ID")

    # BIDS pipelines: --bids-prep rest,dwi
    bids_prep: Optional[List[str]] = typer.Option(None, help="BIDS pipeline preprocessing")
    bids_post: Optional[List[str]] = typer.Option(None, help="BIDS pipeline postprocessing")

    # Staged pipelines: --staged-prep cards,kidvid
    staged_prep: Optional[List[str]] = typer.Option(None, help="Staged pipeline preprocessing")
    staged_post: Optional[List[str]] = typer.Option(None, help="Staged pipeline postprocessing")

def collect_and_expand_tasks(registry, options: TaskOptions):
    """Collect and expand tasks"""
    return parse_and_expand_tasks(registry, **options.__dict__)

def parse_and_expand_tasks(registry, **kwargs):
    """Parse options and expand to concrete task names"""
    for key in ('intermed', 'bids_prep', 'bids_post', 'staged_prep', 'staged_post'):
        if kwargs.get(key):
            kwargs[key] = _parse_comma_list(kwargs[key])

    return registry.expand_tasks(**kwargs)

def _parse_comma_list(values):
    """Flatten and split comma-separated CLI values into a clean list"""
    result = []
    for item in values:
        result.extend([v.strip() for v in item.split(',') if v.strip()])
    return result

@app.command()
def run(
    subjects: Optional[str] = typer.Option(..., help="Subject list or txt file path"),

    input_dir: str = typer.Option(..., "--input", help="Input directory"),
    output_dir: str = typer.Option(..., "--output", help="Output directory"),
    work_dir: str = typer.Option(..., "--work", help="Work directory"),

    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="Path to config directory (contains config.yaml, hpc_config.yaml, project_config/). Defaults to $NEUROPIPE_CONFIG_DIR."),

    project: str = typer.Option(..., help="Project name"),

    prep: Optional[PrepChoice] = typer.Option(None, help="Preprocessing steps"),

    intermed: Optional[List[str]] = typer.Option(None, "--intermed", help="Intermed tasks (e.g. volume,bfc)"),
    mriqc: Optional[MRIQCChoice] = typer.Option(None, help="MRIQC processing"),
    session: Optional[str] = typer.Option(..., help="Session or wave ID"),

    bids_prep: Optional[List[str]] = typer.Option(None, "--bids-prep", help="BIDS pipeline preprocessing (e.g. rest,dwi)"),
    bids_post: Optional[List[str]] = typer.Option(None, "--bids-post", help="BIDS pipeline postprocessing (e.g. rest,dwi)"),

    staged_prep: Optional[List[str]] = typer.Option(None, "--staged-prep", help="Staged pipeline preprocessing (e.g. cards,kidvid)"),
    staged_post: Optional[List[str]] = typer.Option(None, "--staged-post", help="Staged pipeline postprocessing (e.g. cards,kidvid)"),

    dry_run: bool = typer.Option(False, "--dry-run", help="Show execution plan"),
    resume: bool = typer.Option(False, "--resume", help="Skip subjects whose outputs already exist"),

    skip_preflight: bool = typer.Option(False, "--skip-preflight", help="Skip pre-flight config and filesystem checks"),
    skip_bids_validation: bool = typer.Option(False, "--skip-bids-validation", help="Skip BIDS format validation"),

    wait: bool = typer.Option(False, "--wait", help="Wait for jobs to complete"),
    polling_interval: int = typer.Option(60, "--polling-interval", help="Polling interval (seconds)")
):

    set_config_dir(_resolve_config_dir(config_dir))
    config = get_config()

    execution_id = None
    db_path = None
    command_line = " ".join(sys.argv)

    try:
        options = TaskOptions(
            prep=prep,
            intermed=intermed,
            mriqc=mriqc,
            session=session,
            bids_prep=bids_prep,
            bids_post=bids_post,
            staged_prep=staged_prep,
            staged_post=staged_post,
        )
                
        # Validate input
        if not Path(input_dir).exists():
            typer.echo(f"Error: Input directory not found: {input_dir}", err=True)
            raise typer.Exit(1)
        
        # Store original work_dir for database
        original_work_dir = work_dir
        
        # Adjust paths for project, input_path/project/
        if project:
            work_dir = os.path.join(work_dir, project)
            output_dir = os.path.join(output_dir, project)
        
        Path(work_dir).mkdir(parents=True, exist_ok=True)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # Load project config
        try:
            project_config = load_project_config(project)
            typer.echo(f"Loaded project: {project}")
        except FileNotFoundError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)
        
        # Extract global parameters (root-level config)
        prefix = project_config.get('prefix', '')
        envir_dir = project_config.get('envir_dir', {})
        container_dir = envir_dir.get('container_dir')
        if not container_dir:
            raise ValueError("container_dir not found in envir_dir config")

        if not prefix:
            typer.echo("Error: 'prefix' not found in project config", err=True)
            raise typer.Exit(1)

        # Pre-flight checks
        if not skip_preflight:
            from .utils.preflight import PreflightChecker, print_preflight_report
            checker = PreflightChecker(
                project_config=project_config,
                global_config=config,
            )
            preflight_result = checker.run_all()
            print_preflight_report(preflight_result)
            if not preflight_result.ok:
                raise typer.Exit(1)
    
        registry = TaskRegistry()

        # Expand tasks
        requested_tasks = collect_and_expand_tasks(registry, options)
        if not requested_tasks:
            typer.echo("Error: No tasks specified", err=True)
            raise typer.Exit(1)
        
        typer.echo(f"Tasks: {requested_tasks}")

        if not skip_bids_validation and not prep:
            if bids_prep or mriqc in (MRIQCChoice.individual, MRIQCChoice.all):
                from .utils.bids_validation import run_bids_validation
                run_bids_validation(input_dir, work_dir)

        dag_executor = DAGExecutor(config)

        # Setup context
        if not subjects:
            typer.echo("Error: subjects parameter is required", err=True)
            raise typer.Exit(1)

        # Parse subjects (from file or string)
        user_subjects = _parse_subjects(subjects)
        context = {'subjects': user_subjects}
        typer.echo(f"Subjects: {user_subjects}")

        # Setup environment
        option_env = {
            "session": options.session,
            "prefix": prefix,
            "project": project,
        }
        
        for key, value in envir_dir.items():
            option_env[f"envir_dir_{key}"] = value
        
        option_env = {k: v for k, v in option_env.items() if v is not None}

        # Setup database
        db_config = project_config.get('database', {})

        # Check if database config exists
        if not db_config or 'db_path' not in db_config:
            typer.echo("Error: 'database.db_path' not found in project config", err=True)
            raise typer.Exit(1)

        db_path = db_config['db_path'].replace('$WORK_DIR', original_work_dir)
        if '$WORK_DIR' in db_path:
            typer.echo("Error: 'database.db_path' contains unresolved '$WORK_DIR' — check your project config", err=True)
            raise typer.Exit(1)

        # Create db directory
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        # Log execution start
        execution_id = log_pipeline_execution(
            command_line=command_line,
            project_name=project,
            session=options.session,
            input_dir=input_dir,
            output_dir=output_dir,
            work_dir=work_dir,
            subjects=context.get('subjects', []),
            requested_tasks=requested_tasks,
            dry_run=dry_run,
            db_path=db_path
        )
        typer.echo(f"Execution ID: {execution_id}")

        # Resume: locate per-project checks config
        checks_config_path = None
        if resume:
            from .utils.output_checker import load_checks_config
            try:
                checks_config_path = load_checks_config(project)
                typer.echo(f"[resume] Loaded output checks: {checks_config_path}")
            except FileNotFoundError as e:
                typer.echo(f"Warning: {e}", err=True)
                typer.echo("Warning: --resume requested but no checks config found. "
                           "Proceeding without skipping.", err=True)

        # Execute DAG
        all_job_ids, context = dag_executor.execute(
            requested_tasks=requested_tasks,
            input_dir=input_dir,
            output_dir=output_dir,
            work_dir=work_dir,
            container_dir=container_dir,
            dry_run=dry_run,
            context=context,
            option_env=option_env,
            project_config=project_config,
            original_work_dir=original_work_dir,
            db_path=db_path,
            resume=resume,
            checks_config_path=checks_config_path,
            execution_id=execution_id,
        )
        # Display summary
        typer.echo(f"\n=== Summary ===")
        total_jobs = sum(len(job_list) for job_list in all_job_ids.values())
        typer.echo(f"Tasks executed: {len(all_job_ids)}")
        typer.echo(f"Jobs submitted: {total_jobs}")
        
        if not dry_run:
            for task_name, job_ids in all_job_ids.items():
                if job_ids:
                    typer.echo(f"  {task_name}: {', '.join(job_ids)}")
        
        # Wait for jobs if requested
        if wait and not dry_run:
            all_jobs = []
            for job_list in all_job_ids.values():
                all_jobs.extend(job_list)
            
            if all_jobs:
                typer.echo(f"\n=== Waiting for jobs ===")
                wait_for_jobs(all_jobs, polling_interval)
            else:
                typer.echo("No jobs to wait for")
        
        # Update execution status
        if execution_id:
            update_pipeline_execution(
                execution_id=execution_id,
                status="COMPLETED",
                total_jobs=total_jobs,
                db_path=db_path
            )
            
        if not dry_run and all_job_ids:
            typer.echo("\n" + "="*60)
            typer.echo(f"\nJSON logs location:")
            typer.echo(f"  {os.path.dirname(db_path)}/json/")
            typer.echo(f"\nTo check job status, run:")
            typer.echo(f"  python -m neuro_pipeline.pipeline.utils.job_db query_jobs --db-path {db_path}")
            typer.echo(f"\nOr check recent jobs:")
            typer.echo(f"  python -m neuro_pipeline.pipeline.utils.job_db query_jobs --limit 20 --db-path {db_path}")
            typer.echo(f"\nTo manually merge logs (optional):")
            typer.echo(f"  neuropipe merge-logs {original_work_dir or work_dir}")

        typer.echo("\n=== Completed ===")
    
    # Record error
    except Exception as e:
        # Update execution status on failure
        if execution_id:
            update_pipeline_execution(
                execution_id=execution_id,
                status="FAILED",
                error_msg=str(e),
                db_path=db_path
            )
        raise e

@app.command("list-tasks")
def list_tasks(
    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="Path to config directory. Defaults to $NEUROPIPE_CONFIG_DIR."),
):
    """List available tasks"""
    set_config_dir(_resolve_config_dir(config_dir))
    from .utils.config_utils import config
    typer.echo("Available tasks:")
    for section_name, section_tasks in config.items():
        if not isinstance(section_tasks, list):
            continue
        typer.echo(f"\n{section_name.upper()}:")
        for task in section_tasks:
            if not isinstance(task, dict):
                continue
            name = task.get('name', 'Unknown')
            scripts = task.get('scripts', [])
            deps = task.get('input_from', 'None')

            typer.echo(f"  - {name}")
            typer.echo(f"    Scripts: {', '.join(scripts)}")
            typer.echo(f"    Dependencies: {deps}")

@app.command()
def detect_subjects(
    input_dir: str = typer.Argument(..., help="Input directory to scan"),
    output_file: Optional[str] = typer.Option(None, "--output", "-o", help="Output file (optional, prints to stdout if not specified)"),
    prefix: str = typer.Option("sub-", "--prefix", "-p", help="Subject prefix")
):
    """
    Detect subjects in input directory and optionally save to file.
    
    Examples:
      neuro-pipeline detect-subjects /data/BIDS
      neuro-pipeline detect-subjects /data/BIDS --output subjects.txt
      neuro-pipeline detect-subjects /data/BIDS --prefix "sub-" --output subjects.txt
    """
    from .utils.detect_subjects import detect_subjects as sd, save_subjects_to_file

    if not Path(input_dir).exists():
        typer.echo(f"Error: Directory not found: {input_dir}", err=True)
        raise typer.Exit(1)

    subjects = sd(input_dir, prefix)

    if not subjects:
        typer.echo(f"No subjects found with prefix: {prefix}")
        raise typer.Exit(0)

    if output_file:
        save_subjects_to_file(subjects, output_file)
        typer.echo(f"Detected {len(subjects)} subjects")
        typer.echo(f"Saved to: {output_file}")
        typer.echo(f"Subjects: {', '.join(subjects[:5])}{'...' if len(subjects) > 5 else ''}")
    else:
        typer.echo(f"Detected {len(subjects)} subjects:")
        typer.echo(",".join(subjects))

@app.command("merge-logs")
def merge_logs_cmd(
    work_dir: str = typer.Argument(..., help="Work directory"),
    db_path: Optional[str] = typer.Option(None, help="Database path (auto-detect if not provided)")
):
    """Merge JSON logs to database manually"""
    from .utils.merge_logs_create_db import merge_once
    merge_once(work_dir, db_path)


@app.command("force-rebuild")
def force_rebuild_cmd(
    work_dir: str = typer.Argument(..., help="Work directory"),
    db_path: Optional[str] = typer.Option(None, help="Original database path (auto-detect if not provided)"),
):
    """Rebuild a fresh database from all JSONL logs, including archived files.

    Creates pipeline_jobs_rebuild_{timestamp}.db next to the original database.
    The original database is never modified.

    Example:
      neuropipe force-rebuild /data/work/my_study
    """
    from .utils.merge_logs_create_db import rebuild_db
    try:
        new_db_path, count = rebuild_db(work_dir, db_path)
        typer.echo(f"Rebuilt {count} record(s) from all JSONL logs (including archived).")
        typer.echo(f"New database: {new_db_path}")
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command("generate-report")
def generate_report_cmd(
    db_path: str = typer.Option(..., "--db-path", help="Path to pipeline_jobs.db"),
    project: str = typer.Option(..., "--project", help="Project name"),
    output: Optional[str] = typer.Option(
        None, "--output", "-o",
        help="Output HTML file, or a directory (a pipeline_report_<project>_<timestamp>.html name is added inside it). Defaults to that name next to the database."
    ),
    session: Optional[str] = typer.Option(
        None, "--session",
        help="Filter by session ID (recommended when multiple projects share a database)."
    ),
    check_results: str = typer.Option(..., "--check-results",
        help="Path to a check_results_*.csv produced by check-outputs."
    ),
):
    """
    Generate a standalone HTML pipeline report for a project.
    Example:
      neuropipe generate-report --db-path /scratch/log/database/pipeline_jobs.db \\
          --project GCDS --session 01 --check-results /data/work/check_results_20260421.csv
    """
    from .utils.report_generator import generate_report
    try:
        out = generate_report(
            db_path=db_path,
            project_name=project,
            check_results_path=check_results,
            output_path=output,
            session=session,
        )
        typer.echo(f"Report: {out}")
    except (FileNotFoundError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command("check-outputs")
def check_outputs_cmd(
    project: str = typer.Option(..., help="Project name"),
    work_dir: str = typer.Option(..., "--work", help="Work/output directory"),
    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="Path to config directory. Defaults to $NEUROPIPE_CONFIG_DIR."),
    subjects: Optional[str] = typer.Option(None, help="Subject list or file path (auto-detected from work_dir if omitted)"),
    session: Optional[str] = typer.Option(None, help="Session ID(s), comma-separated (e.g. 01,02). Checks all sessions if omitted."),
    tasks: Optional[List[str]] = typer.Option(None, "--task",
        help="Task(s) to check (repeatable). Defaults to all configured tasks."),
    checks_dir: Optional[str] = typer.Option(None,
        help="Override directory for *_checks.yaml files"),
):
    """
    Check whether task outputs exist for each subject.

    Prints a summary of problematic subjects to the terminal and saves
    a full CSV report to <work_dir>/check_results_<timestamp>.csv.

    Without --subjects or --session, scans all subjects in work_dir across
    all sessions and saves a single CSV.

    Examples:
      neuropipe check-outputs --project test --work /data/processed
      neuropipe check-outputs --project test --work /data/processed \\
          --subjects 001,002 --session 01
    """
    set_config_dir(_resolve_config_dir(config_dir))

    from .utils.output_checker import OutputChecker, load_checks_config
    from .utils.detect_subjects import detect_subjects

    try:
        checks_config_path = load_checks_config(project, checks_dir)
        typer.echo(f"Loaded checks config: {checks_config_path}")
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    try:
        project_config = load_project_config(project)
        prefix = project_config.get('prefix', 'sub-')
    except FileNotFoundError:
        prefix = 'sub-'

    if subjects:
        subject_list = _parse_subjects(subjects)
        if not subject_list:
            typer.echo("Error: no subjects provided", err=True)
            raise typer.Exit(1)
    else:
        scan_dir = os.path.join(work_dir, "BIDS") if os.path.isdir(os.path.join(work_dir, "BIDS")) else work_dir
        subject_list = detect_subjects(scan_dir, prefix)
        if not subject_list:
            typer.echo(f"Error: no subjects found in {scan_dir}", err=True)
            raise typer.Exit(1)
        typer.echo(f"Auto-detected {len(subject_list)} subjects from {scan_dir}")

    if session:
        sessions = [s.strip() for s in session.split(',') if s.strip()]
        typer.echo(f"Sessions: {', '.join(sessions)}")
    else:
        sessions = ["*"]
        typer.echo("No --session specified: checking all sessions")

    # Load config and resolve task list using the first session
    ref_checker = OutputChecker(
        config_path=checks_config_path,
        work_dir=work_dir,
        prefix=prefix,
        session=sessions[0],
    )

    all_configured_tasks = list(ref_checker._config.keys())
    task_names = tasks if tasks else all_configured_tasks

    ref_checker.warn_missing_configs(task_names)
    task_names = [t for t in task_names if t in ref_checker._config]

    if not task_names:
        typer.echo("No tasks to check (none have output check configs).")
        raise typer.Exit(0)

    typer.echo(f"Checking {len(task_names)} task(s) × {len(subject_list)} subject(s) × {len(sessions)} session(s)...")

    import pandas as pd
    all_dfs = []
    for sess in sessions:
        checker = OutputChecker(
            config_path=checks_config_path,
            work_dir=work_dir,
            prefix=prefix,
            session=sess,
        )
        all_dfs.append(checker.check_all(task_names, subject_list))

    df = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame(
        columns=["task", "subject", "session", "check_type", "pattern", "expected", "actual", "status"]
    )
    ref_checker.print_terminal_summary(df)

    csv_path = checker.save_csv(df, work_dir)
    typer.echo(f"Full report saved to: {csv_path}")


@app.command()
def init(
    output_dir: str = typer.Argument(..., help="Directory to initialise (e.g. /scratch/my_study)"),
):
    """Initialise a project directory with config and script templates.

    Copies global config templates (config.yaml, hpc_config.yaml, project_config/,
    results_check/) and bash script templates to output_dir.

    Example:
      neuropipe init /scratch/my_study
    """
    from .utils.init_utils import init_project_templates

    output = Path(output_dir)
    config_out = output / "config"

    copied = init_project_templates(config_out)
    for item in copied:
        typer.echo(f"  Copied {item}")

    scripts_out = output / "scripts"
    typer.echo(f"\nInitialised at: {output}")
    typer.echo(f"\nNext steps:")
    typer.echo(f"  1. Edit {config_out}/hpc_config.yaml  — scheduler & resource settings")
    typer.echo(f"  2. Edit {config_out}/project_config/  — project-specific config")
    typer.echo(f"  3. Edit {scripts_out}/                — adapt .sh scripts to your HPC")
    typer.echo(f"\nThen run:")
    typer.echo(f"  neuropipe run --config-dir {config_out} ...")

    _offer_export_env_var(str(config_out))


@app.command("generate-config")
def generate_config_cmd(
    project_name: str = typer.Argument(..., help="Project name (e.g., branch, study1)"),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", "-o",
        help="Output directory (default: <config-dir>/project_config/)"),
    config_dir: Optional[str] = typer.Option(None, "--config-dir",
        help="Path to config directory (sets default output location). Defaults to $NEUROPIPE_CONFIG_DIR."),
):
    """Generate a blank project config template.

    Example:
      neuropipe generate-config branch --config-dir /scratch/my_study/config
      neuropipe generate-config branch --output-dir /scratch/my_project/config/project_config
    """
    set_config_dir(_resolve_config_dir(config_dir))
    from .utils.generate_project_config import generate_project_config
    generate_project_config(project_name, output_dir)


@app.command("generate-checks")
def generate_checks_cmd(
    project_name: str = typer.Argument(..., help="Project name (e.g., branch, study1)"),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", "-o",
        help="Output directory (default: <config-dir>/results_check/)"),
    config_dir: Optional[str] = typer.Option(None, "--config-dir",
        help="Path to config directory (sets default output location). Defaults to $NEUROPIPE_CONFIG_DIR."),
):
    """Generate a blank results-check config template.

    Example:
      neuropipe generate-checks branch --config-dir /scratch/my_study/config
      neuropipe generate-checks branch --output-dir /scratch/my_project/config/results_check
    """
    set_config_dir(_resolve_config_dir(config_dir))
    from .utils.generate_results_check import generate_results_check
    generate_results_check(project_name, output_dir)