"""
test_job_monitor_callbacks.py

Unit tests for the job monitor callbacks:
  - _render_check_table
  - merge_logs_callback
  - force_rebuild_callback
  - generate_report_callback
  - run_output_check_callback
  - export_check_csv_callback
  - execute_sql_query_callback
  - export_csv_callback

"""

import os
import pytest
import sqlite3
import subprocess
import yaml
import pandas as pd
from pathlib import Path
from unittest.mock import patch, MagicMock

import dash_bootstrap_components as dbc
from dash import html


class FakeApp:
    """Minimal Dash app stub that records registered callbacks by function name."""

    def __init__(self):
        self._callbacks = {}

    def callback(self, *args, **kwargs):
        def decorator(fn):
            self._callbacks[fn.__name__] = fn
            return fn
        return decorator

    def get(self, name):
        return self._callbacks[name]


@pytest.fixture(scope="module")
def callbacks():
    """Register all job monitor callbacks once and return the FakeApp."""
    fake_app = FakeApp()
    from neuromaestro.interface.callbacks.job_monitor_callbacks import register_job_monitor_callbacks
    register_job_monitor_callbacks(fake_app)
    return fake_app


# ---------------------------------------------------------------------------
# _render_check_table
# ---------------------------------------------------------------------------

class TestRenderCheckTable:

    @pytest.fixture(autouse=True)
    def _import(self):
        from neuromaestro.interface.callbacks.job_monitor_callbacks import _render_check_table
        self.render = _render_check_table

    def _make_df(self, rows):
        return pd.DataFrame(rows)

    def test_returns_html_table(self):
        df = self._make_df([{"subject": "001", "status": "PASS"}])
        result = self.render(df)
        assert isinstance(result, html.Table)

    def test_pass_row_gets_green_background(self):
        df = self._make_df([{"subject": "001", "status": "PASS"}])
        table = self.render(df)
        tbody = table.children[1]
        row = tbody.children[0]
        # normalised so the assertion survives a purely cosmetic respacing
        bg = row.style.get("backgroundColor", "").replace(" ", "")
        assert "40,167,69" in bg

    def test_fail_row_gets_red_background(self):
        df = self._make_df([{"subject": "002", "status": "FAIL - file not found"}])
        table = self.render(df)
        tbody = table.children[1]
        row = tbody.children[0]
        bg = row.style.get("backgroundColor", "").replace(" ", "")
        assert "220,53,69" in bg

    def test_mixed_rows(self):
        df = self._make_df([
            {"subject": "001", "status": "PASS"},
            {"subject": "002", "status": "FAIL - too small"},
        ])
        table = self.render(df)
        tbody = table.children[1]
        assert len(tbody.children) == 2

    def test_column_headers_match_df(self):
        df = self._make_df([{"task": "t", "subject": "001", "status": "PASS"}])
        table = self.render(df)
        thead = table.children[0]
        header_row = thead.children
        header_texts = [th.children for th in header_row.children]
        assert "task" in header_texts
        assert "subject" in header_texts
        assert "status" in header_texts


# ---------------------------------------------------------------------------
# merge_logs_callback
# ---------------------------------------------------------------------------

