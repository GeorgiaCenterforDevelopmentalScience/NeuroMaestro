"""
preflight.py — Schema validation for neuromaestro run.

Validates project config structure and references against global config
before job submission. Filesystem checks are intentionally omitted:
NFS/GPFS/Lustre mounts on HPC clusters can cause Path.exists() to block
indefinitely at the kernel level.
"""

import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional

from .config_utils import get_config_dir

@dataclass
class Issue:
    severity: str   # "ERROR" | "WARNING"
    category: str   # "schema" | "scripts" | "containers" | "directories"
    message: str

@dataclass
class PreflightResult:
    issues: List[Issue] = field(default_factory=list)

    @property
    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == "ERROR"]

    @property
    def warnings(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == "WARNING"]

    @property
    def ok(self) -> bool:
        """True when there are no ERROR-level issues."""
        return len(self.errors) == 0

class PreflightChecker:
    """
    Validates project config structure and references before job submission.

    Parameters
    ----------
    project_config : dict
        Loaded project YAML (e.g. branch_config.yaml).
    global_config : dict
        Loaded global pipeline config (config.yaml).
    """

    def __init__(
        self,
        project_config: Dict[str, Any],
        global_config: Dict[str, Any],
        hpc_config: Optional[Dict[str, Any]] = None,
    ):
        self.project_config = project_config
        self.global_config = global_config
        if hpc_config is None:
            try:
                with open(get_config_dir() / "hpc_config.yaml", "r", encoding="utf-8") as _f:
                    hpc_config = yaml.safe_load(_f) or {}
            except (FileNotFoundError, RuntimeError):
                hpc_config = {}
        self.hpc_config = hpc_config
        self._issues: List[Issue] = []

    def _err(self, category: str, message: str) -> None:
        self._issues.append(Issue("ERROR", category, message))

    def _warn(self, category: str, message: str) -> None:
        self._issues.append(Issue("WARNING", category, message))

    def _all_global_tasks(self):
        for section_tasks in self.global_config.values():
            if isinstance(section_tasks, list):
                for task in section_tasks:
                    if isinstance(task, dict) and "name" in task:
                        yield task

    def _all_global_task_names(self) -> set:
        return {task["name"] for task in self._all_global_tasks()}

    # Schema/reference validation

    def check_schema(self) -> None:
        pc = self.project_config

        # Required top-level keys in project config
        for key in ("prefix", "scripts_dir", "envir_dir", "database", "tasks"):
            if key not in pc:
                self._err("schema", f"project config missing required key: '{key}'")

        # envir_dir.container_dir
        envir_dir = pc.get("envir_dir") or {}
        if "container_dir" not in envir_dir:
            self._err("schema", "project config: envir_dir.container_dir is required")

        # database.db_path
        db_config = pc.get("database") or {}
        if "db_path" not in db_config:
            self._err("schema", "project config: database.db_path is required")

        # resource_profiles live in hpc_config.yaml
        global_profiles = set((self.hpc_config.get("resource_profiles") or {}).keys())

        # modules defined in project config
        defined_modules = set((pc.get("modules") or {}).keys())

        # global task names
        global_task_names = self._all_global_task_names()

        # Checked over every registered task, not only those the project config
        # overrides: a task is submittable without a project entry, and profile
        # has no default, so anything missed here surfaces only at submission.
        for gtask in self._all_global_tasks():
            profile = gtask.get("profile")
            if not profile:
                self._err(
                    "schema",
                    f"global config.yaml: task '{gtask['name']}' sets no resource profile",
                )
            elif profile not in global_profiles:
                self._err(
                    "schema",
                    f"task '{gtask['name']}': resource profile '{profile}' is not defined in resource_profiles",
                )

        # Validate each tasks entry
        tasks = pc.get("tasks") or {}
        if not isinstance(tasks, dict):
            self._err("schema", "project config: 'tasks' must be a mapping of task_name -> properties")
        else:
            for name, entry in tasks.items():
                if not isinstance(entry, dict):
                    self._err("schema", f"tasks.{name}: value must be a mapping")
                    continue

                # Task must exist in global config
                if name not in global_task_names:
                    self._err(
                        "schema",
                        f"tasks entry '{name}' is not defined in global config.yaml",
                    )

                # environ references must be defined in project config modules
                for mod in entry.get("environ") or []:
                    if mod not in defined_modules:
                        self._err(
                            "schema",
                            f"task '{name}': environ entry '{mod}' is not defined in project config modules",
                        )

    def run_all(self) -> PreflightResult:
        """Run schema checks and return the result."""
        self._issues = []
        self.check_schema()
        return PreflightResult(issues=list(self._issues))

# Reporting
def print_preflight_report(result: PreflightResult) -> None:
    """Print a structured pre-flight report to stdout."""
    n_err = len(result.errors)
    n_warn = len(result.warnings)

    if n_err == 0 and n_warn == 0:
        print("[preflight] All checks passed.")
        return

    header = f"[preflight] {n_err} error(s), {n_warn} warning(s) found"
    print(header)

    # Group by category
    by_category: Dict[str, List[Issue]] = {}
    for issue in result.issues:
        by_category.setdefault(issue.category, []).append(issue)

    for category, issues in by_category.items():
        print(f"\n  [{category}]")
        for issue in issues:
            tag = "  ERROR  " if issue.severity == "ERROR" else "  warning"
            print(f"    {tag}: {issue.message}")

    if n_err > 0:
        print(
            f"\n[preflight] {n_err} error(s) must be resolved before jobs can be submitted."
            "\n            Re-run with --skip-preflight to bypass these checks."
        )
    else:
        print(f"\n[preflight] No blocking errors. Warnings above are informational.")
