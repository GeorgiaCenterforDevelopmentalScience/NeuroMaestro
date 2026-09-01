"""Measure how the coordination layer scales with cohort size.

Submits nothing. Every phase runs through the real code path with dry_run=True,
which in hpc_utils.submit_slurm_job returns after the wrapper is written and
before the scheduler is contacted.

All writes go into a single timestamped directory created under WORK_DIR, and
nothing outside that directory is ever created or deleted. Pass --keep to leave
it behind for inspection.

Run this on the cluster filesystem the pipeline actually uses. The submission
and verification phases are dominated by filesystem calls, so timings from a
local SSD do not transfer.

    python tests/scaling_benchmark.py

Edit the settings block below to point at a different cluster or project. Every
setting also has a command-line override.

Reading the numbers: DAG resolution is a component of the submission path, not
additive with it. The submission path excludes pre-flight and BIDS validation.
The output-check timing excludes the CSV summary that check-outputs also writes.
"""

import argparse
import contextlib
import io
import os
import shutil
import statistics
import time
from pathlib import Path

import yaml

from neuromaestro.pipeline.dag import DAGExecutor, TaskRegistry
from neuromaestro.pipeline.utils.config_utils import get_config, get_config_dir
from neuromaestro.pipeline.utils.output_checker import OutputChecker, _expand_path

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

CONFIG_DIR = "/scratch/qy49547/open_dataset/config"
WORK_DIR = "/scratch/qy49547/open_dataset/test/dry_run"
PROJECT = "ds027"
SIZES = [30, 100, 500, 1000, 2000]
REPEATS = 3

# Mirrors the ds027 demonstration reported in the manuscript
REQUESTED = dict(
    intermed=["volume"],
    bids_prep=["rest", "dwi"],
    bids_post=["rest", "dwi"],
    staged_prep=["emomatching", "stopsignal", "workingmemory"],
    staged_post=["emomatching", "stopsignal", "workingmemory"],
    mriqc="all",
)

# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------


def subject_ids(n):
    return [f"{i:04d}" for i in range(1, n + 1)]


def resolve_tasks():
    from neuromaestro.pipeline.utils.config_utils import MRIQCChoice

    kwargs = dict(REQUESTED)
    kwargs["mriqc"] = MRIQCChoice(kwargs["mriqc"])
    return TaskRegistry().expand_tasks(**kwargs)


def time_median(fn, repeats):
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    return statistics.median(samples)


def _fresh(run_root: Path, name: str) -> Path:
    """A new empty directory under the run root. Never touches anything else."""
    target = run_root / name
    if target.exists():
        raise RuntimeError(f"unexpected leftover, refusing to overwrite: {target}")
    target.mkdir(parents=True)
    return target


def phase_dag(tasks, repeats):
    def run():
        DAGExecutor(get_config()).build_dag(list(tasks))

    return time_median(run, repeats)


def phase_submit(tasks, subjects, project_config, run_root, repeats):
    """Everything neuromaestro run does before it calls sbatch. Each repeat gets a
    fresh directory so the per-subject log mkdir loop is exercised rather than
    hitting directories that already exist."""
    samples = []
    for i in range(repeats):
        run_dir = _fresh(run_root, f"submit_{len(subjects)}_{i}")

        executor = DAGExecutor(get_config())
        t0 = time.perf_counter()
        # execute() echoes the resolved plan on every call, which would print
        # once per repeat per cohort size
        with contextlib.redirect_stdout(io.StringIO()):
            executor.execute(
                requested_tasks=list(tasks),
                input_dir=str(run_dir / "in"),
                output_dir=str(run_dir / "out"),
                work_dir=str(run_dir),
                container_dir=str(run_dir / "containers"),
                dry_run=True,
                context={"subjects": subjects},
                option_env={"session": "01"},
                project_config=project_config,
                db_path=str(run_dir / "jobs.db"),
            )
        samples.append(time.perf_counter() - t0)
    return statistics.median(samples)