class TestMergeLogsCallback:

    def test_empty_work_dir_returns_warning(self, callbacks):
        fn = callbacks.get("merge_logs_callback")
        result = fn(n_clicks=1, work_dir="", db_path="")
        assert isinstance(result, dbc.Alert)
        assert result.color == "warning"

    def test_nonexistent_work_dir_returns_danger(self, callbacks, tmp_path):
        fn = callbacks.get("merge_logs_callback")
        result = fn(n_clicks=1, work_dir=str(tmp_path / "does_not_exist"), db_path="")
        assert isinstance(result, dbc.Alert)
        assert result.color == "danger"

    def test_successful_sync(self, callbacks, tmp_path):
        fn = callbacks.get("merge_logs_callback")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Merged 5 records."

        with patch("neuromaestro.interface.callbacks.job_monitor_callbacks.subprocess.run",
                   return_value=mock_result) as mock_run:
            result = fn(n_clicks=1, work_dir=str(tmp_path), db_path="")

        assert isinstance(result, dbc.Alert)
        assert result.color == "success"
        assert "Merged 5 records." in result.children
        assert mock_run.call_args.args[0] == ["neuromaestro", "merge-logs", str(tmp_path)]
        # the mock returns str output regardless, so the decoding flags are pinned here
        assert mock_run.call_args.kwargs == {"capture_output": True, "text": True, "timeout": 600}

    def test_db_path_is_forwarded(self, callbacks, tmp_path):
        fn = callbacks.get("merge_logs_callback")
        with patch("neuromaestro.interface.callbacks.job_monitor_callbacks.subprocess.run",
                   return_value=MagicMock(returncode=0, stdout="")) as mock_run:
            fn(n_clicks=1, work_dir=str(tmp_path), db_path=" /db/jobs.db ")
        assert mock_run.call_args.args[0][-2:] == ["--db-path", "/db/jobs.db"]

    def test_failed_command_returns_danger(self, callbacks, tmp_path):
        fn = callbacks.get("merge_logs_callback")
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "merge failed"
        mock_result.stdout = ""

        with patch("neuromaestro.interface.callbacks.job_monitor_callbacks.subprocess.run",
                   return_value=mock_result):
            result = fn(n_clicks=1, work_dir=str(tmp_path), db_path="")

        assert isinstance(result, dbc.Alert)
        assert result.color == "danger"
        assert result.children == "merge-logs failed: merge failed"

    def test_timeout_returns_danger(self, callbacks, tmp_path):
        import subprocess
        fn = callbacks.get("merge_logs_callback")

        with patch("neuromaestro.interface.callbacks.job_monitor_callbacks.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="neuromaestro", timeout=120)):
            result = fn(n_clicks=1, work_dir=str(tmp_path), db_path="")

        assert isinstance(result, dbc.Alert)
        assert result.color == "danger"
        assert result.children == "merge-logs timed out after 600 seconds."

    def test_neuromaestro_not_found_returns_danger(self, callbacks, tmp_path):
        fn = callbacks.get("merge_logs_callback")

        with patch("neuromaestro.interface.callbacks.job_monitor_callbacks.subprocess.run",
                   side_effect=FileNotFoundError):
            result = fn(n_clicks=1, work_dir=str(tmp_path), db_path="")

        assert isinstance(result, dbc.Alert)
        assert result.color == "danger"
        assert result.children == (
            "neuromaestro command not found. Make sure the package is installed in the active environment.")

    def test_other_launch_error_is_reported(self, callbacks, tmp_path):
        with patch(SUBPROCESS_RUN, side_effect=OSError("disk full")):
            result = callbacks.get("merge_logs_callback")(n_clicks=1, work_dir=str(tmp_path), db_path="")
        assert result.color == "danger"
        assert result.children == "Error: disk full"


# ---------------------------------------------------------------------------
# force_rebuild_callback
# ---------------------------------------------------------------------------

SUBPROCESS_RUN = "neuromaestro.interface.callbacks.job_monitor_callbacks.subprocess.run"


class TestForceRebuildCallback:

    def test_empty_work_dir_returns_warning(self, callbacks):
        with patch(SUBPROCESS_RUN) as mock_run:
            result = callbacks.get("force_rebuild_callback")(n_clicks=1, work_dir="", db_path="")
        assert result.color == "warning"
        assert result.children == "Please enter the work directory."
        mock_run.assert_not_called()

    def test_missing_work_dir_returns_danger(self, callbacks, tmp_path):
        missing = str(tmp_path / "does_not_exist")
        with patch(SUBPROCESS_RUN) as mock_run:
            result = callbacks.get("force_rebuild_callback")(n_clicks=1, work_dir=missing, db_path="")
        assert result.color == "danger"
        assert result.children == f"Directory not found: {missing}"
        mock_run.assert_not_called()

    def test_successful_rebuild(self, callbacks, tmp_path):
        with patch(SUBPROCESS_RUN, return_value=MagicMock(returncode=0, stdout="Rebuilt 3 tables.\n")) as mock_run:
            result = callbacks.get("force_rebuild_callback")(n_clicks=1, work_dir=str(tmp_path), db_path="")
        assert mock_run.call_args.args[0] == ["neuromaestro", "force-rebuild", str(tmp_path)]
        assert mock_run.call_args.kwargs == {"capture_output": True, "text": True, "timeout": 300}
        assert result.color == "success"
        assert result.children[0].children == "Rebuild complete. "
        assert result.children[1] == "Rebuilt 3 tables."

    def test_empty_stdout_gets_a_default_message(self, callbacks, tmp_path):
        with patch(SUBPROCESS_RUN, return_value=MagicMock(returncode=0, stdout="")):
            result = callbacks.get("force_rebuild_callback")(n_clicks=1, work_dir=str(tmp_path), db_path="")
        assert result.children[1] == "Rebuild complete."

    @pytest.mark.parametrize("db_path, tail", [
        (" /db/jobs.db ", ["--db-path", "/db/jobs.db"]),
        ("   ", []),
        (None, []),
    ])
    def test_db_path_is_forwarded_only_when_set(self, callbacks, tmp_path, db_path, tail):
        with patch(SUBPROCESS_RUN, return_value=MagicMock(returncode=0, stdout="")) as mock_run:
            callbacks.get("force_rebuild_callback")(n_clicks=1, work_dir=str(tmp_path), db_path=db_path)
        assert mock_run.call_args.args[0] == ["neuromaestro", "force-rebuild", str(tmp_path)] + tail

    @pytest.mark.parametrize("stderr, stdout, shown", [
        ("database is locked\n", "partial", "database is locked"),
        ("", "partial\n", "partial"),
        ("", "", "Unknown error."),
    ])
    def test_failure_shows_stderr_then_stdout(self, callbacks, tmp_path, stderr, stdout, shown):
        with patch(SUBPROCESS_RUN, return_value=MagicMock(returncode=1, stderr=stderr, stdout=stdout)):
            result = callbacks.get("force_rebuild_callback")(n_clicks=1, work_dir=str(tmp_path), db_path="")
        assert result.color == "danger"
        assert result.children == f"force-rebuild failed: {shown}"

    @pytest.mark.parametrize("error, shown", [
        (subprocess.TimeoutExpired(cmd="neuromaestro", timeout=300),
         "force-rebuild timed out after 300 seconds."),
        (FileNotFoundError(),
         "neuromaestro command not found. Make sure the package is installed in the active environment."),
        (OSError("disk full"), "Error: disk full"),
    ])
    def test_launch_errors_are_reported(self, callbacks, tmp_path, error, shown):
        with patch(SUBPROCESS_RUN, side_effect=error):
            result = callbacks.get("force_rebuild_callback")(n_clicks=1, work_dir=str(tmp_path), db_path="")
        assert result.color == "danger"
        assert result.children == shown


# ---------------------------------------------------------------------------
# generate_report_callback
# ---------------------------------------------------------------------------

GENERATE_REPORT = "neuromaestro.pipeline.utils.report_generator.generate_report"


class TestGenerateReportCallback:

    @pytest.fixture
    def db(self, tmp_path):
        path = tmp_path / "jobs.db"
        path.touch()
        return str(path)

    @pytest.mark.parametrize("db_path, project", [("", "proj"), (None, "proj"), ("x.db", ""), ("x.db", None)])
    def test_db_and_project_are_required(self, callbacks, db_path, project):
        with patch(GENERATE_REPORT) as gen:
            result = callbacks.get("generate_report_callback")(1, db_path, project, None, "checks.csv", None)
        assert result.color == "warning"
        assert result.children == "Database path and project name are required."
        gen.assert_not_called()

    @pytest.mark.parametrize("check_results", ["", "   ", None])
    def test_check_results_are_required(self, callbacks, db, check_results):
        with patch(GENERATE_REPORT) as gen:
            result = callbacks.get("generate_report_callback")(1, db, "proj", None, check_results, None)
        assert result.color == "warning"
        assert result.children == "Check Results CSV is required."
        gen.assert_not_called()

    def test_missing_db_returns_danger(self, callbacks, tmp_path):
        missing = str(tmp_path / "missing.db")
        with patch(GENERATE_REPORT) as gen:
            result = callbacks.get("generate_report_callback")(1, missing, "proj", None, "checks.csv", None)
        assert result.color == "danger"
        assert result.children == f"Database not found: {missing}"
        gen.assert_not_called()

    def test_fields_are_stripped_and_passed_by_name(self, callbacks, db):
        # autospec: a renamed generate_report parameter fails here instead of at click time
        with patch(GENERATE_REPORT, autospec=True, return_value="/out/report.html") as gen:
            result = callbacks.get("generate_report_callback")(
                1, db, " proj ", " ses-01 ", " /in/checks.csv ", " /out/report.html ")
        gen.assert_called_once_with(
            db_path=db, project_name="proj", check_results_path="/in/checks.csv",
            output_path="/out/report.html", session="ses-01",
        )
        assert result.color == "success"
        assert result.children[0] == "Report saved: "
        assert result.children[1].children == "/out/report.html"

    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_blank_optional_fields_become_none(self, callbacks, db, blank):
        with patch(GENERATE_REPORT, autospec=True, return_value="r.html") as gen:
            callbacks.get("generate_report_callback")(1, db, "proj", blank, "checks.csv", blank)
        assert gen.call_args.kwargs["output_path"] is None
        assert gen.call_args.kwargs["session"] is None

    @pytest.mark.parametrize("error, shown", [
        (ValueError("no jobs for project proj"), "no jobs for project proj"),
        (FileNotFoundError("checks.csv"), "checks.csv"),
        (RuntimeError("boom"), "Error generating report: boom"),
    ])
    def test_errors_are_reported(self, callbacks, db, error, shown):
        with patch(GENERATE_REPORT, side_effect=error):
            result = callbacks.get("generate_report_callback")(1, db, "proj", None, "checks.csv", None)
        assert result.color == "danger"
        assert result.children == shown


# ---------------------------------------------------------------------------
# run_output_check_callback
# ---------------------------------------------------------------------------

class TestRunOutputCheckCallback:

    def test_missing_project_returns_warning(self, callbacks):
        fn = callbacks.get("run_output_check_callback")
        result = fn(1, project="", work_dir="/work", subjects_raw="001",
                    task_filter="", session="01", prefix="sub-")
        assert isinstance(result, dbc.Alert)
        assert result.color == "warning"

    def test_missing_work_dir_returns_warning(self, callbacks):
        fn = callbacks.get("run_output_check_callback")
        result = fn(1, project="myproject", work_dir="", subjects_raw="001",
                    task_filter="", session="01", prefix="sub-")
        assert isinstance(result, dbc.Alert)
        assert result.color == "warning"

    def test_missing_subjects_returns_warning(self, callbacks, tmp_path):
        # Blank subject list falls back to auto-detection; an empty work dir
        # yields nothing, so the user gets a warning rather than a silent run.
        fn = callbacks.get("run_output_check_callback")
        result = fn(1, project="myproject", work_dir=str(tmp_path), subjects_raw="",
                    task_filter="", session="01", prefix="sub-")
        assert isinstance(result, dbc.Alert)
        assert result.color == "warning"
        assert "auto-detected" in str(result.children)

    def test_blank_subjects_uses_auto_detection(self, callbacks, tmp_path):
        fn = callbacks.get("run_output_check_callback")
        fake_df = pd.DataFrame([
            {"task": "t", "subject": "007", "session": "01", "status": "PASS"},
        ])
        # detect_subjects is imported inside the callback, so the source module
        # is the only patch point; there is no module-level name to override.
        with patch("neuromaestro.pipeline.utils.detect_subjects.detect_subjects",
                   return_value=["007"]), \
             patch("neuromaestro.interface.callbacks.job_monitor_callbacks.load_checks_config",
                   return_value="/fake/path.yaml"), \
             patch("neuromaestro.interface.callbacks.job_monitor_callbacks.run_output_checks",
                   return_value=(fake_df, ["t"], [])) as mock_run:
            fn(1, project="myproject", work_dir=str(tmp_path), subjects_raw="",
               task_filter="", session="01", prefix="sub-")

        assert mock_run.call_args.kwargs["subjects"] == ["007"]

    def test_checks_config_not_found_returns_danger(self, callbacks, tmp_path):
        fn = callbacks.get("run_output_check_callback")
        with patch(
            "neuromaestro.interface.callbacks.job_monitor_callbacks.load_checks_config",
            side_effect=FileNotFoundError("no checks file"),
        ):
            result = fn(1, project="ghost", work_dir=str(tmp_path),
                        subjects_raw="001", task_filter="", session="01", prefix="sub-")
        assert isinstance(result, dbc.Alert)
        assert result.color == "danger"

    def test_successful_run_returns_div_with_summary(self, callbacks, tmp_path):
        fn = callbacks.get("run_output_check_callback")
        fake_df = pd.DataFrame([
            {"task": "my_task", "subject": "001", "session": "01",
             "check_type": "required_files", "pattern": "*.html",
             "expected": "exists", "actual": 1, "status": "PASS"},
            {"task": "my_task", "subject": "002", "session": "01",
             "check_type": "required_files", "pattern": "*.html",
             "expected": "exists", "actual": 0, "status": "FAIL - file not found"},
            {"task": "my_task", "subject": "003", "session": "01",
             "check_type": "required_files", "pattern": "*.html",
             "expected": "exists", "actual": 1, "status": "PASS"},
        ])
        with patch("neuromaestro.interface.callbacks.job_monitor_callbacks.load_checks_config",
                   return_value="/fake/path.yaml"), \
             patch("neuromaestro.interface.callbacks.job_monitor_callbacks.run_output_checks",
                   return_value=(fake_df, ["my_task"], [])):
            result = fn(1, project="myproject", work_dir=str(tmp_path),
                        subjects_raw="001,002,003", task_filter="", session="01", prefix="sub-")

        assert isinstance(result, html.Div)
        # unequal counts, so swapping the two cannot go unnoticed
        counts, failures = result.children[0].children
        assert counts.children == "2 checks passed, 1 checks failed. "
        assert failures == "Subjects with failures: 002"

    def test_all_pass_summary_is_success_color(self, callbacks, tmp_path):
        fn = callbacks.get("run_output_check_callback")
        fake_df = pd.DataFrame([
            {"task": "t", "subject": "001", "session": "01",
             "check_type": "required_files", "pattern": "*.html",
             "expected": "exists", "actual": 1, "status": "PASS"},
        ])
        with patch("neuromaestro.interface.callbacks.job_monitor_callbacks.load_checks_config",
                   return_value="/fake/path.yaml"), \
             patch("neuromaestro.interface.callbacks.job_monitor_callbacks.run_output_checks",
                   return_value=(fake_df, ["t"], [])):
            result = fn(1, project="myproject", work_dir=str(tmp_path),
                        subjects_raw="001", task_filter="", session="01", prefix="sub-")

        summary_alert = result.children[0]
        assert summary_alert.color == "success"

    def test_any_fail_summary_is_warning_color(self, callbacks, tmp_path):
        fn = callbacks.get("run_output_check_callback")
        fake_df = pd.DataFrame([
            {"task": "t", "subject": "001", "session": "01",
             "check_type": "required_files", "pattern": "*.html",
             "expected": "exists", "actual": 0, "status": "FAIL - file not found"},
        ])
        with patch("neuromaestro.interface.callbacks.job_monitor_callbacks.load_checks_config",
                   return_value="/fake/path.yaml"), \
             patch("neuromaestro.interface.callbacks.job_monitor_callbacks.run_output_checks",
                   return_value=(fake_df, ["t"], [])):
            result = fn(1, project="myproject", work_dir=str(tmp_path),
                        subjects_raw="001", task_filter="", session="01", prefix="sub-")

        summary_alert = result.children[0]
        assert summary_alert.color == "warning"

    def test_task_filter_passed_correctly(self, callbacks, tmp_path):
        fn = callbacks.get("run_output_check_callback")
        fake_df = pd.DataFrame([
            {"task": "specific_task", "subject": "001", "session": "01",
             "check_type": "required_files", "pattern": "*.html",
             "expected": "exists", "actual": 1, "status": "PASS"},
        ])
        with patch("neuromaestro.interface.callbacks.job_monitor_callbacks.load_checks_config",
                   return_value="/fake/path.yaml"), \
             patch("neuromaestro.interface.callbacks.job_monitor_callbacks.run_output_checks",
                   return_value=(fake_df, ["specific_task"], [])) as mock_run:
            fn(1, project="myproject", work_dir=str(tmp_path),
               subjects_raw="001,002", task_filter="specific_task",
               session="01", prefix="sub-")

        kwargs = mock_run.call_args.kwargs
        assert kwargs["tasks"] == ["specific_task"]
        assert kwargs["subjects"] == ["001", "002"]
        assert kwargs["sessions"] == ["01"]


# ---------------------------------------------------------------------------
# export_check_csv_callback
# ---------------------------------------------------------------------------

class TestExportCheckCsvCallback:

    def test_missing_inputs_returns_warning(self, callbacks):
        fn = callbacks.get("export_check_csv_callback")
        result = fn(1, project="", work_dir="/work", subjects_raw="001",
                    task_filter="", session="01", prefix="sub-")
        assert isinstance(result, dbc.Alert)
        assert result.color == "warning"

    def test_successful_export_returns_success(self, callbacks, tmp_path):
        fn = callbacks.get("export_check_csv_callback")
        fake_csv = str(tmp_path / "check_results_20250101.csv")
        fake_df = pd.DataFrame([
            {"task": "t", "subject": "001", "status": "PASS"},
        ])
        # OutputChecker is still used directly, but only to write the CSV
        mock_checker = MagicMock()
        mock_checker.save_csv.return_value = fake_csv

        with patch("neuromaestro.interface.callbacks.job_monitor_callbacks.load_checks_config",
                   return_value="/fake/path.yaml"), \
             patch("neuromaestro.interface.callbacks.job_monitor_callbacks.run_output_checks",
                   return_value=(fake_df, ["t"], [])), \
             patch("neuromaestro.interface.callbacks.job_monitor_callbacks.OutputChecker",
                   return_value=mock_checker):
            result = fn(1, project="myproject", work_dir=str(tmp_path),
                        subjects_raw="001", task_filter="", session="01", prefix="sub-")

        assert isinstance(result, dbc.Alert)
        assert result.color == "success"
        assert fake_csv in str(result.children)

    def test_file_not_found_returns_danger(self, callbacks, tmp_path):
        fn = callbacks.get("export_check_csv_callback")

        with patch("neuromaestro.interface.callbacks.job_monitor_callbacks.load_checks_config",
                   side_effect=FileNotFoundError("no file")):
            result = fn(1, project="ghost", work_dir=str(tmp_path),
                        subjects_raw="001", task_filter="", session="01", prefix="sub-")

        assert isinstance(result, dbc.Alert)
        assert result.color == "danger"

    def test_exception_while_running_checks_returns_danger(self, callbacks, tmp_path):
        fn = callbacks.get("export_check_csv_callback")

        with patch("neuromaestro.interface.callbacks.job_monitor_callbacks.load_checks_config",
                   return_value="/fake/path.yaml"), \
             patch("neuromaestro.interface.callbacks.job_monitor_callbacks.run_output_checks",
                   side_effect=RuntimeError("checks blew up")):
            result = fn(1, project="myproject", work_dir=str(tmp_path),
                        subjects_raw="001", task_filter="", session="01", prefix="sub-")

        assert isinstance(result, dbc.Alert)
        assert result.color == "danger"
        assert "checks blew up" in str(result.children)

    def test_separator_only_subjects_returns_warning(self, callbacks, tmp_path):
        # run_output_check_callback already guarded this; the export path did not
        fn = callbacks.get("export_check_csv_callback")
        with patch("neuromaestro.interface.callbacks.job_monitor_callbacks.OutputChecker") as mock_cls:
            result = fn(1, project="myproject", work_dir=str(tmp_path),
                        subjects_raw=" , ", task_filter="", session="01", prefix="sub-")

        assert isinstance(result, dbc.Alert)
        assert result.color == "warning"
        mock_cls.assert_not_called()

    def test_exception_while_writing_csv_returns_danger(self, callbacks, tmp_path):
        fn = callbacks.get("export_check_csv_callback")
        fake_df = pd.DataFrame([{"task": "t", "subject": "001", "status": "PASS"}])
        mock_checker = MagicMock()
        mock_checker.save_csv.side_effect = OSError("disk full")

        with patch("neuromaestro.interface.callbacks.job_monitor_callbacks.load_checks_config",
                   return_value="/fake/path.yaml"), \
             patch("neuromaestro.interface.callbacks.job_monitor_callbacks.run_output_checks",
                   return_value=(fake_df, ["t"], [])), \
             patch("neuromaestro.interface.callbacks.job_monitor_callbacks.OutputChecker",
                   return_value=mock_checker):
            result = fn(1, project="myproject", work_dir=str(tmp_path),
                        subjects_raw="001", task_filter="", session="01", prefix="sub-")

        assert isinstance(result, dbc.Alert)
        assert result.color == "danger"
        assert "disk full" in str(result.children)


# ---------------------------------------------------------------------------
# Session is required for output checks
# ---------------------------------------------------------------------------

class TestParseSessions:
    """A blank session used to fall back to "*", which globs every session at
    once. A required file present in any one session then satisfied the check,
    so sessions that were entirely missing were reported as PASS.
    """

    @staticmethod
    def _parse(value):
        from neuromaestro.interface.callbacks.job_monitor_callbacks import _parse_sessions
        return _parse_sessions(value)

    def test_single_session_parsed(self):
        sessions, err = self._parse("01")
        assert sessions == ["01"] and err is None

    def test_comma_separated_parsed(self):
        sessions, err = self._parse("01,02")
        assert sessions == ["01", "02"] and err is None

    def test_whitespace_stripped(self):
        sessions, err = self._parse(" 01 , 02 ")
        assert sessions == ["01", "02"] and err is None

    def test_blank_returns_warning(self):
        sessions, err = self._parse("")
        assert sessions is None
        assert isinstance(err, dbc.Alert) and err.color == "warning"

    def test_none_returns_warning(self):
        sessions, err = self._parse(None)
        assert sessions is None and isinstance(err, dbc.Alert)

    def test_only_separators_returns_warning(self):
        sessions, err = self._parse(" , ")
        assert sessions is None and isinstance(err, dbc.Alert)

    def test_no_wildcard_fallback(self):
        # The regression: "*" must never be produced implicitly
        for value in ("", None, "  ", ","):
            sessions, _ = self._parse(value)
            assert sessions is None, f"{value!r} must not silently become a wildcard"


class TestOutputCheckRequiresSession:

    def test_run_check_blank_session_warns(self, callbacks, tmp_path):
        fn = callbacks.get("run_output_check_callback")
        result = fn(1, project="myproject", work_dir=str(tmp_path),
                    subjects_raw="001", task_filter="", session="", prefix="sub-")
        assert isinstance(result, dbc.Alert)
        assert result.color == "warning"

    def test_export_csv_blank_session_warns(self, callbacks, tmp_path):
        fn = callbacks.get("export_check_csv_callback")
        result = fn(1, project="myproject", work_dir=str(tmp_path),
                    subjects_raw="001", task_filter="", session="", prefix="sub-")
        assert isinstance(result, dbc.Alert)
        assert result.color == "warning"

    def test_blank_session_does_not_reach_the_checker(self, callbacks, tmp_path):
        fn = callbacks.get("run_output_check_callback")
        # the checks config must resolve, or the callback stops before the checker either way
        with patch("neuromaestro.interface.callbacks.job_monitor_callbacks.load_checks_config",
                   return_value="/fake/path.yaml"), \
             patch("neuromaestro.interface.callbacks.job_monitor_callbacks.run_output_checks") as mock_run:
            fn(1, project="myproject", work_dir=str(tmp_path),
               subjects_raw="001", task_filter="", session="", prefix="sub-")
        mock_run.assert_not_called()


class TestWrapperInspectorShowsProvenance:
    """wrapper_scripts stores no project or session, so the inspector had no
    way to say which run a wrapper came from. Both are joined in from the
    execution it belongs to.
    """

    @staticmethod
    def _db(tmp_path, with_execution=True):
        from neuromaestro.pipeline.utils.job_db import get_db_connection
        db_path = str(tmp_path / "wrap.db")
        conn = get_db_connection(db_path)
        if with_execution:
            conn.execute(
                "INSERT INTO pipeline_executions "
                "(execution_id, project_name, session, status, execution_time) "
                "VALUES (7, 'branch', '02', 'COMPLETED', '2026-07-01 09:00:00')"
            )
        conn.execute(
            "INSERT INTO wrapper_scripts "
            "(execution_id, task_name, job_id, submission_time, wrapper_path, slurm_cmd) "
            "VALUES (7, 'recon', '999', '2026-07-01 09:00:00', '/w/x.sh', 'sbatch x')"
        )
        conn.commit()
        conn.close()
        return db_path

    def test_project_and_session_shown(self, callbacks, tmp_path):
        fn = callbacks.get("load_wrapper_callback")
        result = fn(1, db_path=self._db(tmp_path), task_filter="recon", job_id="")
        text = str(result)
        assert "Project: branch" in text
        assert "Session: 02" in text

    def test_unresolvable_execution_still_renders(self, callbacks, tmp_path):
        # Older logs were written without an execution_id link
        fn = callbacks.get("load_wrapper_callback")
        result = fn(1, db_path=self._db(tmp_path, with_execution=False),
                    task_filter="recon", job_id="")
        text = str(result)
        assert "Project: unknown" in text
        assert "sbatch x" in text

    def test_task_filter_still_applies(self, callbacks, tmp_path):
        fn = callbacks.get("load_wrapper_callback")
        result = fn(1, db_path=self._db(tmp_path), task_filter="no_such_task", job_id="")
        assert isinstance(result, dbc.Alert)
        assert "No wrapper script found" in str(result.children)

    def test_job_id_filter_still_applies(self, callbacks, tmp_path):
        fn = callbacks.get("load_wrapper_callback")
        result = fn(1, db_path=self._db(tmp_path), task_filter="", job_id="999")
        assert "Job ID: 999" in str(result)

    @staticmethod
    def _db_with_newer_wrapper(tmp_path):
        db_path = TestWrapperInspectorShowsProvenance._db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO wrapper_scripts "
            "(execution_id, task_name, job_id, submission_time, wrapper_path, slurm_cmd) "
            "VALUES (7, 'recon', '1000', '2026-07-02 09:00:00', '/w/y.sh', 'sbatch y')"
        )
        conn.commit()
        conn.close()
        return db_path

    def test_job_id_filter_picks_its_own_wrapper_over_a_newer_one(self, callbacks, tmp_path):
        fn = callbacks.get("load_wrapper_callback")
        text = str(fn(1, db_path=self._db_with_newer_wrapper(tmp_path), task_filter="", job_id="999"))
        assert "sbatch x" in text
        assert "sbatch y" not in text

    def test_blank_filters_show_the_newest_wrapper(self, callbacks, tmp_path):
        fn = callbacks.get("load_wrapper_callback")
        text = str(fn(1, db_path=self._db_with_newer_wrapper(tmp_path), task_filter="", job_id=""))
        assert "sbatch y" in text
        assert "sbatch x" not in text

    # Dash sends None for an input that was never typed in
    @pytest.mark.parametrize("blank", [None, "   "])
    def test_unset_or_whitespace_filters_are_ignored(self, callbacks, tmp_path, blank):
        fn = callbacks.get("load_wrapper_callback")
        text = str(fn(1, db_path=self._db_with_newer_wrapper(tmp_path), task_filter=blank, job_id=blank))
        assert "sbatch y" in text

    @pytest.mark.parametrize("job_id, shown", [("99", "sbatch x"), ("00", None)])
    def test_job_id_matches_from_the_start(self, callbacks, tmp_path, job_id, shown):
        # an array parent id finds its subjobs, a fragment from the middle finds nothing
        fn = callbacks.get("load_wrapper_callback")
        result = fn(1, db_path=self._db_with_newer_wrapper(tmp_path), task_filter="", job_id=job_id)
        if shown:
            assert shown in str(result)
        else:
            assert result.children == "No wrapper script found matching the filters."

    def test_task_filter_matches_part_of_the_name(self, callbacks, tmp_path):
        fn = callbacks.get("load_wrapper_callback")
        assert "sbatch x" in str(fn(1, db_path=self._db(tmp_path), task_filter=" eco ", job_id=""))

    def test_no_database_given(self, callbacks):
        result = callbacks.get("load_wrapper_callback")(1, db_path=None, task_filter="", job_id="")
        assert (result.color, result.children) == ("danger", "Database file not found: None")


