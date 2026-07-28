"""
Output checker for resume/checkpoint mode and standalone check-outputs command.

Reads per-project output_checks YAML and verifies whether task outputs exist
for each subject. Supports two check types:
  - required_files: glob pattern + optional min_size_kb
  - count_check:    file count within expected ± tolerance
"""

import glob
import os
import warnings
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yaml

def _safe_glob(pattern: str) -> List[str]:
    return glob.glob(pattern, recursive=True)

def _expand_path(template: str, work_dir: str, subject: str,
                 session: str, prefix: str) -> str:
    return template.format(
        work_dir=work_dir,
        subject=subject,
        session=session,
        prefix=prefix,
    )

def _normalise_required_file(entry) -> dict:
    """Accept both plain string and dict with optional min_size_kb."""
    if isinstance(entry, str):
        return {"pattern": entry, "min_size_kb": None}
    return {"pattern": entry.get("pattern", ""), "min_size_kb": entry.get("min_size_kb")}

# Check functions  (return list[dict] rows, one row per check item)

def _required_files_check(task, base_path, files_config,
                           subject, session, prefix="sub-") -> List[dict]:
    rows = []
    for entry in files_config:
        spec = _normalise_required_file(entry)
        pattern = spec["pattern"]
        min_size_kb = spec["min_size_kb"]

        expanded_pattern = pattern.format(
            subject=subject,
            prefix=prefix,
            session=session,
        )
        full_pattern = os.path.join(base_path, expanded_pattern)
        matches = _safe_glob(full_pattern)

        if not matches:
            status = f"FAIL – file not found ({pattern})"
        elif min_size_kb is not None:
            threshold = min_size_kb * 1024
            big_enough = [m for m in matches if os.path.getsize(m) >= threshold]
            if not big_enough:
                status = (f"FAIL – file exists but too small "
                          f"(< {min_size_kb} KB) ({pattern})")
            else:
                status = "PASS"
        else:
            status = "PASS"

        rows.append({
            "task": task,
            "subject": subject,
            "session": session,
            "check_type": "required_files",
            "pattern": pattern,
            "expected": "exists" if min_size_kb is None else f"exists + ≥{min_size_kb} KB",
            "actual": len(matches),
            "status": status,
        })
    return rows

def _count_check(task: str, base_path: str, count_config: dict,
                 subject: str, session: str) -> List[dict]:
    rows = []
    for data_type, spec in count_config.items():
        pattern = spec.get("pattern", "")
        expected = spec.get("expected_count", 0)
        tolerance = spec.get("tolerance", 0)

        full_pattern = os.path.join(base_path, pattern)
        matches = _safe_glob(full_pattern)
        
        actual = len(matches)
        diff = actual - expected

        if abs(diff) <= tolerance:
            status = "PASS"
        elif diff > tolerance:
            status = f"FAIL – too many files on {data_type} (got {actual}, expected {expected}±{tolerance})"
        else:
            status = f"FAIL – too few files on {data_type} (got {actual}, expected {expected}±{tolerance})"

        rows.append({
            "task": task,
            "subject": subject,
            "session": session,
            "check_type": f"count_check:{data_type}",
            "pattern": pattern,
            "expected": f"{expected}±{tolerance}",
            "actual": actual,
            "status": status,
        })
    return rows

