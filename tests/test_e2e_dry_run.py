"""
test_e2e_dry_run.py

End-to-end smoke test: `neuromaestro init` to lay down a study, then
`neuromaestro run --dry-run` through the real Typer app, the real config loader,
the real TaskRegistry, the real DAG and the real wrapper builder.

Every other test drives these layers in isolation with mocks, so the wiring
between them was never executed: config.yaml feeding output_pattern into the
wrapper, hpc_config profiles turning into scheduler flags, work_dir vs
original_work_dir landing in the right variables. That is what this covers.

--dry-run stops short of submission but everything before it runs for real,
including script resolution and wrapper generation. No scheduler is contacted;
the test asserts that too.
"""

import json
import os
import yaml
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

PROJECT = "smoke"
SESSION = "01"
SUBJECTS = ["001", "002"]

# unzip -> unzip_rename.sh, recon -> dcm2bids_convert_BIDS.sh, both shipped in
# scripts/template and wired as recon depending on unzip.
_PREP = "unzip_recon"


def _write_project_config(config_dir: Path, scripts_dir: Path, envir: Path) -> None:
    # Local paths only. Real project configs point envir_dir at NFS mounts, and
    # Path.exists() on an unavailable mount blocks indefinitely.
    project_config = {
        "prefix": "sub-",
        "scripts_dir": str(scripts_dir),
        "database": {"db_path": "$WORK_DIR/database/pipeline_jobs.db"},
        "envir_dir": {
            "container_dir": str(envir / "containers"),
            "virtual_envir": str(envir / "conda_env"),
            "template_dir": str(envir / "templates"),
            "atlas_dir": str(envir / "atlas"),
            "freesurfer_dir": str(envir / "freesurfer"),
            "config_dir": str(envir / "bids_config"),
            "stimulus_dir": str(envir / "stimulus"),
        },
        "global_python": ["echo mock-python"],
        "modules": {
            "data_manage_1": ["echo mock-datamanage"],
            "afni_24.3.06": ["echo mock-afni"],
        },
        "tasks": {
            "unzip": {"environ": ["data_manage_1", "afni_24.3.06"]},
            "recon": {"container": "dcm2bids_3.2.0.sif", "config": "branch_config.json"},
        },
    }
    pc_dir = config_dir / "project_config"
    pc_dir.mkdir(parents=True, exist_ok=True)
    (pc_dir / f"{PROJECT}_config.yaml").write_text(
        yaml.dump(project_config), encoding="utf-8"
    )


@pytest.fixture(scope="module")
def dry_run(tmp_path_factory):
    """Run the CLI once; the tests below inspect different parts of the result."""
    from neuromaestro.pipeline.utils import config_utils, hpc_utils
    from neuromaestro.pipeline.utils.init_utils import init_project_templates

    tmp = tmp_path_factory.mktemp("e2e")

    config_dir = tmp / "study" / "config"
    copied = init_project_templates(config_dir)
    assert "scripts/" in copied
    scripts_dir = tmp / "study" / "scripts"

    envir = tmp / "envir"
    for name in ("containers", "conda_env", "templates", "atlas", "freesurfer",
                 "bids_config", "stimulus"):
        (envir / name).mkdir(parents=True)
    (envir / "containers" / "dcm2bids_3.2.0.sif").write_text("mock container")
    (envir / "bids_config" / "branch_config.json").write_text("{}")

    _write_project_config(config_dir, scripts_dir, envir)

    input_dir = tmp / "input"
    for subject in SUBJECTS:
        (input_dir / f"sub-{subject}").mkdir(parents=True)
    output_dir = tmp / "output"
    work_dir = tmp / "work"

    # set_config_dir and _ensure_hpc_config mutate module globals; other tests
    # rely on them being untouched (including the "config dir not set" paths)
    saved = (config_utils._config_dir, config_utils.config, hpc_utils.hpc_config)
    saved_env = os.environ.get("NEUROMAESTRO_CONFIG_DIR")
    os.environ["NEUROMAESTRO_CONFIG_DIR"] = str(config_dir)

    from neuromaestro.pipeline.core import app

    try:
        with patch("subprocess.run") as mock_subprocess:
            result = CliRunner().invoke(app, [
                "run",
                "--subjects", ",".join(SUBJECTS),
                "--input", str(input_dir),
                "--output", str(output_dir),
                "--work", str(work_dir),
                "--project", PROJECT,
                "--session", SESSION,
                "--prep", _PREP,
                "--dry-run",
                "--skip-preflight",
                "--skip-bids-validation",
            ])
            subprocess_calls = list(mock_subprocess.call_args_list)

        wrappers = {
            p.name.split("_wrapper")[0].rsplit("_", 1)[0]: p.read_text(encoding="utf-8")
            for p in (work_dir / PROJECT / "log" / "wrapper").glob("*_wrapper.sh")
        }
        yield SimpleNamespace(
            result=result,
            output=result.output,
            wrappers=wrappers,
            subprocess_calls=subprocess_calls,
            work_dir=work_dir,
            output_dir=output_dir,
            input_dir=input_dir,
            scripts_dir=scripts_dir,
        )
    finally:
        config_utils._config_dir, config_utils.config, hpc_utils.hpc_config = saved
        if saved_env is None:
            os.environ.pop("NEUROMAESTRO_CONFIG_DIR", None)
        else:
            os.environ["NEUROMAESTRO_CONFIG_DIR"] = saved_env