# ---------------------------------------------------------------------------
# _build_query
#
# The query and export paths used to build SQL separately, which let them
# drift: exporting "wrapper_scripts" silently dumped pipeline_executions, and
# a bare end date excluded everything recorded on that day.
# ---------------------------------------------------------------------------

class TestBuildQuery:

    ALL_TYPES = {"job_status", "command_outputs", "pipeline_executions", "wrapper_scripts"}

    @staticmethod
    def _build(*args, **kwargs):
        from neuromaestro.interface.callbacks.job_monitor_callbacks import _build_query
        return _build_query(*args, **kwargs)

    @staticmethod
    def _specs():
        from neuromaestro.interface.callbacks.job_monitor_callbacks import _QUERY_SPECS
        return _QUERY_SPECS

    @pytest.fixture
    def db(self, tmp_path):
        """One row per table, all stamped 2026-07-28 09:00:00."""
        from neuromaestro.pipeline.utils.job_db import get_db_connection
        conn = get_db_connection(str(tmp_path / "q.db"))
        conn.execute("INSERT INTO pipeline_executions "
                     "(execution_id, project_name, session, status, execution_time) "
                     "VALUES (1,'proj','01','COMPLETED','2026-07-28 09:00:00')")
        conn.execute("INSERT INTO job_status "
                     "(execution_id, subject, task_name, session, start_time, status) "
                     "VALUES (1,'001','recon','01','2026-07-28 09:00:00','SUCCESS')")
        conn.execute("INSERT INTO command_outputs "
                     "(execution_id, subject, task_name, execution_time, exit_code) "
                     "VALUES (1,'001','recon','2026-07-28 09:00:00',0)")
        conn.execute("INSERT INTO wrapper_scripts "
                     "(execution_id, task_name, job_id, submission_time, wrapper_path, full_content) "
                     "VALUES (1,'recon','999','2026-07-28 09:00:00','/w/x.sh','#!/bin/bash')")
        conn.commit()
        yield conn
        conn.close()

    def test_unknown_query_type_returns_none(self):
        assert self._build("nope") == (None, None)

    @pytest.mark.parametrize("query_type", [
        "job_status", "command_outputs", "pipeline_executions", "wrapper_scripts",
    ])
    def test_every_type_produces_runnable_sql(self, db, query_type):
        sql, params = self._build(query_type, paged=True)
        assert len(db.execute(sql, params).fetchall()) == 1

    @pytest.mark.parametrize("query_type", [
        "job_status", "command_outputs", "pipeline_executions", "wrapper_scripts",
    ])
    def test_end_date_includes_records_on_that_day(self, db, query_type):
        # The regression: '<= 2026-07-28' dropped a row stamped 09:00 that day
        sql, params = self._build(query_type, start_date="2026-07-28",
                                  end_date="2026-07-28", paged=True)
        assert len(db.execute(sql, params).fetchall()) == 1

    def test_export_of_wrapper_scripts_hits_the_right_table(self):
        # The regression: this fell through to pipeline_executions
        sql, _ = self._build("wrapper_scripts", columns="*")
        assert "FROM wrapper_scripts" in sql
        assert "pipeline_executions" not in sql

    def test_export_includes_full_content(self, db):
        sql, params = self._build("wrapper_scripts", columns="*")
        cols = [d[0] for d in db.execute(sql, params).description]
        assert "full_content" in cols

    def test_table_view_omits_full_content(self, db):
        sql, params = self._build("wrapper_scripts", paged=True)
        cols = [d[0] for d in db.execute(sql, params).description]
        assert "full_content" not in cols

    def test_status_all_is_not_a_filter(self):
        _sql, params = self._build("job_status", status="all", paged=True)
        assert params == []

    def test_blank_filters_are_ignored(self):
        _sql, params = self._build("job_status", subject="", session=None,
                                   task="   ", execution_id="", paged=True)
        assert params == []

    def test_non_matching_filter_returns_no_rows(self, db):
        sql, params = self._build("job_status", subject="zzz", paged=True)
        assert db.execute(sql, params).fetchall() == []

    # each filter must drop the fixture row while keeping a second row that matches it
    @pytest.mark.parametrize("filters, expected", [
        ({"subject": "002"}, ["002"]),
        ({"session": "02"}, ["002"]),
        ({"task": "volume"}, ["002"]),
        ({"status": "FAILED"}, ["002"]),
        ({"execution_id": "2"}, ["002"]),
        ({"start_date": "2026-07-29"}, ["002"]),
        ({"end_date": "2026-07-28"}, ["001"]),
    ])
    def test_job_status_filters_exclude_non_matching_rows(self, db, filters, expected):
        db.execute("INSERT INTO job_status "
                   "(execution_id, subject, task_name, session, start_time, status) "
                   "VALUES (2,'002','volume','02','2026-07-29 09:00:00','FAILED')")
        sql, params = self._build("job_status", columns="subject", **filters)
        assert [row[0] for row in db.execute(sql, params).fetchall()] == expected

    @pytest.mark.parametrize("filters", [{"session": "02"}, {"status": "FAILED"}])
    def test_pipeline_execution_filters_exclude_non_matching_rows(self, db, filters):
        db.execute("INSERT INTO pipeline_executions "
                   "(execution_id, project_name, session, status, execution_time) "
                   "VALUES (2,'proj','02','FAILED','2026-07-29 09:00:00')")
        sql, params = self._build("pipeline_executions", columns="execution_id", **filters)
        assert [row[0] for row in db.execute(sql, params).fetchall()] == [2]

    def test_execution_id_is_exact_not_fuzzy(self, db):
        sql, params = self._build("job_status", execution_id="1", paged=True)
        assert "execution_id = ?" in sql
        assert len(db.execute(sql, params).fetchall()) == 1

    def test_subject_filter_is_fuzzy(self):
        sql, params = self._build("job_status", subject="01", paged=True)
        assert "subject LIKE ?" in sql
        assert params == ["%01%"]

    def test_export_is_not_limited(self):
        sql, _ = self._build("job_status")
        assert "LIMIT" not in sql

    def test_view_applies_the_per_type_limit(self):
        specs = self._specs()
        assert set(specs) == self.ALL_TYPES
        for query_type, spec in specs.items():
            sql, _ = self._build(query_type, paged=True)
            assert sql.endswith(f"LIMIT {spec['view_limit']}")

    def test_filters_only_apply_where_the_column_exists(self, db):
        # command_outputs has no session column; passing one must not break it
        sql, params = self._build("command_outputs", session="01", paged=True)
        assert "session" not in sql
        assert len(db.execute(sql, params).fetchall()) == 1

    def test_every_spec_orders_by_its_own_time_column(self):
        specs = self._specs()
        assert set(specs) == self.ALL_TYPES
        for query_type, spec in specs.items():
            sql, _ = self._build(query_type, paged=True)
            assert f"ORDER BY {spec['time_column']} DESC" in sql


