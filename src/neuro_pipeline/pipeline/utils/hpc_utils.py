import sys
import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import typer
import yaml

from .config_utils import get_config_dir

config: Optional[dict] = None
hpc_config: Optional[dict] = None


def _ensure_config() -> dict:
    global config
    if config is None:
        with open(get_config_dir() / "config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    return config


def _ensure_hpc_config() -> dict:
    global hpc_config
    if hpc_config is None:
        with open(get_config_dir() / "hpc_config.yaml", "r", encoding="utf-8") as f:
            hpc_config = yaml.safe_load(f)
    return hpc_config


class HPCBackend(ABC):
    """Abstract base class for HPC scheduler backends.
    
    Subclass this to add support for a new scheduler (PBS, LSF, etc.).
    Only three methods need to be implemented:
      - build_job_args   → scheduler-specific submission flags
      - submit_job       → submit and return job id
      - wait_for_jobs    → poll until all jobs finish
    """

    @abstractmethod
    def build_job_args(
        self,
        resources: "HPCResources",
        array_param: Optional[str],
        wait_jobs: Optional[List[str]],
        job_name: str,
        log_output: str,
        log_error: str,
    ) -> List[str]:
        """Build the scheduler-specific argument list for job submission."""

    @abstractmethod
    def submit_job(self, args: List[str], wrapper_script: Path) -> Optional[str]:
        """Submit a job and return the job id string, or None on failure."""

    @abstractmethod
    def wait_for_jobs(self, job_ids: List[str], polling_interval: int = 60) -> None:
        """Block until all given job ids have left the active state."""


class SLURMBackend(HPCBackend):
    """SLURM scheduler backend (sbatch / squeue / scancel)."""

    def __init__(self, scheduler_cfg: Dict[str, Any]):
        self._cfg = scheduler_cfg
        self._flags = scheduler_cfg.get("resource_flags", {})

    def _fmt(self, key: str, value: Any) -> str:
        """Format a resource flag using the template from hpc_config.yaml."""
        template = self._flags[key]
        return template.format(value=value)

    def build_job_args(
        self,
        resources: "HPCResources",
        array_param: Optional[str],
        wait_jobs: Optional[List[str]],
        job_name: str,
        log_output: str,
        log_error: str,
    ) -> List[str]:
        args = [
            self._fmt("partition",     resources.partition),
            self._fmt("nodes",         resources.nodes),
            self._fmt("ntasks",        resources.ntasks),
            self._fmt("cpus_per_task", resources.cpus_per_task),
            self._fmt("time",          resources.time),
            self._fmt("job_name",      job_name),
            self._fmt("output",        log_output),
            self._fmt("error",         log_error),
        ]

        if resources.memory_per_cpu:
            args.append(self._fmt("mem_per_cpu", resources.memory_per_cpu))
        else:
            args.append(self._fmt("mem", resources.memory))

        if resources.gres and "gres" in self._flags:
            args.append(self._fmt("gres", resources.gres))

        if array_param:
            array_flag = self._cfg["array_flag"].format(array=array_param)
            args.append(array_flag)

        if resources.additional_args:
            args.extend(resources.additional_args)

        if wait_jobs:
            dep_flag = self._cfg["dependency_flag"].format(jobs=":".join(wait_jobs))
            args.append(dep_flag)

        return args

    def submit_job(self, args: List[str], wrapper_script: Path) -> Optional[str]:
        submit_cmd = self._cfg["submit_cmd"]
        cmd = [submit_cmd] + args + [str(wrapper_script)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            # Parse job id according to hpc_config job_id_parse strategy
            parse = self._cfg.get("job_id_parse", "last_word")
            if parse == "last_word":
                job_id = result.stdout.strip().split()[-1]
            elif parse == "first_word":
                job_id = result.stdout.strip().split()[0]
            else:
                job_id = result.stdout.strip()
            typer.echo(f"Job submitted: {job_id}")
            return job_id
        except subprocess.CalledProcessError as e:
            typer.echo(f"Job submission failed: {e}", err=True)
            if e.stdout:
                typer.echo(f"STDOUT: {e.stdout}", err=True)
            if e.stderr:
                typer.echo(f"STDERR: {e.stderr}", err=True)
            return None

    def wait_for_jobs(self, job_ids: List[str], polling_interval: int = 60) -> None:
        if not job_ids:
            return

        typer.echo(f"Waiting for jobs: {', '.join(job_ids)}")
        status_cmd = self._cfg["status_cmd"]
        status_args = self._cfg.get("status_args", ["--noheader", "--format=%i %T"])
        active_states = set(self._cfg.get("active_states", ["PENDING", "RUNNING"]))

        while True:
            try:
                result = subprocess.run(
                    [status_cmd, "--job", ",".join(job_ids)] + status_args,
                    capture_output=True, text=True, check=True
                )

                if not result.stdout.strip():
                    typer.echo("All jobs completed")
                    break

                running_jobs = []
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            job_id, status = parts[0], parts[1]
                            if status in active_states:
                                running_jobs.append(f"{job_id}({status})")

                if running_jobs:
                    typer.echo(f"Waiting for: {', '.join(running_jobs)}")
                    time.sleep(polling_interval)
                else:
                    typer.echo("All jobs completed")
                    break

            except subprocess.CalledProcessError:
                typer.echo("All jobs completed (not found in queue)")
                break


class PBSBackend(HPCBackend):
    """PBS/Torque scheduler backend (qsub / qstat / qdel)."""

    def __init__(self, scheduler_cfg: Dict[str, Any]):
        self._cfg = scheduler_cfg
        self._flags = scheduler_cfg.get("resource_flags", {})

    def _fmt(self, key: str, value: Any) -> Optional[str]:
        template = self._flags.get(key, "")
        if not template:
            return None
        return template.format(value=value)

    def build_job_args(
        self,
        resources: "HPCResources",
        array_param: Optional[str],
        wait_jobs: Optional[List[str]],
        job_name: str,
        log_output: str,
        log_error: str,
    ) -> List[str]:
        candidates = [
            ("partition",     resources.partition),
            ("nodes",         resources.nodes),
            ("ntasks",        resources.ntasks),
            ("cpus_per_task", resources.cpus_per_task),
            ("time",          resources.time),
            ("job_name",      job_name),
            ("output",        log_output),
            ("error",         log_error),
        ]
        args = [f for k, v in candidates if (f := self._fmt(k, v)) is not None]

        mem_key = "mem_per_cpu" if resources.memory_per_cpu else "mem"
        mem_val = resources.memory_per_cpu or resources.memory
        mem_flag = self._fmt(mem_key, mem_val)
        if mem_flag:
            args.append(mem_flag)

        if resources.gres:
            gres_flag = self._fmt("gres", resources.gres)
            if gres_flag:
                args.append(gres_flag)

        if array_param:
            args.append(self._cfg["array_flag"].format(array=array_param))

        if resources.additional_args:
            args.extend(resources.additional_args)

        if wait_jobs:
            args.append(self._cfg["dependency_flag"].format(jobs=":".join(wait_jobs)))

        return args

    def submit_job(self, args: List[str], wrapper_script: Path) -> Optional[str]:
        submit_cmd = self._cfg["submit_cmd"]
        cmd = [submit_cmd] + args + [str(wrapper_script)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            parse = self._cfg.get("job_id_parse", "first_word")
            if parse == "last_word":
                job_id = result.stdout.strip().split()[-1]
            elif parse == "first_word":
                job_id = result.stdout.strip().split()[0]
            else:
                job_id = result.stdout.strip()
            typer.echo(f"Job submitted: {job_id}")
            return job_id
        except subprocess.CalledProcessError as e:
            typer.echo(f"Job submission failed: {e}", err=True)
            if e.stdout:
                typer.echo(f"STDOUT: {e.stdout}", err=True)
            if e.stderr:
                typer.echo(f"STDERR: {e.stderr}", err=True)
            return None

    def wait_for_jobs(self, job_ids: List[str], polling_interval: int = 60) -> None:
        if not job_ids:
            return

        typer.echo(f"Waiting for jobs: {', '.join(job_ids)}")
        status_cmd = self._cfg["status_cmd"]
        active_states = set(self._cfg.get("active_states", ["Q", "R", "H"]))

        while True:
            running_jobs = []
            for job_id in job_ids:
                try:
                    result = subprocess.run(
                        [status_cmd, job_id],
                        capture_output=True, text=True, check=True
                    )
                    for line in result.stdout.strip().splitlines():
                        parts = line.split()
                        if len(parts) >= 5 and parts[0].startswith(job_id.split(".")[0]):
                            state = parts[4]
                            if state in active_states:
                                running_jobs.append(f"{job_id}({state})")
                except subprocess.CalledProcessError:
                    pass  # job no longer in queue = completed

            if running_jobs:
                typer.echo(f"Waiting for: {', '.join(running_jobs)}")
                time.sleep(polling_interval)
            else:
                typer.echo("All jobs completed")
                break


def get_hpc_backend() -> HPCBackend:
    hpc_cfg = _ensure_hpc_config()
    scheduler = hpc_cfg.get("scheduler", "slurm").lower()
    scheduler_cfg = hpc_cfg.get(scheduler)

    if scheduler_cfg is None:
        raise ValueError(
            f"Scheduler '{scheduler}' selected in hpc_config.yaml "
            f"but has no config block defined."
        )

    if scheduler == "slurm":
        return SLURMBackend(scheduler_cfg)
    elif scheduler == "pbs":
        return PBSBackend(scheduler_cfg)
    else:
        raise NotImplementedError(
            f"Scheduler '{scheduler}' is not yet implemented. "
            f"See HPCBackend in hpc_utils.py to add support."
        )


@dataclass
class HPCResources:
    """HPC resource configuration for a job"""
    
    partition: str
    nodes: int
    ntasks: int
    cpus_per_task: int
    memory: str
    time: str
    memory_per_cpu: Optional[str] = None
    gres: Optional[str] = None
    array: Optional[str] = None
    additional_args: Optional[List[str]] = None
    
    def __post_init__(self):
        if self.additional_args is None:
            self.additional_args = []

def get_hpc_resources(task_config: Dict[str, Any]) -> HPCResources:
    """Get HPC resource configuration from task config and global settings"""
    
    hpc_cfg = _ensure_hpc_config()
    defaults = hpc_cfg.get('defaults', {})
    profile_name = task_config.get('profile', 'standard')
    profile_config = hpc_cfg.get('resource_profiles', {}).get(profile_name, {})

    if not profile_config:
        available = ', '.join(hpc_cfg.get('resource_profiles', {}).keys())
        raise ValueError(f"Profile '{profile_name}' not found. Available: {available}")
    
    merged_config = {**defaults, **profile_config}
    
    array_param = None
    if task_config.get('array', False):
        array_config = _ensure_config().get('array_config', {})
        array_param = array_config.get('pattern', '1-{num}%15')
    
    return HPCResources(
        partition=merged_config['partition'],
        nodes=merged_config['nodes'],
        ntasks=merged_config['ntasks'],
        cpus_per_task=merged_config['cpus_per_task'],
        memory=merged_config['memory'],
        memory_per_cpu=merged_config.get('memory_per_cpu'),
        gres=merged_config.get('gres'),
        time=merged_config['time'],
        array=array_param,
        additional_args=merged_config.get('additional_args', [])
    )

def get_environment_commands(task_config: Dict[str, Any], project_config: Dict[str, Any] = None) -> List[str]:
    """Get environment setup commands from task and project configuration"""
    env_commands = []
    environ_names = task_config.get('environ', [])
    
    if isinstance(environ_names, str):
        environ_names = [environ_names]
    elif not isinstance(environ_names, list):
        environ_names = []
    
    modules = {}
    if project_config and 'modules' in project_config:
        modules = project_config['modules']
    
    for env_name in environ_names:
        if env_name in modules:
            env_commands.extend(modules[env_name])
    
    return env_commands

def get_script_with_validation(script_name: str, scripts_dir: str) -> Optional[Path]:
    """Validate and return script path, with helpful error messages"""
    scripts_dir_path = Path(scripts_dir)
    script_path = scripts_dir_path / script_name

    if script_path.exists():
        return script_path

    if scripts_dir_path.exists():
        available = [f.name for f in scripts_dir_path.iterdir() if f.is_file()]
        typer.echo(f"[ERROR] Script '{script_name}' not found in {scripts_dir_path}. Available: {', '.join(sorted(available))}", err=True)
    else:
        typer.echo(f"[ERROR] Script '{script_name}' not found. Scripts directory {scripts_dir_path} does not exist.", err=True)

    return None


def submit_slurm_job(
    script_name: str,
    subjects: str,
    input_dir: str,
    output_dir: str,
    work_dir: str,
    container_dir: str,
    env_vars: Optional[Dict[str, str]] = None,
    wait_jobs: Optional[List[str]] = None,
    task_config: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    option_env: Optional[Dict[str, str]] = None,
    project_config: Optional[Dict[str, Any]] = None,
    requested_tasks: Optional[List[str]] = None,
    original_work_dir: Optional[str] = None,
    db_path: Optional[str] = None,
    execution_id: Optional[int] = None,
) -> Optional[str]:
    """Submit a SLURM job for the given script and subjects"""

    # Locate and validate script
    scripts_dir = project_config.get('scripts_dir', 'scripts/template') if project_config else 'scripts/template'
    script_path = get_script_with_validation(script_name, scripts_dir)
    
    if not script_path:
        raise FileNotFoundError(f"Script '{script_name}' not found in scripts_dir='{scripts_dir}'")

    if task_config:
        resources = get_hpc_resources(task_config)
        env_commands = get_environment_commands(task_config, project_config=project_config)
    else:
        default_task_config = {'profile': 'standard', 'array': False}
        resources = get_hpc_resources(default_task_config)
        env_commands = []

    actual_input_dir = input_dir
    if task_config and 'input_from' in task_config:
        input_from = task_config['input_from']
        if requested_tasks and input_from in requested_tasks:
            from .config_utils import find_task_config_by_name
            upstream_config = find_task_config_by_name(input_from)
            if upstream_config and 'output_pattern' in upstream_config:
                actual_input_dir = upstream_config['output_pattern'].format(base_output=output_dir)

    # Create directories
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Setup database path
    if not db_path:
        db_path = str(Path(work_dir) / "database" / "pipeline_jobs.db")

    # Handle output pattern
    if task_config and 'output_pattern' in task_config:
        output_pattern = task_config['output_pattern']
        actual_output_dir = output_pattern.format(base_output=output_dir)
    else:
        actual_output_dir = output_dir
    
    # os.path.isfile, not Path.is_file: subjects is usually a comma-joined list,
    # and past ~64 IDs it exceeds NAME_MAX, where Path.stat() propagates
    # ENAMETOOLONG on Python < 3.13. os.path.isfile returns False instead.
    if os.path.isfile(subjects):
        with open(subjects, 'r') as f:
            subjects_list = [line.strip() for line in f if line.strip()]
    else:
        subjects_list = [s.strip() for s in subjects.split(',') if s.strip()]

    if not subjects_list:
        typer.echo("Error: No subjects provided", err=True)
        return None

    is_array_job = task_config and 'array' in task_config and task_config['array']

    # Setup array parameter
    if is_array_job:
        array_param = resources.array
        if array_param and '{num}' in array_param:
            array_param = array_param.replace('{num}', str(len(subjects_list)))
    else:
        array_param = None

    # Get task name for log directory
    task_name = task_config.get('name', script_path.stem) if task_config else script_path.stem

    # Setup log paths - always use task-specific directory
    log_dir = Path(work_dir) / "log"
    task_log_dir = log_dir / task_name
    task_log_dir.mkdir(parents=True, exist_ok=True)

    # Create per-subject subdirectories inside task log dir for array jobs
    if is_array_job:
        for subject in subjects_list:
            (task_log_dir / f"sub-{subject}").mkdir(parents=True, exist_ok=True)
    
    if is_array_job:
        slurm_output = f"{task_log_dir}/{task_name}_%A-%a.out"
        slurm_error = f"{task_log_dir}/{task_name}_%A-%a.err"
    else:
        slurm_output = f"{task_log_dir}/{task_name}_%A.out"
        slurm_error = f"{task_log_dir}/{task_name}_%A.err"
        
    # Build scheduler arguments via the configured backend
    backend = get_hpc_backend()
    slurm_args = backend.build_job_args(
        resources=resources,
        array_param=array_param,
        wait_jobs=wait_jobs,
        job_name=script_path.stem,
        log_output=slurm_output,
        log_error=slurm_error,
    )

    # Create wrapper script
    wrapper_script, wrapper_sections = create_wrapper_script(
        script_path=script_path,
        subjects_list=subjects_list,
        input_dir=actual_input_dir,
        output_dir=actual_output_dir,
        work_dir=work_dir,
        container_dir=container_dir,
        env_vars=env_vars,
        use_array=bool(array_param),
        env_commands=env_commands,
        project_config=project_config,
        task_config=task_config,
        db_path=str(db_path),
        option_env=option_env,
        slurm_args=slurm_args,
        execution_id=execution_id,
    )

    # Dry run mode
    if dry_run:
        return f"dry_run_{script_path.stem}"

    # Submit via the configured backend
    job_id = backend.submit_job(slurm_args, wrapper_script)
    if job_id:
        try:
            from .job_db import log_wrapper_script
            log_wrapper_script(task_name, job_id, str(wrapper_script), wrapper_sections,
                               execution_id=execution_id, db_path=str(db_path))
        except Exception:
            pass  # never block submission over a logging failure
    return job_id


def create_wrapper_script(
    script_path: Path,
    subjects_list: List[str],
    input_dir: str,
    output_dir: str,
    work_dir: str,
    container_dir: str = "",
    env_vars: Optional[Dict[str, str]] = None,
    use_array: bool = True,
    env_commands: Optional[List[str]] = None,
    project_config: Optional[Dict[str, Any]] = None,
    task_config: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
    option_env: Optional[Dict[str, str]] = None,
    slurm_args: Optional[List[str]] = None,
    execution_id: Optional[int] = None,
) -> Tuple[Path, Dict[str, str]]:
    """Generate minimal wrapper script that calls bash template"""

    wrapper_dir = Path(work_dir) / "log" / "wrapper"
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    
    script_name = script_path.stem
    timestamp = int(time.time())
    wrapper_filename = f"{script_name}_{timestamp}_wrapper.sh"
    wrapper_path = wrapper_dir / wrapper_filename
    
    # Prepare environment commands
    env_commands_str = ""
    if env_commands:
        env_commands_str = "\n".join(env_commands)
    
    # Prepare global Python commands
    global_python_str = ""
    if project_config:
        global_python = project_config.get('global_python', [])
        if global_python:
            global_python_str = "\n".join(global_python)
    
    # Prepare global environment variables
    global_env_vars = {}
    envir_dir = project_config.get('envir_dir') if project_config else None
    if envir_dir:
        global_env_vars.update(envir_dir)
    
    if option_env:
        for key, value in option_env.items():
            if value is not None and not key.startswith('envir_dir_'):
                global_env_vars[key] = value
    
    global_env_str = ""
    if global_env_vars:
        global_env_str = "\n".join([f'export {k.upper()}="{v}"' for k, v in global_env_vars.items()])
    
    # Prepare task parameters
    task_params_str = ""
    if task_config:
        excluded_keys = {'name', 'environ', 'input_from', 'scripts', 'profile', 'array', 'output_pattern'}
        task_params = []
        for key, value in task_config.items():
            if key in excluded_keys:
                continue
            if isinstance(value, (str, int, float)):
                task_params.append(f'export {key.upper()}="{value}"')
            elif isinstance(value, list):
                task_params.append(f'export {key.upper()}="{" ".join(map(str, value))}"')
            else:
                typer.echo(f"[WARN] Task parameter '{key}' has unsupported type {type(value).__name__} (nested dict/object); skipped. Config values must be scalars or flat lists.", err=True)
        task_params_str = "\n".join(task_params)
    
    # Get task name
    task_name = task_config.get('name', script_name) if task_config else script_name
    
    # Setup database path
    if not db_path:
        db_path = str(Path(work_dir) / "database" / "pipeline_jobs.db")

    # pipeline/ dir: used by bash wrapper to locate utils/wrapper_functions.sh
    pipeline_root = Path(__file__).parent.parent
    
    # Write minimal wrapper script
    with open(wrapper_path, 'w') as f:
        f.write("#!/bin/bash\n\n")
        f.write("# Auto-generated wrapper script\n")
        f.write(f"# Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# Original script: {script_path.resolve()}\n")
        f.write(f"# Subjects: {', '.join(subjects_list[:5])}{'...' if len(subjects_list) > 5 else ''}\n")
        f.write(f"# Number of subjects: {len(subjects_list)}\n")
        f.write(f"# Array job: {'Yes' if use_array else 'No'}\n")
        
        # Submission command reference (for debugging)
        if slurm_args:
            _hc = _ensure_hpc_config()
            submit_cmd = _hc.get(_hc.get("scheduler", "slurm"), {}).get("submit_cmd", "sbatch")
            f.write("#\n")
            f.write("# Submission Command:\n")
            f.write(f"# {submit_cmd} {' '.join(slurm_args)} {wrapper_path}\n")
        
        f.write("\n")

        # Export all configuration as environment variables
        f.write("# Basic paths and configuration\n")
        f.write(f'export SUBJECTS="{" ".join(subjects_list)}"\n')
        f.write(f'export INPUT_DIR="{input_dir}"\n')
        f.write(f'export OUTPUT_DIR="{output_dir}"\n')
        f.write(f'export WORK_DIR="{work_dir}"\n')
        f.write(f'export CONTAINER_DIR="{container_dir}"\n')
        f.write(f'export LOG_DIR="{work_dir}/log"\n')
        f.write(f'export DB_PATH="{db_path}"\n')
        f.write(f'export TASK_NAME="{task_name}"\n')
        f.write(f'export SCRIPT_DIR="{pipeline_root}"\n')
        f.write(f'export EXECUTION_ID="{execution_id or ""}"\n')
        f.write("\n")
        
        # Export command strings if present
        if global_python_str:
            f.write("# Global Python environment commands\n")
            f.write(f'export GLOBAL_PYTHON_COMMANDS=$(cat << "PYTHON_EOF"\n')
            f.write(global_python_str + "\n")
            f.write("PYTHON_EOF\n)\n\n")
        
        if env_commands_str:
            f.write("# Environment module commands\n")
            f.write(f'export ENV_COMMANDS=$(cat << "ENV_EOF"\n')
            f.write(env_commands_str + "\n")
            f.write("ENV_EOF\n)\n\n")
        
        if global_env_str:
            f.write("# Global environment variables\n")
            f.write(f'export GLOBAL_ENV_VARS=$(cat << "GENV_EOF"\n')
            f.write(global_env_str + "\n")
            f.write("GENV_EOF\n)\n\n")
        
        if task_params_str:
            f.write("# Task-specific parameters\n")
            f.write(f'export TASK_PARAMS=$(cat << "TASK_EOF"\n')
            f.write(task_params_str + "\n")
            f.write("TASK_EOF\n)\n\n")
        
        # Source the template and execute
        f.write("# Source wrapper template and execute\n")
        f.write(f'source "$SCRIPT_DIR/utils/wrapper_functions.sh"\n')
        f.write(f'execute_wrapper "{script_path.resolve()}"\n')

    os.chmod(wrapper_path, 0o755)

    _hc = _ensure_hpc_config()
    submit_cmd = _hc.get(_hc.get("scheduler", "slurm"), {}).get("submit_cmd", "sbatch")
    sections = {
        "full_content": wrapper_path.read_text(),
        "slurm_cmd": f"{submit_cmd} {' '.join(slurm_args)} {wrapper_path}" if slurm_args else "",
        "basic_paths": "\n".join([
            f'export SUBJECTS="{" ".join(subjects_list)}"',
            f'export INPUT_DIR="{input_dir}"',
            f'export OUTPUT_DIR="{output_dir}"',
            f'export WORK_DIR="{work_dir}"',
            f'export CONTAINER_DIR="{container_dir}"',
            f'export LOG_DIR="{work_dir}/log"',
            f'export DB_PATH="{db_path}"',
            f'export TASK_NAME="{task_name}"',
            f'export SCRIPT_DIR="{pipeline_root}"',
        ]),
        "global_python":   global_python_str,
        "env_modules":     env_commands_str,
        "global_env_vars": global_env_str,
        "task_params":     task_params_str,
        "execute_cmd": "\n".join([
            f'source "$SCRIPT_DIR/utils/wrapper_functions.sh"',
            f'execute_wrapper "{script_path.resolve()}"',
        ]),
    }
    return wrapper_path, sections

def wait_for_jobs(job_ids: List[str], polling_interval: int = 60):
    """Wait for jobs to complete using the configured HPC backend."""
    backend = get_hpc_backend()
    backend.wait_for_jobs(job_ids, polling_interval)