# ---------------------------------------------------------------------------
# The run itself
# ---------------------------------------------------------------------------

class TestTheRunSucceeds:

    def test_exit_code_is_zero(self, dry_run):
        assert dry_run.result.exit_code == 0, dry_run.output

    def test_both_tasks_were_expanded(self, dry_run):
        assert "Tasks: ['unzip', 'recon']" in dry_run.output

    def test_subjects_were_parsed(self, dry_run):
        assert f"Subjects: {SUBJECTS}" in dry_run.output

    def test_dag_order_puts_recon_after_unzip(self, dry_run):
        assert "unzip <- (no dependencies)" in dry_run.output
        assert "recon <- unzip" in dry_run.output

    def test_summary_counts_both_jobs(self, dry_run):
        assert "Tasks executed: 2" in dry_run.output
        assert "Jobs submitted: 2" in dry_run.output

    def test_run_completed(self, dry_run):
        assert "=== Completed ===" in dry_run.output


class TestNothingWasSubmitted:

    def test_no_subprocess_was_spawned(self, dry_run):
        """--dry-run must not reach sbatch."""
        assert dry_run.subprocess_calls == []

    def test_no_sqlite_database_was_created(self, dry_run):
        # dry runs only append JSONL; the DB is built later by merge-logs
        assert not (dry_run.work_dir / "database" / "pipeline_jobs.db").exists()


# ---------------------------------------------------------------------------
# Wrapper generation — the actual artifact handed to the scheduler
# ---------------------------------------------------------------------------