# ---------------------------------------------------------------------------
# status_options_for
#
# Each table records its own status vocabulary. A single fixed dropdown meant
# "Success" never matched a pipeline_executions row (which stores COMPLETED),
# and the filter stayed clickable for tables that have no status column.
# ---------------------------------------------------------------------------

class TestStatusOptions:

    @staticmethod
    def _options(query_type):
        from neuromaestro.interface.callbacks.job_monitor_callbacks import status_options_for
        return status_options_for(query_type)

    @staticmethod
    def _values(options):
        return [o["value"] for o in options]

    def test_job_status_offers_the_job_level_vocabulary(self):
        options, disabled = self._options("job_status")
        assert self._values(options) == ["all", "RUNNING", "SUCCESS", "FAILED", "CANCELLED"]
        assert disabled is False

    def test_pipeline_executions_offers_completed_not_success(self):
        options, disabled = self._options("pipeline_executions")
        values = self._values(options)
        assert "COMPLETED" in values
        assert "SUCCESS" not in values
        assert disabled is False

    def test_pipeline_executions_can_filter_for_unfinished_runs(self):
        # A run killed before its pipeline_update was merged stays RUNNING
        # forever, which is exactly the row worth finding
        options, _disabled = self._options("pipeline_executions")
        assert "RUNNING" in self._values(options)

    @pytest.mark.parametrize("query_type", ["command_outputs", "wrapper_scripts"])
    def test_tables_without_a_status_column_disable_the_filter(self, query_type):
        options, disabled = self._options(query_type)
        assert self._values(options) == ["all"]
        assert disabled is True

    def test_unknown_query_type_falls_back_to_all(self):
        options, disabled = self._options("bogus")
        assert self._values(options) == ["all"]
        assert disabled is True

    def test_every_offered_value_exists_in_the_database(self, tmp_path):
        """Every offered status becomes a status clause its table can run."""
        from neuromaestro.interface.callbacks.job_monitor_callbacks import (
            _build_query, _QUERY_SPECS,
        )
        from neuromaestro.pipeline.utils.job_db import get_db_connection
        conn = get_db_connection(str(tmp_path / "s.db"))
        checked = 0
        try:
            for query_type, spec in _QUERY_SPECS.items():
                for value in spec["status_values"]:
                    sql, params = _build_query(query_type, status=value)
                    assert "status = ?" in sql and params == [value], query_type
                    conn.execute(sql, params)   # raises if the column is absent
                    checked += 1
        finally:
            conn.close()
        # without this the loop passes vacuously if a spec loses status_values;
        # 4 for job_status + 3 for pipeline_executions, the other two have none
        assert checked == 7

    # Every value the pipeline can write into each status column, traced to its
    # writer. Maintained by hand because the writers are split across Python
    # and bash; the test below is what keeps the dropdown from drifting off it.
    _WRITTEN_BY_THE_PIPELINE = {
        # merge_logs_create_db inserts RUNNING, then log_end overwrites it with
        # SUCCESS or FAILED, or CANCELLED from the wrapper's signal trap.
        "job_status": {"RUNNING", "SUCCESS", "FAILED", "CANCELLED"},
        # log_pipeline_execution writes RUNNING; core.py then calls
        # update_pipeline_execution with COMPLETED or FAILED.
        "pipeline_executions": {"RUNNING", "COMPLETED", "FAILED"},
        "command_outputs": set(),
        "wrapper_scripts": set(),
    }

    def test_no_written_status_is_missing_from_the_dropdown(self):
        """The inverse of test_every_offered_value_exists_in_the_database.

        A value the table can hold but the dropdown does not offer hides those
        rows entirely, which is worse than an option that matches nothing.
        """
        from neuromaestro.interface.callbacks.job_monitor_callbacks import _QUERY_SPECS
        for query_type, expected in self._WRITTEN_BY_THE_PIPELINE.items():
            offered = set(_QUERY_SPECS[query_type]["status_values"])
            assert offered == expected, query_type

    def test_callback_resets_selection_when_type_changes(self, callbacks):
        fn = callbacks.get("sync_status_options")
        options, value, disabled = fn("pipeline_executions")
        assert value == "all"
        assert "COMPLETED" in [o["value"] for o in options]
        assert disabled is False


