"""
test_job_monitor_callbacks.py

Unit tests for the job monitor callbacks:
  - _render_check_table
  - merge_logs_callback
  - run_output_check_callback
  - export_check_csv_callback

"""

import os
import pytest
import sqlite3
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
    from neuro_pipeline.interface.callbacks.job_monitor_callbacks import register_job_monitor_callbacks
    register_job_monitor_callbacks(fake_app)
    return fake_app


# ---------------------------------------------------------------------------
# _render_check_table
# ---------------------------------------------------------------------------

class TestRenderCheckTable:

    @pytest.fixture(autouse=True)
    def _import(self):
        from neuro_pipeline.interface.callbacks.job_monitor_callbacks import _render_check_table
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
        bg = row.style.get("backgroundColor", "")
        assert "40,167,69" in bg or "40, 167, 69" in bg.replace(",", ", ")

    def test_fail_row_gets_red_background(self):
        df = self._make_df([{"subject": "002", "status": "FAIL - file not found"}])
        table = self.render(df)
        tbody = table.children[1]
        row = tbody.children[0]
        bg = row.style.get("backgroundColor", "")
        assert "220,53,69" in bg or "220, 53, 69" in bg.replace(",", ", ")

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

        with patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.subprocess.run",
                   return_value=mock_result):
            result = fn(n_clicks=1, work_dir=str(tmp_path), db_path="")

        assert isinstance(result, dbc.Alert)
        assert result.color == "success"

    def test_failed_command_returns_danger(self, callbacks, tmp_path):
        fn = callbacks.get("merge_logs_callback")
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "merge failed"
        mock_result.stdout = ""

        with patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.subprocess.run",
                   return_value=mock_result):
            result = fn(n_clicks=1, work_dir=str(tmp_path), db_path="")

        assert isinstance(result, dbc.Alert)
        assert result.color == "danger"

    def test_timeout_returns_danger(self, callbacks, tmp_path):
        import subprocess
        fn = callbacks.get("merge_logs_callback")

        with patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="neuropipe", timeout=120)):
            result = fn(n_clicks=1, work_dir=str(tmp_path), db_path="")

        assert isinstance(result, dbc.Alert)
        assert result.color == "danger"
        assert "timed out" in str(result.children).lower()

    def test_neuropipe_not_found_returns_danger(self, callbacks, tmp_path):
        fn = callbacks.get("merge_logs_callback")

        with patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.subprocess.run",
                   side_effect=FileNotFoundError):
            result = fn(n_clicks=1, work_dir=str(tmp_path), db_path="")

        assert isinstance(result, dbc.Alert)
        assert result.color == "danger"
        assert "not found" in str(result.children).lower()


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
        with patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.detect_subjects",
                   return_value=["007"], create=True), \
             patch("neuro_pipeline.pipeline.utils.detect_subjects.detect_subjects",
                   return_value=["007"]), \
             patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.load_checks_config",
                   return_value="/fake/path.yaml"), \
             patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.run_output_checks",
                   return_value=(fake_df, ["t"], [])) as mock_run:
            fn(1, project="myproject", work_dir=str(tmp_path), subjects_raw="",
               task_filter="", session="01", prefix="sub-")

        assert mock_run.call_args.kwargs["subjects"] == ["007"]

    def test_checks_config_not_found_returns_danger(self, callbacks, tmp_path):
        fn = callbacks.get("run_output_check_callback")
        with patch(
            "neuro_pipeline.interface.callbacks.job_monitor_callbacks.load_checks_config",
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
        ])
        with patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.load_checks_config",
                   return_value="/fake/path.yaml"), \
             patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.run_output_checks",
                   return_value=(fake_df, ["my_task"], [])):
            result = fn(1, project="myproject", work_dir=str(tmp_path),
                        subjects_raw="001", task_filter="", session="01", prefix="sub-")

        assert isinstance(result, html.Div)

    def test_all_pass_summary_is_success_color(self, callbacks, tmp_path):
        fn = callbacks.get("run_output_check_callback")
        fake_df = pd.DataFrame([
            {"task": "t", "subject": "001", "session": "01",
             "check_type": "required_files", "pattern": "*.html",
             "expected": "exists", "actual": 1, "status": "PASS"},
        ])
        with patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.load_checks_config",
                   return_value="/fake/path.yaml"), \
             patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.run_output_checks",
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
        with patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.load_checks_config",
                   return_value="/fake/path.yaml"), \
             patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.run_output_checks",
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
        with patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.load_checks_config",
                   return_value="/fake/path.yaml"), \
             patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.run_output_checks",
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

        with patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.load_checks_config",
                   return_value="/fake/path.yaml"), \
             patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.run_output_checks",
                   return_value=(fake_df, ["t"], [])), \
             patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.OutputChecker",
                   return_value=mock_checker):
            result = fn(1, project="myproject", work_dir=str(tmp_path),
                        subjects_raw="001", task_filter="", session="01", prefix="sub-")

        assert isinstance(result, dbc.Alert)
        assert result.color == "success"
        assert fake_csv in str(result.children)

    def test_file_not_found_returns_danger(self, callbacks, tmp_path):
        fn = callbacks.get("export_check_csv_callback")

        with patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.load_checks_config",
                   side_effect=FileNotFoundError("no file")):
            result = fn(1, project="ghost", work_dir=str(tmp_path),
                        subjects_raw="001", task_filter="", session="01", prefix="sub-")

        assert isinstance(result, dbc.Alert)
        assert result.color == "danger"

    def test_exception_while_running_checks_returns_danger(self, callbacks, tmp_path):
        fn = callbacks.get("export_check_csv_callback")

        with patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.load_checks_config",
                   return_value="/fake/path.yaml"), \
             patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.run_output_checks",
                   side_effect=RuntimeError("checks blew up")):
            result = fn(1, project="myproject", work_dir=str(tmp_path),
                        subjects_raw="001", task_filter="", session="01", prefix="sub-")

        assert isinstance(result, dbc.Alert)
        assert result.color == "danger"
        assert "checks blew up" in str(result.children)

    def test_exception_while_writing_csv_returns_danger(self, callbacks, tmp_path):
        fn = callbacks.get("export_check_csv_callback")
        fake_df = pd.DataFrame([{"task": "t", "subject": "001", "status": "PASS"}])
        mock_checker = MagicMock()
        mock_checker.save_csv.side_effect = OSError("disk full")

        with patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.load_checks_config",
                   return_value="/fake/path.yaml"), \
             patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.run_output_checks",
                   return_value=(fake_df, ["t"], [])), \
             patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.OutputChecker",
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
        from neuro_pipeline.interface.callbacks.job_monitor_callbacks import _parse_sessions
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
        with patch("neuro_pipeline.interface.callbacks.job_monitor_callbacks.OutputChecker") as mock_cls:
            fn(1, project="myproject", work_dir=str(tmp_path),
               subjects_raw="001", task_filter="", session="", prefix="sub-")
        mock_cls.assert_not_called()


