from enum import Enum
from typing import List, Optional, Dict, Any, Tuple
import typer
import yaml
from pathlib import Path


_config_dir: Optional[Path] = None


def get_config_dir() -> Path:
    if _config_dir is None:
        raise RuntimeError(
            "Config directory not set. Pass --config-dir or set NEUROMAESTRO_CONFIG_DIR."
        )
    return _config_dir


def get_config() -> dict:
    return config


def set_config_dir(path) -> None:
    global _config_dir, config
    _config_dir = Path(path)
    with open(_config_dir / "config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    # hpc_config.yaml follows the same dir but is cached in hpc_utils, which would
    # otherwise serve the previous project for the life of a long-running process.
    # Imported here rather than at module level: hpc_utils imports this module.
    from . import hpc_utils
    hpc_utils.hpc_config = None


config: dict = {}


class PrepChoice(str, Enum):
    unzip = "unzip"
    recon = "recon"
    unzip_recon = "unzip_recon"


class MRIQCChoice(str, Enum):
    group = "group"
    individual = "individual"
    all = "all"

def get_tasks_from_section(section: str, stage: str = None) -> List[Tuple[str, List[str]]]:
    section_tasks = config.get(section, [])
    result = []
    for task in section_tasks:
        if not isinstance(task, dict):
            continue
        if stage is None or task.get('stage') == stage:
            dep = task.get('input_from')
            deps = [dep] if dep else []
            result.append((task['name'], deps))
    return result


def get_tasks_by_suffix(suffix: str, category: str = None) -> List[str]:
    """Get task names by suffix pattern.

    If category is given, search only that config section.
    If category is None (default), search all sections.
    """
    if category:
        all_tasks = config.get(category, [])
    else:
        all_tasks = []
        for val in config.values():
            if isinstance(val, list):
                all_tasks.extend(val)
    return [t['name'] for t in all_tasks if isinstance(t, dict) and suffix in t.get('name', '')]

def get_all_task_names(category: str = None) -> List[str]:
    """Get all task names. If category is given, only that section; otherwise all sections in config order."""
    if category:
        return [t['name'] for t in config.get(category, []) if isinstance(t, dict)]
    names = []
    for val in config.values():
        if not isinstance(val, list):
            continue
        for task in val:
            if isinstance(task, dict) and 'name' in task:
                names.append(task['name'])
    return names

def validate_task_name(task_name: str) -> bool:
    """Check if task exists across all config sections"""
    return task_name in get_all_task_names()

def expand_task_names(task_list: List[str], suffix: str) -> List[str]:
    """Expand short names to full task names"""
    return [f"{task}{suffix}" for task in task_list]

def clean_all_only(argval: List[str], name: str) -> List[str]:
    """Clean up 'all' when mixed with other options"""
    if isinstance(argval, list) and 'all' in argval and len(argval) > 1:
        typer.echo(f"Warning: '{name}' has 'all' + other values. Using 'all' only.")
        return ['all']
    return argval

# TODO: need add to pytest
def find_task_config_by_name(task_name: str) -> Optional[Dict[str, Any]]:
    """Find task configuration by name"""
    for section_name, section_tasks in config.items():
        if isinstance(section_tasks, list):
            for task in section_tasks:
                if isinstance(task, dict) and task.get('name') == task_name:
                    return task
        elif isinstance(section_tasks, dict):
            if section_name == task_name:
                task_config = section_tasks.copy()
                task_config['name'] = task_name
                return task_config
    return None


def find_task_config_by_name_with_project(task_name: str, project_config: dict = None) -> Optional[Dict[str, Any]]:
    """Find task configuration, merging global and project configs"""
    global_task_config = find_task_config_by_name(task_name)

    if not global_task_config:
        typer.echo(f"Warning: No global config for: {task_name}")
        return None

    if project_config and 'tasks' in project_config:
        project_tasks = project_config['tasks'] or {}
        task_overrides = project_tasks.get(task_name)
        if task_overrides and isinstance(task_overrides, dict):
            merged_config = global_task_config.copy()
            merged_config.update(task_overrides)
            return merged_config

    return global_task_config


def get_intermed_task_names() -> List[str]:
    """Return task names from the intermed section of config.yaml."""
    return [t['name'] for t in config.get('intermed', []) if isinstance(t, dict) and 'name' in t]

_SYSTEM_SECTIONS = {'prep', 'intermed', 'qc'}

def get_bids_pipeline_names() -> List[str]:
    """Return section names for BIDS-native pipelines (tasks without multi_stage)."""
    names = []
    for section, tasks in config.items():
        if section in _SYSTEM_SECTIONS or not isinstance(tasks, list):
            continue
        if not any(t.get('multi_stage') for t in tasks if isinstance(t, dict)):
            names.append(section)
    return names

def get_staged_pipeline_names() -> List[str]:
    """Return section names for staged pipelines (tasks with multi_stage: true)."""
    names = []
    for section, tasks in config.items():
        if section in _SYSTEM_SECTIONS or not isinstance(tasks, list):
            continue
        if any(t.get('multi_stage') for t in tasks if isinstance(t, dict)):
            names.append(section)
    return names

def load_project_config(project_name: str, config_dir: str = None):
    """Load project configuration from YAML file"""
    if config_dir is None:
        config_dir = get_config_dir() / "project_config"

    config_file = Path(config_dir) / f"{project_name}_config.yaml"

    if not config_file.exists():
        raise FileNotFoundError(f"Config not found: {config_file}")

    with open(config_file, 'r', encoding='utf-8') as f:
        project_config = yaml.safe_load(f)

    return project_config