# ---------------------------------------------------------------------------
# execute_sql_query_callback
#
# The view applied the per-type LIMIT and then sliced to 50 again, so
# view_limit had no effect and the heading reported the truncated row count as
# the number of matching records.
# ---------------------------------------------------------------------------

def _find_components(component, type_name, found=None):
    """Depth-first search by component class name, whatever happens to wrap it."""
    if found is None:
        found = []
    if type(component).__name__ == type_name:
        found.append(component)
    children = getattr(component, "children", None)
    if children is not None:
        if not isinstance(children, (list, tuple)):
            children = [children]
        for child in children:
            _find_components(child, type_name, found)
    return found


def _find_tbody(component):
    matches = _find_components(component, "Tbody")
    return matches[0] if matches else None


class TestExecuteSqlQueryPaging:

    @staticmethod
    def _db(tmp_path, n_rows):
        from neuromaestro.pipeline.utils.job_db import get_db_connection
        db_path = str(tmp_path / "paging.db")
        conn = get_db_connection(db_path)
        conn.executemany(
            "INSERT INTO job_status "
            "(execution_id, subject, task_name, session, start_time, status, duration_hours) "
            "VALUES (1, ?, 'recon', '01', ?, 'SUCCESS', 1.0)",
            [(f"{i:03d}", f"2026-07-{(i % 28) + 1:02d} 09:00:00") for i in range(n_rows)],
        )
        conn.commit()
        conn.close()
        return db_path

    @staticmethod
    def _view_limit(query_type):
        from neuromaestro.interface.callbacks.job_monitor_callbacks import _QUERY_SPECS
        return _QUERY_SPECS[query_type]["view_limit"]

    @staticmethod
    def _run(callbacks, db_path, query_type="job_status"):
        fn = callbacks.get("execute_sql_query_callback")
        return fn(1, db_path, query_type, None, None, None, "all", None, None, None)

    def test_view_renders_up_to_the_per_type_limit(self, callbacks, tmp_path):
        # The regression: a second .head(50) capped this well below view_limit
        limit = self._view_limit("job_status")
        results, _charts = self._run(callbacks, self._db(tmp_path, limit + 20))
        assert len(_find_tbody(results).children) == limit

    def test_full_page_does_not_claim_a_record_count(self, callbacks, tmp_path):
        limit = self._view_limit("job_status")
        results, _charts = self._run(callbacks, self._db(tmp_path, limit + 20))
        heading = results.children[0].children
        assert "records found" not in heading
        assert str(limit) in heading

    def test_partial_page_reports_the_real_count(self, callbacks, tmp_path):
        results, _charts = self._run(callbacks, self._db(tmp_path, 7))
        assert len(_find_tbody(results).children) == 7
        assert "7 records found" in results.children[0].children

    def test_no_rows_returns_secondary_alert(self, callbacks, tmp_path):
        results, charts = self._run(callbacks, self._db(tmp_path, 0))
        assert isinstance(results, dbc.Alert)
        assert results.color == "secondary"
        assert charts == ""

    def test_missing_database_returns_danger(self, callbacks, tmp_path):
        missing = tmp_path / "nope.db"
        results, _charts = self._run(callbacks, str(missing))
        assert isinstance(results, dbc.Alert)
        assert results.color == "danger"
        assert results.children == f"Database file not found: {missing}"
        # sqlite3.connect would have created an empty file at the mistyped path
        assert not missing.exists()

    def test_unknown_query_type_returns_warning(self, callbacks, tmp_path):
        results, _charts = self._run(callbacks, self._db(tmp_path, 1), query_type="bogus")
        assert isinstance(results, dbc.Alert)
        assert results.color == "warning"