class TestWrappersWereGenerated:

    def test_one_wrapper_per_task(self, dry_run):
        assert set(dry_run.wrappers) == {"unzip_rename", "dcm2bids_convert_BIDS"}

    @pytest.mark.parametrize("task", ["unzip_rename", "dcm2bids_convert_BIDS"])
    def test_wrapper_sources_the_shared_functions(self, dry_run, task):
        body = dry_run.wrappers[task]
        assert 'source "$SCRIPT_DIR/utils/wrapper_functions.sh"' in body
        assert "execute_wrapper" in body

    @pytest.mark.parametrize("task", ["unzip_rename", "dcm2bids_convert_BIDS"])
    def test_wrapper_carries_the_run_options(self, dry_run, task):
        body = dry_run.wrappers[task]
        assert "export SUBJECTS='001 002'" in body
        assert f"export SESSION='{SESSION}'" in body
        assert "export PREFIX='sub-'" in body
        assert f"export PROJECT='{PROJECT}'" in body

    @pytest.mark.parametrize("task", ["unzip_rename", "dcm2bids_convert_BIDS"])
    def test_wrapper_carries_an_execution_id(self, dry_run, task):
        body = dry_run.wrappers[task]
        line = next(l for l in body.splitlines() if l.startswith("export EXECUTION_ID="))
        assert line.split("=", 1)[1].strip("'").isdigit()

    def test_task_name_is_the_config_task_not_the_script(self, dry_run):
        assert "export TASK_NAME='unzip'" in dry_run.wrappers["unzip_rename"]
        assert "export TASK_NAME='recon'" in dry_run.wrappers["dcm2bids_convert_BIDS"]

    def test_environ_modules_are_inlined_in_order(self, dry_run):
        body = dry_run.wrappers["unzip_rename"]
        assert body.index("echo mock-datamanage") < body.index("echo mock-afni")

    def test_global_python_is_inlined(self, dry_run):
        assert "echo mock-python" in dry_run.wrappers["unzip_rename"]

    def test_envir_dir_becomes_exported_variables(self, dry_run):
        body = dry_run.wrappers["unzip_rename"]
        for var in ("ATLAS_DIR", "CONFIG_DIR", "CONTAINER_DIR", "FREESURFER_DIR",
                    "STIMULUS_DIR", "TEMPLATE_DIR", "VIRTUAL_ENVIR"):
            assert f"export {var}=" in body, var

    def test_wrapper_points_at_the_real_script(self, dry_run):
        body = dry_run.wrappers["unzip_rename"]
        # the last line, not the "# Original script:" comment that names the same path
        script = (dry_run.scripts_dir / "unzip_rename.sh").resolve()
        assert body.splitlines()[-1] == f'execute_wrapper "{script}"'


class TestConfigReachesTheWrapper:
    """The cross-layer wiring: config.yaml and hpc_config.yaml both end up here."""

    def test_output_pattern_from_config_yaml_is_expanded(self, dry_run):
        # config.yaml gives unzip output_pattern "{base_output}/raw"
        body = dry_run.wrappers["unzip_rename"]
        line = next(l for l in body.splitlines() if l.startswith("export OUTPUT_DIR="))
        assert line.rstrip("'").endswith("/raw"), line

    def test_hpc_profile_becomes_scheduler_flags(self, dry_run):
        # unzip uses profile "standard": 32gb / 20:00:00 / 16 cpus
        body = dry_run.wrappers["unzip_rename"]
        assert "--mem=32gb" in body
        assert "--time=20:00:00" in body
        assert "--cpus-per-task=16" in body

    def test_db_path_resolves_work_dir_without_the_project(self, dry_run):
        """work_dir gains the project name, db_path deliberately does not."""
        body = dry_run.wrappers["unzip_rename"]
        db_line = next(l for l in body.splitlines() if l.startswith("export DB_PATH="))
        work_line = next(l for l in body.splitlines() if l.startswith("export WORK_DIR="))
        assert "$WORK_DIR" not in db_line
        assert "database" in db_line
        assert PROJECT not in db_line.replace(str(dry_run.work_dir), "")
        assert work_line.rstrip("'").endswith(PROJECT)


# ---------------------------------------------------------------------------
# Execution logging
# ---------------------------------------------------------------------------

class TestExecutionWasLogged:

    @pytest.fixture
    def record(self, dry_run):
        jsonl = sorted((dry_run.work_dir / "database" / "json" / "_pipeline")
                       .glob("execution_*.jsonl"))
        assert len(jsonl) == 1, jsonl
        lines = jsonl[0].read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(l) for l in lines]

    def test_start_and_update_were_both_written(self, record):
        assert len(record) == 2
        assert record[1]["status"] == "COMPLETED"

    def test_start_record_marks_the_dry_run(self, record):
        assert record[0]["dry_run"] is True

    def test_start_record_captures_the_request(self, record):
        start = record[0]
        assert start["project_name"] == PROJECT
        assert start["session"] == SESSION
        # both are stored comma-joined, not as JSON lists
        assert start["subjects"].split(",") == SUBJECTS
        assert start["requested_tasks"].split(",") == ["unzip", "recon"]