def build_output_tree(checks_config, tree_dir, subjects, prefix="sub-", session="01"):
    """Create files that satisfy every configured check.

    check-outputs against an empty tree returns on the first failed glob, which
    measures nothing. A populated tree makes the walk do the work it does in a
    real run.
    """
    cfg = yaml.safe_load(Path(checks_config).read_text())
    written = 0
    for task, task_cfg in cfg.items():
        for subject in subjects:
            base = _expand_path(
                task_cfg["output_path"], str(tree_dir), subject, session, prefix
            )
            os.makedirs(base, exist_ok=True)

            for entry in task_cfg.get("required_files", []):
                spec = entry if isinstance(entry, dict) else {"pattern": entry}
                name = spec["pattern"].format(
                    subject=subject, prefix=prefix, session=session
                )
                # a glob wildcard has to become a literal for the file to exist
                name = name.replace("**", "x").replace("*", "x").replace("?", "x")
                target = Path(base) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                kb = spec.get("min_size_kb") or 1
                target.write_bytes(b"0" * int(kb * 1024))
                written += 1

            for _, count_cfg in task_cfg.get("count_check", {}).items():
                name = count_cfg["pattern"].format(
                    subject=subject, prefix=prefix, session=session
                )
                name = name.replace("**", "x").replace("*", "x").replace("?", "x")
                for k in range(int(count_cfg.get("expected_count", 1))):
                    target = Path(base) / f"{k}_{name}"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"0")
                    written += 1
    return written


def phase_verify(checks_config, tree_dir, subjects, tasks, repeats):
    checker = OutputChecker(
        config_path=str(checks_config), work_dir=str(tree_dir),
        prefix="sub-", session="01",
    )
    configured = [t for t in tasks if checker.has_task(t)]

    def run():
        for task in configured:
            for subject in subjects:
                checker.check_subject(task, subject)

    return time_median(run, repeats), len(configured)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config-dir", default=CONFIG_DIR)
    ap.add_argument("--work-dir", default=WORK_DIR,
                    help="parent directory; a single timestamped subdirectory is "
                         "created under it and nothing outside it is touched")
    ap.add_argument("--project", default=PROJECT)
    ap.add_argument("--sizes", type=int, nargs="+", default=SIZES)
    ap.add_argument("--repeats", type=int, default=REPEATS)
    ap.add_argument("--skip-verification", action="store_true",
                    help="skip the output-check phase, which writes one file per "
                         "check per subject")
    ap.add_argument("--keep", action="store_true",
                    help="leave the run directory in place instead of removing it")
    args = ap.parse_args()

    from neuromaestro.pipeline.utils.config_utils import set_config_dir
    set_config_dir(args.config_dir)

    config_dir = get_config_dir()
    project_config_path = Path(config_dir) / "project_config" / f"{args.project}_config.yaml"
    checks_config = Path(config_dir) / "results_check" / f"{args.project}_checks.yaml"
    project_config = yaml.safe_load(project_config_path.read_text())

    parent = Path(args.work_dir).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    run_root = parent / f"scaling_bench_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
    run_root.mkdir()

    tasks = resolve_tasks()
    print(f"run directory: {run_root}")
    print(f"{len(tasks)} tasks, median of {args.repeats} repeats\n")

    header = (f"{'N':>6}  {'DAG only (s)':>13}  {'submission path (s)':>20}  "
              f"{'output checks (s)':>18}")
    print(header)
    print("-" * len(header))

    try:
        for n in args.sizes:
            subjects = subject_ids(n)

            dag = phase_dag(tasks, args.repeats)
            submit = phase_submit(tasks, subjects, project_config, run_root, args.repeats)

            if args.skip_verification:
                verify_str = "skipped"
            else:
                tree_dir = _fresh(run_root, f"verify_{n}")
                build_output_tree(checks_config, tree_dir, subjects)
                verify, _ = phase_verify(checks_config, tree_dir, subjects, tasks, args.repeats)
                verify_str = f"{verify:.3f}"

            print(f"{n:>6}  {dag:>13.4f}  {submit:>20.3f}  {verify_str:>18}")
    finally:
        if args.keep:
            print(f"\nrun directory kept: {run_root}")
        else:
            shutil.rmtree(run_root, ignore_errors=True)


if __name__ == "__main__":
    main()
