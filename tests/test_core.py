"""
test_core.py

Tests for pipeline/core.py helper logic:
  - _parse_comma_list: comma expansion, whitespace trimming, empty-item filtering
  - parse_and_expand_tasks: correct keys are expanded; others pass through unchanged
  - CLI run command: exits with code 1 when --input directory is missing
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.conftest import MOCK_CONFIG

# core.py loads config.yaml at module level; patch the resulting variable
# for tests that invoke code paths touching it.
CORE_CONFIG_PATH = "neuro_pipeline.pipeline.core.config"


def _import_helpers():
    from neuro_pipeline.pipeline.core import _parse_comma_list, parse_and_expand_tasks
    return _parse_comma_list, parse_and_expand_tasks


# ---------------------------------------------------------------------------
# _resolve_config_dir
# ---------------------------------------------------------------------------

class TestResolveConfigDir:

    def _fn(self):
        from neuro_pipeline.pipeline.core import _resolve_config_dir
        return _resolve_config_dir

    def test_returns_explicit_arg(self, monkeypatch):
        monkeypatch.delenv("NEUROPIPE_CONFIG_DIR", raising=False)
        result = self._fn()("/some/path")
        assert result == "/some/path"

    def test_falls_back_to_env_var(self, monkeypatch):
        monkeypatch.setenv("NEUROPIPE_CONFIG_DIR", "/env/path")
        result = self._fn()(None)
        assert result == "/env/path"

    def test_cli_takes_precedence_over_env_var(self, monkeypatch):
        monkeypatch.setenv("NEUROPIPE_CONFIG_DIR", "/env/path")
        result = self._fn()("/cli/path")
        assert result == "/cli/path"

    def test_exits_when_neither_set(self, monkeypatch):
        import typer
        monkeypatch.delenv("NEUROPIPE_CONFIG_DIR", raising=False)
        with pytest.raises(typer.Exit):
            self._fn()(None)


# ---------------------------------------------------------------------------
# _parse_comma_list
# ---------------------------------------------------------------------------

class TestParseCommaList:

    def setup_method(self):
        self.fn, _ = _import_helpers()

    def test_single_comma_separated_string(self):
        assert self.fn(["cards,kidvid"]) == ["cards", "kidvid"]

    def test_already_individual_items(self):
        assert self.fn(["cards", "kidvid"]) == ["cards", "kidvid"]

    def test_mixed_input(self):
        assert self.fn(["cards,kidvid", "rest"]) == ["cards", "kidvid", "rest"]

    def test_strips_whitespace(self):
        assert self.fn(["cards, kidvid"]) == ["cards", "kidvid"]

    def test_filters_empty_items(self):
        assert self.fn(["cards,,kidvid"]) == ["cards", "kidvid"]

    def test_empty_list(self):
        assert self.fn([]) == []

    def test_single_item_no_comma(self):
        assert self.fn(["recon"]) == ["recon"]


# ---------------------------------------------------------------------------
# parse_and_expand_tasks
# ---------------------------------------------------------------------------

class TestParseAndExpandTasks:

    def setup_method(self):
        _, self.fn = _import_helpers()

    def _registry(self, return_value=None):
        reg = MagicMock()
        reg.expand_tasks.return_value = return_value or []
        return reg

    def test_intermed_comma_string_expanded(self):
        reg = self._registry()
        self.fn(reg, intermed=["volume,bfc"], bids_prep=None,
                bids_post=None, staged_prep=None, staged_post=None)
        assert reg.expand_tasks.call_args.kwargs["intermed"] == ["volume", "bfc"]

    def test_bids_prep_comma_string_expanded(self):
        reg = self._registry()
        self.fn(reg, intermed=None, bids_prep=["rest,dwi"],
                bids_post=None, staged_prep=None, staged_post=None)
        assert reg.expand_tasks.call_args.kwargs["bids_prep"] == ["rest", "dwi"]

    def test_staged_prep_comma_string_expanded(self):
        reg = self._registry()
        self.fn(reg, intermed=None, bids_prep=None,
                bids_post=None, staged_prep=["cards,kidvid"], staged_post=None)
        assert reg.expand_tasks.call_args.kwargs["staged_prep"] == ["cards", "kidvid"]

    def test_none_keys_passed_through_unchanged(self):
        reg = self._registry()
        self.fn(reg, intermed=None, bids_prep=None,
                bids_post=None, staged_prep=None, staged_post=None)
        kwargs = reg.expand_tasks.call_args.kwargs
        assert kwargs["intermed"] is None
        assert kwargs["bids_prep"] is None
        assert kwargs["staged_prep"] is None

    def test_non_list_kwargs_passed_through(self):
        reg = self._registry(["unzip"])
        self.fn(reg, prep="unzip", intermed=None,
                bids_prep=None, bids_post=None, staged_prep=None, staged_post=None)
        assert reg.expand_tasks.call_args.kwargs["prep"] == "unzip"

    def test_returns_registry_result(self):
        reg = self._registry(["recon", "volume"])
        result = self.fn(reg, intermed=None, bids_prep=None,
                         bids_post=None, staged_prep=None, staged_post=None)
        assert result == ["recon", "volume"]


# ---------------------------------------------------------------------------
# CLI — run command error paths
# ---------------------------------------------------------------------------

class TestCliRunErrors:

    def test_exits_when_config_dir_missing_and_no_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NEUROPIPE_CONFIG_DIR", raising=False)
        from typer.testing import CliRunner
        with patch(CORE_CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.core import app
        runner = CliRunner()
        result = runner.invoke(app, [
            "run",
            "--subjects", "001",
            "--input", str(tmp_path),
            "--output", str(tmp_path),
            "--work", str(tmp_path),
            "--project", "test_proj",
            "--session", "01",
        ])
        assert result.exit_code == 1
        assert "NEUROPIPE_CONFIG_DIR" in (result.output or "")

    def test_env_var_used_when_no_config_dir_flag(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROPIPE_CONFIG_DIR", str(tmp_path))
        from typer.testing import CliRunner
        with patch(CORE_CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.core import app
        runner = CliRunner()
        with patch("neuro_pipeline.pipeline.core.set_config_dir") as mock_set, \
             patch("neuro_pipeline.pipeline.core.get_config", return_value=MOCK_CONFIG):
            runner.invoke(app, [
                "run",
                "--subjects", "001",
                "--input", str(tmp_path / "nonexistent"),
                "--output", str(tmp_path),
                "--work", str(tmp_path),
                "--project", "test_proj",
                "--session", "01",
            ])
        mock_set.assert_called_once_with(str(tmp_path))

    def test_exits_when_input_dir_missing(self, tmp_path):
        from typer.testing import CliRunner
        with patch(CORE_CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.core import app
        runner = CliRunner()
        with patch("neuro_pipeline.pipeline.core.set_config_dir"), \
             patch("neuro_pipeline.pipeline.core.get_config", return_value=MOCK_CONFIG):
            result = runner.invoke(app, [
                "run",
                "--subjects", "001",
                "--input", str(tmp_path / "nonexistent"),
                "--output", str(tmp_path / "output"),
                "--work", str(tmp_path / "work"),
                "--project", "test_proj",
                "--session", "01",
                "--config-dir", str(tmp_path),
            ])
        assert result.exit_code == 1
        assert "not found" in (result.output or "").lower()


def _runner():
    from typer.testing import CliRunner
    with patch(CORE_CONFIG_PATH, MOCK_CONFIG):
        from neuro_pipeline.pipeline.core import app
    return CliRunner(), app


# ---------------------------------------------------------------------------
# CLI — merge-logs
# ---------------------------------------------------------------------------

class TestMergeLogsCmd:

    def test_no_json_dir_completes_successfully(self, tmp_path):
        runner, app = _runner()
        result = runner.invoke(app, ["merge-logs", str(tmp_path)])
        assert result.exit_code == 0

    def test_explicit_db_path_passed_through(self, tmp_path):
        runner, app = _runner()
        db_path = str(tmp_path / "custom.db")
        with patch("neuro_pipeline.pipeline.utils.merge_logs_create_db.merge_once") as mock_merge:
            runner.invoke(app, ["merge-logs", str(tmp_path), "--db-path", db_path])
        mock_merge.assert_called_once_with(str(tmp_path), db_path)


# ---------------------------------------------------------------------------
# CLI — force-rebuild
# ---------------------------------------------------------------------------

class TestForceRebuildCmd:

    def test_missing_json_dir_exits_1(self, tmp_path):
        runner, app = _runner()
        result = runner.invoke(app, ["force-rebuild", str(tmp_path)])
        assert result.exit_code == 1

    def test_success_reports_count_and_path(self, tmp_path):
        runner, app = _runner()
        new_db = str(tmp_path / "pipeline_jobs_rebuild_20260101.db")
        with patch("neuro_pipeline.pipeline.utils.merge_logs_create_db.rebuild_db",
                   return_value=(new_db, 7)):
            result = runner.invoke(app, ["force-rebuild", str(tmp_path)])
        assert result.exit_code == 0
        assert "7" in result.output
        assert new_db in result.output


# ---------------------------------------------------------------------------
# CLI — generate-report
# ---------------------------------------------------------------------------

class TestGenerateReportCmd:

    def test_missing_db_exits_1(self, tmp_path):
        runner, app = _runner()
        csv_path = tmp_path / "check_results.csv"
        csv_path.write_text("task,subject,status\n")
        result = runner.invoke(app, [
            "generate-report",
            "--db-path", str(tmp_path / "nonexistent.db"),
            "--project", "proj",
            "--check-results", str(csv_path),
        ])
        assert result.exit_code == 1

    def test_success_prints_report_path(self, tmp_path):
        runner, app = _runner()
        out_html = str(tmp_path / "report.html")
        with patch("neuro_pipeline.pipeline.utils.report_generator.generate_report",
                   return_value=out_html):
            result = runner.invoke(app, [
                "generate-report",
                "--db-path", str(tmp_path / "db.db"),
                "--project", "proj",
                "--check-results", str(tmp_path / "results.csv"),
            ])
        assert out_html in result.output


# ---------------------------------------------------------------------------
# CLI — check-outputs
# ---------------------------------------------------------------------------

class TestCheckOutputsCmd:

    def test_missing_checks_config_exits_1(self, tmp_path):
        runner, app = _runner()
        with patch("neuro_pipeline.pipeline.core.set_config_dir"):
            result = runner.invoke(app, [
                "check-outputs",
                "--project", "no_such_project_xyz",
                "--work", str(tmp_path),
                "--config-dir", str(tmp_path),
                "--session", "01",
            ])
        assert result.exit_code == 1

    def test_no_subjects_found_exits_1(self, tmp_path):
        runner, app = _runner()
        yaml_path = tmp_path / "proj_checks.yaml"
        yaml_path.write_text(
            "task1:\n  output_path: '{work_dir}'\n"
            "  required_files:\n    - 'file.txt'\n"
        )
        with patch("neuro_pipeline.pipeline.core.set_config_dir"), \
             patch("neuro_pipeline.pipeline.utils.output_checker.load_checks_config",
                   return_value=str(yaml_path)):
            result = runner.invoke(app, [
                "check-outputs",
                "--project", "proj",
                "--work", str(tmp_path),
                "--config-dir", str(tmp_path),
                "--session", "01",
            ])
        assert result.exit_code == 1

    def test_missing_session_exits_2(self, tmp_path):
        # --session is required: typer reports a usage error, not our exit(1)
        runner, app = _runner()
        with patch("neuro_pipeline.pipeline.core.set_config_dir"):
            result = runner.invoke(app, [
                "check-outputs",
                "--project", "proj",
                "--work", str(tmp_path),
                "--config-dir", str(tmp_path),
            ])
        assert result.exit_code == 2

    def test_blank_session_exits_1(self, tmp_path):
        runner, app = _runner()
        yaml_path = tmp_path / "proj_checks.yaml"
        yaml_path.write_text(
            "task1:\n  output_path: '{work_dir}'\n"
            "  required_files:\n    - 'file.txt'\n"
        )
        with patch("neuro_pipeline.pipeline.core.set_config_dir"), \
             patch("neuro_pipeline.pipeline.utils.output_checker.load_checks_config",
                   return_value=str(yaml_path)):
            result = runner.invoke(app, [
                "check-outputs",
                "--project", "proj",
                "--work", str(tmp_path),
                "--config-dir", str(tmp_path),
                "--session", " , ",
            ])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# CLI — detect-subjects
# ---------------------------------------------------------------------------

class TestDetectSubjectsCmd:

    def test_missing_input_dir_exits_1(self, tmp_path):
        runner, app = _runner()
        result = runner.invoke(app, ["detect-subjects", str(tmp_path / "nonexistent")])
        assert result.exit_code == 1

    def test_prints_subjects_to_stdout(self, tmp_path):
        runner, app = _runner()
        (tmp_path / "sub-001").mkdir()
        (tmp_path / "sub-002").mkdir()
        result = runner.invoke(app, ["detect-subjects", str(tmp_path)])
        assert result.exit_code == 0
        assert "001" in result.output

    def test_saves_subjects_to_file(self, tmp_path):
        runner, app = _runner()
        (tmp_path / "sub-001").mkdir()
        out_file = str(tmp_path / "subjects.txt")
        result = runner.invoke(app, ["detect-subjects", str(tmp_path), "--output", out_file])
        assert result.exit_code == 0
        from pathlib import Path
        assert Path(out_file).exists()


# ---------------------------------------------------------------------------
# CLI — generate-config / generate-checks
# ---------------------------------------------------------------------------

class TestGenerateConfigCmd:

    def test_generate_config_delegates_to_utility(self, tmp_path):
        runner, app = _runner()
        with patch("neuro_pipeline.pipeline.core.set_config_dir"), \
             patch("neuro_pipeline.pipeline.utils.generate_project_config.generate_project_config") as mock_fn:
            runner.invoke(app, [
                "generate-config", "my_study",
                "--config-dir", str(tmp_path),
                "--output-dir", str(tmp_path),
            ])
        mock_fn.assert_called_once()

    def test_generate_checks_delegates_to_utility(self, tmp_path):
        runner, app = _runner()
        with patch("neuro_pipeline.pipeline.core.set_config_dir"), \
             patch("neuro_pipeline.pipeline.utils.generate_results_check.generate_results_check") as mock_fn:
            runner.invoke(app, [
                "generate-checks", "my_study",
                "--config-dir", str(tmp_path),
                "--output-dir", str(tmp_path),
            ])
        mock_fn.assert_called_once()


# ---------------------------------------------------------------------------
# CLI — init
# ---------------------------------------------------------------------------

class TestInitCmd:

    def test_creates_output_dir_and_prints_next_steps(self, tmp_path):
        runner, app = _runner()
        result = runner.invoke(app, ["init", str(tmp_path / "study")])
        assert result.exit_code == 0
        assert "Initialised at" in result.output

    def test_prints_env_var_tip(self, tmp_path):
        runner, app = _runner()
        result = runner.invoke(app, ["init", str(tmp_path / "study")])
        assert result.exit_code == 0
        assert "NEUROPIPE_CONFIG_DIR" in result.output



# ---------------------------------------------------------------------------
# generate-config template must agree with the merge/rebuild auto-detect path
# ---------------------------------------------------------------------------

class TestGeneratedProjectConfigTemplate:
    """The template shipped db_path under log/ while every real project config
    and the merge-logs / force-rebuild auto-detect use database/. A freshly
    generated project could not be found by `neuropipe merge-logs <work_dir>`.
    """

    @staticmethod
    def _generate(tmp_path):
        import yaml
        from neuro_pipeline.pipeline.utils.generate_project_config import generate_project_config
        generate_project_config("proj", str(tmp_path))
        return yaml.safe_load((tmp_path / "proj_config.yaml").read_text(encoding="utf-8"))

    def test_db_path_uses_database_subdir(self, tmp_path):
        cfg = self._generate(tmp_path)
        assert cfg["database"]["db_path"] == "$WORK_DIR/database/pipeline_jobs.db"

    def test_db_path_matches_merge_once_autodetect(self, tmp_path):
        import os
        cfg = self._generate(tmp_path)
        generated = cfg["database"]["db_path"].replace("$WORK_DIR", "/work")
        autodetected = os.path.join("/work", "database", "pipeline_jobs.db")
        assert Path(generated) == Path(autodetected)

    def test_db_path_placeholder_is_resolvable(self, tmp_path):
        cfg = self._generate(tmp_path)
        resolved = cfg["database"]["db_path"].replace("$WORK_DIR", "/work")
        assert "$WORK_DIR" not in resolved


class TestGeneratorsDoNotOverwrite:
    """Regenerating over a tuned config used to silently discard it."""

    @staticmethod
    def _gen_config(tmp_path, **kw):
        from neuro_pipeline.pipeline.utils.generate_project_config import generate_project_config
        return generate_project_config("proj", str(tmp_path), **kw)

    @staticmethod
    def _gen_checks(tmp_path, **kw):
        from neuro_pipeline.pipeline.utils.generate_results_check import generate_results_check
        return generate_results_check("proj", str(tmp_path), **kw)

    def test_project_config_refuses_to_overwrite(self, tmp_path):
        self._gen_config(tmp_path)
        with pytest.raises(FileExistsError, match="already exists"):
            self._gen_config(tmp_path)

    def test_project_config_force_overwrites(self, tmp_path):
        self._gen_config(tmp_path)
        (tmp_path / "proj_config.yaml").write_text("edited: true\n", encoding="utf-8")
        self._gen_config(tmp_path, force=True)
        assert "edited" not in (tmp_path / "proj_config.yaml").read_text(encoding="utf-8")

    def test_project_config_content_preserved_when_refused(self, tmp_path):
        self._gen_config(tmp_path)
        (tmp_path / "proj_config.yaml").write_text("edited: true\n", encoding="utf-8")
        with pytest.raises(FileExistsError):
            self._gen_config(tmp_path)
        assert (tmp_path / "proj_config.yaml").read_text(encoding="utf-8") == "edited: true\n"

    def test_checks_refuses_to_overwrite(self, tmp_path):
        self._gen_checks(tmp_path)
        with pytest.raises(FileExistsError, match="already exists"):
            self._gen_checks(tmp_path)

    def test_checks_force_overwrites(self, tmp_path):
        self._gen_checks(tmp_path)
        (tmp_path / "proj_checks.yaml").write_text("edited: true\n", encoding="utf-8")
        self._gen_checks(tmp_path, force=True)
        assert "edited" not in (tmp_path / "proj_checks.yaml").read_text(encoding="utf-8")

    def test_cli_generate_config_exits_1_on_existing(self, tmp_path):
        runner, app = _runner()
        self._gen_config(tmp_path)
        with patch("neuro_pipeline.pipeline.core.set_config_dir"):
            result = runner.invoke(app, [
                "generate-config", "proj",
                "--output-dir", str(tmp_path),
                "--config-dir", str(tmp_path),
            ])
        assert result.exit_code == 1

    def test_cli_generate_config_force_succeeds(self, tmp_path):
        runner, app = _runner()
        self._gen_config(tmp_path)
        with patch("neuro_pipeline.pipeline.core.set_config_dir"):
            result = runner.invoke(app, [
                "generate-config", "proj",
                "--output-dir", str(tmp_path),
                "--config-dir", str(tmp_path),
                "--force",
            ])
        assert result.exit_code == 0
