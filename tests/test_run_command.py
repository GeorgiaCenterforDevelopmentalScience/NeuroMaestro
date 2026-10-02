"""`neuromaestro run` past the dry run: submission, --wait, --resume, pre-flight, BIDS validation and failures."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml
from typer.testing import CliRunner

from neuromaestro.pipeline.dag import DAGExecutor
from tests.test_e2e_dry_run import PROJECT, SESSION, _PREP, _lay_down_study

BIDS_VALIDATION = "neuromaestro.pipeline.utils.bids_validation.run_bids_validation"
WAIT_FOR_JOBS = "neuromaestro.pipeline.core.wait_for_jobs"


class FakeSbatch:

    def __init__(self):
        self.calls = []

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=f"Submitted batch job {1000 + len(self.calls)}\n", stderr="")


@pytest.fixture
def study(tmp_path, monkeypatch):
    from neuromaestro.pipeline.utils import config_utils, hpc_utils

    config_dir = _lay_down_study(tmp_path)
    saved = (config_utils._config_dir, config_utils.config, hpc_utils.hpc_config)
    monkeypatch.setenv("NEUROMAESTRO_CONFIG_DIR", str(config_dir))
    sbatch = FakeSbatch()

    def invoke(*extra, prep=_PREP):
        from neuromaestro.pipeline.core import app
        args = ["run", "--subjects", "001",
                "--input", str(tmp_path / "input"),
                "--output", str(tmp_path / "output"),
                "--work", str(tmp_path / "work"),
                "--project", PROJECT, "--session", SESSION]
        if prep:
            args += ["--prep", prep]
        with patch("subprocess.run", side_effect=sbatch):
            return CliRunner().invoke(app, args + list(extra))

    def records():
        files = sorted((tmp_path / "work" / "database" / "json" / "_pipeline").glob("execution_*.jsonl"))
        return [json.loads(line) for f in files for line in f.read_text(encoding="utf-8").splitlines()]

    def edit_project_config(change):
        path = config_dir / "project_config" / f"{PROJECT}_config.yaml"
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        change(cfg)
        path.write_text(yaml.dump(cfg), encoding="utf-8")

    try:
        yield SimpleNamespace(root=tmp_path, config_dir=config_dir, sbatch=sbatch, invoke=invoke,
                              records=records, edit_project_config=edit_project_config)
    finally:
        config_utils._config_dir, config_utils.config, hpc_utils.hpc_config = saved


QUICK = ("--skip-preflight", "--skip-bids-validation")


# ---------------------------------------------------------------------------
# A real run hands one job per task to the scheduler
# ---------------------------------------------------------------------------

class TestRealSubmission:

    def test_each_task_is_submitted_once_in_dag_order(self, study):
        result = study.invoke(*QUICK)
        assert result.exit_code == 0, result.output
        assert [c[0] for c in study.sbatch.calls] == ["sbatch", "sbatch"]
        wrappers = [Path(c[-1]).name for c in study.sbatch.calls]
        assert wrappers[0].startswith("unzip_rename_") and wrappers[0].endswith("_wrapper.sh")
        assert wrappers[1].startswith("dcm2bids_convert_BIDS_") and wrappers[1].endswith("_wrapper.sh")

    def test_recon_waits_for_the_unzip_job_it_was_given(self, study):
        study.invoke(*QUICK)
        unzip, recon = study.sbatch.calls
        assert not any(a.startswith("--dependency") for a in unzip)
        assert [a for a in recon if a.startswith("--dependency")] == ["--dependency=afterany:1001"]

    def test_summary_names_every_job(self, study):
        lines = study.invoke(*QUICK).output.splitlines()
        assert "Jobs submitted: 2" in lines
        assert lines[lines.index("Jobs submitted: 2") + 1:][:2] == ["  unzip: 1001", "  recon: 1002"]

    def test_follow_up_commands_point_at_the_shared_database(self, study):
        lines = study.invoke(*QUICK).output.splitlines()
        db = f"{study.root / 'work'}/database/pipeline_jobs.db"
        assert f"  python -m neuromaestro.pipeline.utils.job_db query_jobs --db-path {db}" in lines
        # the database and merge-logs take --work without the project name
        assert f"  neuromaestro merge-logs {study.root / 'work'}" in lines

    def test_execution_is_recorded_as_a_real_run(self, study):
        study.invoke(*QUICK)
        start, end = study.records()
        assert start["dry_run"] is False
        assert (end["status"], end["total_jobs"], end["error_msg"]) == ("COMPLETED", 2, None)

    def test_dry_run_submits_nothing_and_skips_the_job_listing(self, study):
        lines = study.invoke(*QUICK, "--dry-run").output.splitlines()
        assert study.sbatch.calls == []
        assert "  unzip: 1001" not in lines
        assert not any("query_jobs" in line for line in lines)


# ---------------------------------------------------------------------------
# --wait
# ---------------------------------------------------------------------------

class TestWait:

    def test_waits_on_every_submitted_job(self, study):
        with patch(WAIT_FOR_JOBS) as wait:
            result = study.invoke(*QUICK, "--wait", "--polling-interval", "5")
        assert result.exit_code == 0, result.output
        wait.assert_called_once_with(["1001", "1002"], 5)
        assert "=== Waiting for jobs ===" in result.output

    def test_default_polling_interval(self, study):
        with patch(WAIT_FOR_JOBS) as wait:
            study.invoke(*QUICK, "--wait")
        assert wait.call_args.args[1] == 60

    @pytest.mark.parametrize("extra", [(), ("--wait", "--dry-run")])
    def test_does_not_wait_unless_asked_on_a_real_run(self, study, extra):
        with patch(WAIT_FOR_JOBS) as wait:
            result = study.invoke(*QUICK, *extra)
        assert result.exit_code == 0, result.output
        wait.assert_not_called()

    def test_nothing_submitted_means_nothing_to_wait_for(self, study):
        with patch.object(DAGExecutor, "execute", return_value=({"unzip": []}, {})), patch(WAIT_FOR_JOBS) as wait:
            result = study.invoke(*QUICK, "--wait")
        wait.assert_not_called()
        assert "No jobs to wait for" in result.output.splitlines()


# ---------------------------------------------------------------------------
# --resume
# ---------------------------------------------------------------------------

class TestResume:

    def test_checks_config_is_handed_to_the_dag(self, study):
        checks = study.config_dir / "results_check" / f"{PROJECT}_checks.yaml"
        checks.parent.mkdir(exist_ok=True)
        checks.write_text("{}", encoding="utf-8")
        with patch.object(DAGExecutor, "execute", return_value=({}, {})) as execute:
            result = study.invoke(*QUICK, "--resume")
        assert result.exit_code == 0, result.output
        assert execute.call_args.kwargs["resume"] is True
        assert execute.call_args.kwargs["checks_config_path"] == str(checks)
        assert f"[resume] Loaded output checks: {checks}" in result.output.splitlines()

    def test_missing_checks_config_warns_and_runs_everything(self, study):
        result = study.invoke(*QUICK, "--resume")
        assert result.exit_code == 0, result.output
        assert "Warning: --resume requested but no checks config found. Proceeding without skipping." in result.output
        assert len(study.sbatch.calls) == 2

    def test_without_resume_no_checks_config_is_looked_up(self, study):
        with patch.object(DAGExecutor, "execute", return_value=({}, {})) as execute, \
                patch("neuromaestro.pipeline.utils.output_checker.load_checks_config") as load:
            study.invoke(*QUICK)
        load.assert_not_called()
        assert execute.call_args.kwargs["resume"] is False
        assert execute.call_args.kwargs["checks_config_path"] is None


# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------

class TestPreflight:

    def test_passing_preflight_lets_the_run_continue(self, study):
        result = study.invoke("--skip-bids-validation")
        assert result.exit_code == 0, result.output
        assert "[preflight] All checks passed." in result.output.splitlines()
        assert len(study.sbatch.calls) == 2

    def test_failing_preflight_stops_before_anything_is_recorded_or_submitted(self, study):
        study.edit_project_config(lambda c: c["tasks"].update(not_a_task={}))
        result = study.invoke("--skip-bids-validation")
        assert result.exit_code == 1, result.output
        assert "tasks entry 'not_a_task' is not defined in global config.yaml" in result.output
        assert study.sbatch.calls == []
        assert study.records() == []

    def test_skip_preflight_ignores_the_failure(self, study):
        study.edit_project_config(lambda c: c["tasks"].update(not_a_task={}))
        result = study.invoke(*QUICK)
        assert result.exit_code == 0, result.output
        assert "[preflight]" not in result.output
        assert len(study.sbatch.calls) == 2


# ---------------------------------------------------------------------------
# BIDS validation runs only for tasks that read BIDS input
# ---------------------------------------------------------------------------

class TestBidsValidationTrigger:

    @pytest.mark.parametrize("prep, extra, expected", [
        (None, ("--bids-prep", "rest"), True),
        (None, ("--mriqc", "individual"), True),
        (None, ("--mriqc", "all"), True),
        (None, ("--mriqc", "group"), False),
        # --prep converts to BIDS first, so the input is not BIDS yet
        (_PREP, ("--bids-prep", "rest"), False),
        (None, ("--bids-prep", "rest", "--skip-bids-validation"), False),
    ])
    def test_when_validation_runs(self, study, prep, extra, expected):
        with patch.object(DAGExecutor, "execute", return_value=({}, {})), patch(BIDS_VALIDATION) as validate:
            result = study.invoke("--skip-preflight", "--dry-run", *extra, prep=prep)
        assert result.exit_code == 0, result.output
        if expected:
            validate.assert_called_once_with(str(study.root / "input"), str(study.root / "work" / PROJECT))
        else:
            validate.assert_not_called()


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------

class TestFailures:

    def test_dag_failure_is_recorded_and_re_raised(self, study):
        with patch.object(DAGExecutor, "execute", side_effect=RuntimeError("scheduler down")):
            result = study.invoke(*QUICK)
        assert result.exit_code == 1
        assert isinstance(result.exception, RuntimeError)
        start, end = study.records()
        assert (end["status"], end["error_msg"]) == ("FAILED", "scheduler down")

    @pytest.mark.parametrize("change, message", [
        (lambda c: c.update(prefix=""), "Error: 'prefix' not found in project config"),
        (lambda c: c.pop("database"), "Error: 'database.db_path' not found in project config"),
    ])
    def test_project_config_errors_exit_before_submission(self, study, change, message):
        study.edit_project_config(change)
        result = study.invoke(*QUICK)
        assert result.exit_code == 1
        assert message in result.output.splitlines()
        assert study.sbatch.calls == []

    def test_missing_container_dir_raises(self, study):
        study.edit_project_config(lambda c: c["envir_dir"].pop("container_dir"))
        result = study.invoke(*QUICK)
        assert isinstance(result.exception, ValueError)
        assert str(result.exception) == "container_dir not found in envir_dir config"
        assert study.records() == []

    def test_unknown_project_exits_1(self, study):
        from neuromaestro.pipeline.core import app
        with patch("subprocess.run", side_effect=study.sbatch):
            result = CliRunner().invoke(app, [
                "run", "--subjects", "001", "--input", str(study.root / "input"),
                "--output", str(study.root / "output"), "--work", str(study.root / "work"),
                "--project", "no_such_project", "--session", SESSION, "--prep", _PREP, *QUICK])
        assert result.exit_code == 1
        assert result.output.startswith("Error: ")
        assert "no_such_project" in result.output

    def test_no_tasks_exits_1(self, study):
        result = study.invoke(*QUICK, prep=None)
        assert result.exit_code == 1
        assert "Error: No tasks specified" in result.output.splitlines()
        assert study.records() == []