# ---------------------------------------------------------------------------
# Relative CLI paths
# ---------------------------------------------------------------------------

def _lay_down_study(root: Path) -> Path:
    """Returns the config dir of a study under root, with one subject in root/input."""
    from neuromaestro.pipeline.utils.init_utils import init_project_templates

    config_dir = root / "study" / "config"
    init_project_templates(config_dir)
    envir = root / "envir"
    for name in ("containers", "conda_env", "templates", "atlas", "freesurfer",
                 "bids_config", "stimulus"):
        (envir / name).mkdir(parents=True)
    (envir / "containers" / "dcm2bids_3.2.0.sif").write_text("mock container")
    (envir / "bids_config" / "branch_config.json").write_text("{}")
    _write_project_config(config_dir, root / "study" / "scripts", envir)
    (root / "input" / "sub-001").mkdir(parents=True)
    return config_dir


def test_relative_paths_are_absolute_by_the_time_they_reach_the_wrapper(tmp_path, monkeypatch):
    """A relative --output resolves against the submit host's working directory,
    which the compute node does not share. run() calls abspath before anything
    else so the wrapper always carries a path both hosts agree on.

    Separate from the module fixture: that one passes tmp_path absolutes, where
    abspath is the identity and would prove nothing.
    """
    from neuromaestro.pipeline.utils import config_utils, hpc_utils
    from neuromaestro.pipeline.core import app

    config_dir = _lay_down_study(tmp_path)

    saved = (config_utils._config_dir, config_utils.config, hpc_utils.hpc_config)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEUROMAESTRO_CONFIG_DIR", str(config_dir))
    try:
        with patch("subprocess.run"):
            result = CliRunner().invoke(app, [
                "run",
                "--subjects", "001",
                "--input", "input",
                "--output", "output",
                "--work", "work",
                "--project", PROJECT,
                "--session", SESSION,
                "--prep", _PREP,
                "--dry-run",
                "--skip-preflight",
                "--skip-bids-validation",
            ])
        assert result.exit_code == 0, result.output

        wrappers = list((tmp_path / "work" / PROJECT / "log" / "wrapper").glob("*_wrapper.sh"))
        assert wrappers, "no wrapper was generated"

        for wrapper in wrappers:
            body = wrapper.read_text(encoding="utf-8")
            for var in ("INPUT_DIR", "OUTPUT_DIR", "WORK_DIR", "DB_PATH"):
                line = next(l for l in body.splitlines()
                            if l.startswith(f"export {var}="))
                value = line.split("=", 1)[1].strip().strip("'")
                assert os.path.isabs(value), f"{wrapper.name}: {line}"
    finally:
        config_utils._config_dir, config_utils.config, hpc_utils.hpc_config = saved


# ---------------------------------------------------------------------------
# Re-running into existing directories
# ---------------------------------------------------------------------------

def test_a_second_run_into_the_same_directories_succeeds(tmp_path, monkeypatch):
    """Every --resume run reuses the work, output and database directories of the first."""
    from neuromaestro.pipeline.utils import config_utils, hpc_utils
    from neuromaestro.pipeline.core import app

    config_dir = _lay_down_study(tmp_path)
    saved = (config_utils._config_dir, config_utils.config, hpc_utils.hpc_config)
    monkeypatch.setenv("NEUROMAESTRO_CONFIG_DIR", str(config_dir))
    args = [
        "run",
        "--subjects", "001",
        "--input", str(tmp_path / "input"),
        "--output", str(tmp_path / "output"),
        "--work", str(tmp_path / "work"),
        "--project", PROJECT,
        "--session", SESSION,
        "--prep", _PREP,
        "--dry-run",
        "--skip-preflight",
        "--skip-bids-validation",
    ]
    try:
        with patch("subprocess.run"):
            for attempt in (1, 2):
                result = CliRunner().invoke(app, args)
                assert result.exit_code == 0, f"run {attempt}:\n{result.output}"
    finally:
        config_utils._config_dir, config_utils.config, hpc_utils.hpc_config = saved