class OutputChecker:
    """
    Load a per-project output_checks YAML and run file-system checks
    across tasks and subjects.

    Parameters
    ----------
    config_path : path to the project's *_checks.yaml file
    work_dir    : base work/output directory (substituted for {work_dir})
    prefix      : subject prefix, e.g. "sub-"
    session     : session label, e.g. "01"
    """

    def __init__(self, config_path: str, work_dir: str,
                 prefix: str = "sub-", session: str = "01"):
        self.work_dir = work_dir
        self.prefix = prefix
        self.session = session
        self._config = self._load_config(config_path)


    def configured_tasks(self) -> List[str]:
        """Task names that have an entry in the checks YAML."""
        return list(self._config.keys())

    def has_task(self, task_name: str) -> bool:
        return task_name in self._config

    def warn_missing_configs(self, task_names: List[str]) -> List[str]:
        """
        Print a warning for every task that has no entry in the checks YAML.
        Returns the list of unconfigured task names.
        """
        missing = [t for t in task_names if t not in self._config]
        for t in missing:
            warnings.warn(
                f"[OutputChecker] No output check configured for task '{t}'. "
                "This task will be skipped during resume checks.",
                stacklevel=2,
            )
        return missing

    def check_subject(self, task_name: str, subject: str) -> List[dict]:
        """Run all checks for one (task, subject) pair. Returns list of row dicts."""
        task_cfg = self._config.get(task_name)
        if task_cfg is None:
            return []

        base_path = _expand_path(
            task_cfg["output_path"],
            self.work_dir, subject, self.session, self.prefix,
        )

        rows = []

        if "required_files" in task_cfg:
            rows.extend(_required_files_check(
                task_name, base_path,
                task_cfg["required_files"],
                subject, self.session,self.prefix
            ))

        if "count_check" in task_cfg:
            rows.extend(_count_check(
                task_name, base_path,
                task_cfg["count_check"],
                subject, self.session,
            ))

        return rows

    def check_all(self, task_names: List[str],
                  subjects: List[str]) -> pd.DataFrame:
        """
        Run checks for every (task, subject) combination.
        Returns a tidy DataFrame with one row per check item.
        """
        all_rows = []
        for task in task_names:
            if task not in self._config:
                continue
            for subject in subjects:
                all_rows.extend(self.check_subject(task, subject))

        if not all_rows:
            return pd.DataFrame(columns=[
                "task", "subject", "session",
                "check_type", "pattern", "expected", "actual", "status",
            ])

        return pd.DataFrame(all_rows)

    def get_completed_subjects(self, task_name: str,
                               subjects: List[str]) -> List[str]:
        """
        Return subjects for which ALL checks on task_name are PASS.
        Used by DAGExecutor to filter array job subjects.
        """
        if task_name not in self._config:
            return []

        completed = []
        for subject in subjects:
            rows = self.check_subject(task_name, subject)
            if rows and all(r["status"] == "PASS" for r in rows):
                completed.append(subject)
        return completed

    def get_pending_subjects(self, task_name: str,
                             subjects: List[str]) -> List[str]:
        """Return subjects that still need to run (complement of completed)."""
        completed = set(self.get_completed_subjects(task_name, subjects))
        return [s for s in subjects if s not in completed]

    def print_terminal_summary(self, df: pd.DataFrame) -> None:
        """
        Print only the problematic subject IDs to the terminal.
        Full details are in the CSV.
        """
        if df.empty:
            print("[check-outputs] No checks were run (no matching config).")
            return

        failed = df[df["status"] != "PASS"]

        if failed.empty:
            total_subjects = df["subject"].nunique()
            total_tasks = df["task"].nunique()
            print(f"[check-outputs] All checks passed "
                  f"({total_subjects} subjects × {total_tasks} tasks).")
            return

        print("[check-outputs] Issues found:")
        for task, group in failed.groupby("task"):
            bad_subjects = sorted(group["subject"].unique().tolist())
            print(f"  {task}: {', '.join(bad_subjects)}")

    def save_csv(self, df: pd.DataFrame, out_dir: str) -> str:
        """Save results DataFrame to CSV, return the file path."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path(out_dir) / f"check_results_{timestamp}.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)
        return str(out_path)

    @staticmethod
    def _load_config(config_path: str) -> dict:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Output checks config not found: {config_path}"
            )
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

def run_output_checks(
    config_path: str,
    work_dir: str,
    sessions: List[str],
    subjects: List[str],
    prefix: str = "sub-",
    tasks: Optional[List[str]] = None,
) -> Tuple[pd.DataFrame, List[str], List[str]]:
    """Run output checks for every (task, subject, session) combination.

    Shared by the check-outputs command and the GUI so session handling and
    task resolution stay identical. Returns
    (results, checked_tasks, unconfigured_tasks).

    Sessions are checked one at a time on purpose. A wildcard session would
    glob them all at once, letting a file present in any single session
    satisfy the check for every session.
    """
    if not sessions:
        raise ValueError("At least one session is required")
    if not subjects:
        raise ValueError("At least one subject is required")

    ref = OutputChecker(config_path=config_path, work_dir=work_dir,
                        prefix=prefix, session=sessions[0])

    requested = list(tasks) if tasks else ref.configured_tasks()
    checked = [t for t in requested if ref.has_task(t)]
    unconfigured = [t for t in requested if not ref.has_task(t)]

    frames = []
    for sess in sessions:
        checker = OutputChecker(config_path=config_path, work_dir=work_dir,
                                prefix=prefix, session=sess)
        frames.append(checker.check_all(checked, subjects))

    if frames:
        df = pd.concat(frames, ignore_index=True)
    else:
        df = pd.DataFrame(columns=[
            "task", "subject", "session",
            "check_type", "pattern", "expected", "actual", "status",
        ])
    return df, checked, unconfigured


# Convenience loader (mirrors load_project_config pattern)

def load_checks_config(project_name: str,
                       checks_dir: Optional[str] = None) -> str:
    """
    Return the path to <project_name>_checks.yaml.
    Raises FileNotFoundError if it does not exist.
    """
    if checks_dir is None:
        from .config_utils import get_config_dir
        checks_dir = get_config_dir() / "results_check"

    config_file = Path(checks_dir) / f"{project_name}_checks.yaml"

    if not config_file.exists():
        raise FileNotFoundError(
            f"Output checks config not found: {config_file}\n"
            f"Create '{project_name}_checks.yaml' in {checks_dir} to enable "
            "resume and check-outputs for this project."
        )

    return str(config_file)