# ---------------------------------------------------------------------------
# export_csv_callback
# ---------------------------------------------------------------------------

class TestExportCsvDestination:

    @staticmethod
    def _db(tmp_path):
        from neuromaestro.pipeline.utils.job_db import get_db_connection
        db_path = tmp_path / "pipeline_jobs.db"
        conn = get_db_connection(str(db_path))
        conn.execute("INSERT INTO job_status "
                     "(execution_id, subject, task_name, session, start_time, status) "
                     "VALUES (1,'001','recon','01','2026-07-28 09:00:00','SUCCESS')")
        conn.commit()
        conn.close()
        return db_path

    def test_csv_lands_next_to_the_database(self, callbacks, tmp_path):
        fn = callbacks.get("export_csv_callback")
        db_path = self._db(tmp_path)
        result = fn(1, str(db_path), "job_status", None, None, None, "all", None)

        assert result.color == "success"
        assert list(tmp_path.glob("job_status_*.csv"))

    def test_relative_db_path_reports_an_absolute_destination(self, callbacks, tmp_path, monkeypatch):
        # The regression: dirname("pipeline_jobs.db") is "", so the file was
        # written to the process cwd but reported as a bare filename.
        fn = callbacks.get("export_csv_callback")
        self._db(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = fn(1, "pipeline_jobs.db", "job_status", None, None, None, "all", None)

        assert result.color == "success"
        reported = str(result.children).rsplit(" to ", 1)[-1]
        assert os.path.isabs(reported)
        assert os.path.exists(reported)

    def test_export_is_not_truncated_by_the_view_limit(self, callbacks, tmp_path):
        from neuromaestro.pipeline.utils.job_db import get_db_connection
        db_path = tmp_path / "big.db"
        conn = get_db_connection(str(db_path))
        conn.executemany(
            "INSERT INTO job_status "
            "(execution_id, subject, task_name, session, start_time, status) "
            "VALUES (1, ?, 'recon', '01', '2026-07-28 09:00:00', 'SUCCESS')",
            [(f"{i:03d}",) for i in range(150)],
        )
        conn.commit()
        conn.close()

        fn = callbacks.get("export_csv_callback")
        result = fn(1, str(db_path), "job_status", None, None, None, "all", None)

        assert "150 records" in str(result.children)
        exported = pd.read_csv(next(tmp_path.glob("job_status_*.csv")), dtype=str)
        assert len(exported) == 150
        assert exported.columns[0] != "Unnamed: 0"   # no pandas index column


# ---------------------------------------------------------------------------
# create_query_charts
#
# Which charts appear is driven by the query type and by which columns the
# table happens to carry.
# ---------------------------------------------------------------------------

class TestCreateQueryCharts:

    @staticmethod
    def _charts(df, query_type):
        from neuromaestro.interface.callbacks.job_monitor_callbacks import create_query_charts
        return create_query_charts(df, query_type)

    @pytest.fixture
    def job_status_df(self):
        return pd.DataFrame([
            {"start_time": "2026-07-01 09:00:00", "task_name": "recon",
             "duration_hours": 2.0, "status": "SUCCESS"},
            {"start_time": "2026-07-08 09:00:00", "task_name": "recon",
             "duration_hours": 4.0, "status": "FAILED"},
        ])

    def test_job_status_renders_timeline_radar_and_donut(self, job_status_df):
        graphs = _find_components(self._charts(job_status_df, "job_status"), "Graph")
        assert len(graphs) == 3

    def test_radar_is_dropped_when_duration_is_absent(self, job_status_df):
        df = job_status_df.drop(columns=["duration_hours"])
        graphs = _find_components(self._charts(df, "job_status"), "Graph")
        assert len(graphs) == 2

    def test_pipeline_executions_timeline_reads_its_own_time_column(self):
        # The table stores execution_time; create_timeline_chart only knows
        # start_time, so the column has to be renamed on the way in
        df = pd.DataFrame([
            {"execution_time": "2026-07-01 09:00:00", "status": "COMPLETED"},
            {"execution_time": "2026-07-08 09:00:00", "status": "FAILED"},
        ])
        graphs = _find_components(self._charts(df, "pipeline_executions"), "Graph")
        timeline = graphs[1].figure
        texts = [a.text for a in timeline.layout.annotations]
        assert "No timestamp data available" not in texts
        assert sum(timeline.data[0].y) == 2

    def test_command_outputs_renders_the_exit_code_bar(self):
        df = pd.DataFrame([{"exit_code": 0}, {"exit_code": 1}])
        graphs = _find_components(self._charts(df, "command_outputs"), "Graph")
        assert len(graphs) == 1
        assert graphs[0].figure.data[0].type == "bar"

    def test_wrapper_scripts_has_no_charts(self):
        df = pd.DataFrame([{"task_name": "recon", "wrapper_path": "/w/x.sh"}])
        assert self._charts(df, "wrapper_scripts") == ""

    def test_unknown_query_type_has_no_charts(self):
        assert self._charts(pd.DataFrame([{"a": 1}]), "bogus") == ""

    def test_a_failing_chart_is_reported_inline_not_raised(self, job_status_df):
        with patch("neuromaestro.interface.callbacks.job_monitor_callbacks.create_status_donut",
                   side_effect=RuntimeError("plotly blew up")):
            result = self._charts(job_status_df, "pipeline_executions")
        assert "plotly blew up" in str(result)