class TestWrapperInspectorShowsProvenance:
    """wrapper_scripts stores no project or session, so the inspector had no
    way to say which run a wrapper came from. Both are joined in from the
    execution it belongs to.
    """

    @staticmethod
    def _db(tmp_path, with_execution=True):
        from neuro_pipeline.pipeline.utils.job_db import get_db_connection
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


# ---------------------------------------------------------------------------
# _build_query
#
# The query and export paths used to build SQL separately, which let them
# drift: exporting "wrapper_scripts" silently dumped pipeline_executions, and
# a bare end date excluded everything recorded on that day.
# ---------------------------------------------------------------------------

class TestBuildQuery:

    @staticmethod
    def _build(*args, **kwargs):
        from neuro_pipeline.interface.callbacks.job_monitor_callbacks import _build_query
        return _build_query(*args, **kwargs)

    @staticmethod
    def _specs():
        from neuro_pipeline.interface.callbacks.job_monitor_callbacks import _QUERY_SPECS
        return _QUERY_SPECS

    @pytest.fixture
    def db(self, tmp_path):
        """One row per table, all stamped 2026-07-28 09:00:00."""
        from neuro_pipeline.pipeline.utils.job_db import get_db_connection
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
        sql, params = self._build(query_type, limit=100)
        assert len(db.execute(sql, params).fetchall()) == 1

    @pytest.mark.parametrize("query_type", [
        "job_status", "command_outputs", "pipeline_executions", "wrapper_scripts",
    ])
    def test_end_date_includes_records_on_that_day(self, db, query_type):
        # The regression: '<= 2026-07-28' dropped a row stamped 09:00 that day
        sql, params = self._build(query_type, start_date="2026-07-28",
                                  end_date="2026-07-28", limit=100)
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
        sql, params = self._build("wrapper_scripts", limit=100)
        cols = [d[0] for d in db.execute(sql, params).description]
        assert "full_content" not in cols

    def test_status_all_is_not_a_filter(self):
        _sql, params = self._build("job_status", status="all", limit=100)
        assert params == []

    def test_blank_filters_are_ignored(self):
        _sql, params = self._build("job_status", subject="", session=None,
                                   task="   ", execution_id="", limit=100)
        assert params == []

    def test_non_matching_filter_returns_no_rows(self, db):
        sql, params = self._build("job_status", subject="zzz", limit=100)
        assert db.execute(sql, params).fetchall() == []

    def test_execution_id_is_exact_not_fuzzy(self, db):
        sql, params = self._build("job_status", execution_id="1", limit=100)
        assert "execution_id = ?" in sql
        assert len(db.execute(sql, params).fetchall()) == 1

    def test_subject_filter_is_fuzzy(self):
        sql, params = self._build("job_status", subject="01", limit=100)
        assert "subject LIKE ?" in sql
        assert params == ["%01%"]

    def test_limit_omitted_when_not_requested(self):
        sql, _ = self._build("job_status")
        assert "LIMIT" not in sql

    def test_limit_applied_when_requested(self):
        sql, _ = self._build("job_status", limit=50)
        assert sql.endswith("LIMIT 50")

    def test_filters_only_apply_where_the_column_exists(self, db):
        # command_outputs has no session column; passing one must not break it
        sql, params = self._build("command_outputs", session="01", limit=100)
        assert "session" not in sql
        assert len(db.execute(sql, params).fetchall()) == 1

    def test_every_spec_orders_by_its_own_time_column(self):
        for query_type, spec in self._specs().items():
            sql, _ = self._build(query_type, limit=10)
            assert f"ORDER BY {spec['time_column']} DESC" in sql
