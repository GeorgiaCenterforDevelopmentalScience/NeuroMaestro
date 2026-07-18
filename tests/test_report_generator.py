"""
test_report_generator.py

Tests for pipeline/utils/report_generator.py using mock data.
  - compute_task_summary: counts, duration string, task ordering, empty input
  - get_report_data: subject collection, session filter, metadata, failed_jobs
  - generate_report: error paths (missing db/csv, no subjects), happy path
"""

import sqlite3
import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import patch

from neuro_pipeline.pipeline.utils.job_db import get_db_connection
from neuro_pipeline.pipeline.utils.report_generator import (
    compute_task_summary,
    get_report_data,
    ordered_tasks_from_summary,
    generate_report,
    _build_sessions_data,
)

TASK_ORDER_PATH = "neuro_pipeline.pipeline.utils.report_generator.TASK_ORDER"
MOCK_TASK_ORDER = ["recon", "volume", "rest_preprocess", "rest_post"]


# ---------------------------------------------------------------------------
# Shared DB fixture
# ---------------------------------------------------------------------------

def _make_db(tmp_path, project="proj", session="01"):
    db_path = str(tmp_path / "pipeline_jobs.db")
    conn = get_db_connection(db_path)
    conn.execute(
        "INSERT INTO pipeline_executions "
        "(execution_id, project_name, session, status, subjects, requested_tasks, dry_run, total_jobs, execution_time) "
        "VALUES (1001, ?, ?, 'COMPLETED', '001,002', 'recon,volume', 0, 4, '2024-01-01 09:00:00')",
        [project, session],
    )
    conn.execute(
        "INSERT INTO pipeline_executions "
        "(execution_id, project_name, session, status, subjects, requested_tasks, dry_run, total_jobs, execution_time) "
        "VALUES (1002, ?, ?, 'COMPLETED', '001,002,003', 'recon', 0, 3, '2024-01-02 09:00:00')",
        [project, session],
    )
    conn.execute(
        "INSERT INTO job_status "
        "(execution_id, subject, task_name, session, status, duration_hours, start_time, end_time) "
        "VALUES (1001, '001', 'recon', ?, 'SUCCESS', 1.0, '2024-01-01 10:00:00', '2024-01-01 11:00:00')",
        [session],
    )
    conn.execute(
        "INSERT INTO job_status "
        "(execution_id, subject, task_name, session, status, duration_hours, start_time, end_time) "
        "VALUES (1001, '002', 'recon', ?, 'SUCCESS', 3.0, '2024-01-01 10:00:00', '2024-01-01 13:00:00')",
        [session],
    )
    conn.execute(
        "INSERT INTO job_status "
        "(execution_id, subject, task_name, session, status, duration_hours, start_time) "
        "VALUES (1001, '001', 'volume', ?, 'FAILED', NULL, '2024-01-01 11:30:00')",
        [session],
    )
    conn.execute(
        "INSERT INTO job_status "
        "(execution_id, subject, task_name, session, status, duration_hours, start_time, end_time) "
        "VALUES (1002, '003', 'recon', ?, 'SUCCESS', 2.0, '2024-01-02 10:00:00', '2024-01-02 12:00:00')",
        [session],
    )
    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# compute_task_summary
# ---------------------------------------------------------------------------

class TestComputeTaskSummary:

    SUBJECTS = ["001", "002", "003"]

    JOB_STATUS = [
        {"subject": "001", "task_name": "recon",  "status": "SUCCESS", "duration_hours": 1.0, "start_time": "2024-01-01T10:00:00"},
        {"subject": "002", "task_name": "recon",  "status": "SUCCESS", "duration_hours": 3.0, "start_time": "2024-01-01T10:00:00"},
        {"subject": "003", "task_name": "recon",  "status": "FAILED",  "duration_hours": None, "start_time": "2024-01-01T09:00:00"},
        {"subject": "001", "task_name": "volume", "status": "FAILED",  "duration_hours": None, "start_time": "2024-01-01T11:00:00"},
    ]

    def _run(self, job_status=None, subjects=None):
        js = job_status if job_status is not None else self.JOB_STATUS
        subj = subjects if subjects is not None else self.SUBJECTS
        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER):
            return compute_task_summary(js, subj)

    # --- counts ---

    def test_ok_count(self):
        summary = self._run()
        recon = next(r for r in summary if r["task"] == "recon")
        assert recon["ok"] == 2

    def test_failed_count(self):
        summary = self._run()
        recon = next(r for r in summary if r["task"] == "recon")
        assert recon["failed"] == 1

    def test_not_run_count(self):
        summary = self._run()
        volume = next(r for r in summary if r["task"] == "volume")
        # 3 subjects total, only 1 has a volume record
        assert volume["not_run"] == 2

    def test_all_run_no_not_run(self):
        summary = self._run()
        recon = next(r for r in summary if r["task"] == "recon")
        assert recon["not_run"] == 0

    def test_total_always_equals_subject_count(self):
        summary = self._run()
        for row in summary:
            assert row["total"] == len(self.SUBJECTS)

    # --- duration string ---

    def test_duration_mean_std_for_two_successes(self):
        # durations 1.0 and 3.0 → mean=2.0, std=1.4
        summary = self._run()
        recon = next(r for r in summary if r["task"] == "recon")
        assert "h ±" in recon["dur"]
        assert recon["dur"].startswith("2.0h")

    def test_duration_single_value_for_one_success(self):
        js = [{"subject": "001", "task_name": "recon", "status": "SUCCESS",
               "duration_hours": 2.5, "start_time": "2024-01-01T10:00:00"}]
        summary = self._run(job_status=js, subjects=["001"])
        recon = next(r for r in summary if r["task"] == "recon")
        assert recon["dur"] == "2.5h"

    def test_duration_dash_when_no_successes(self):
        summary = self._run()
        volume = next(r for r in summary if r["task"] == "volume")
        assert volume["dur"] == "—"

    # --- last_run date ---

    def test_last_run_formatted_as_date(self):
        summary = self._run()
        recon = next(r for r in summary if r["task"] == "recon")
        assert recon["last"] == "2024-01-01"

    # --- task ordering ---

    def test_tasks_ordered_by_task_order(self):
        summary = self._run()
        task_names = [r["task"] for r in summary]
        # recon comes before volume in MOCK_TASK_ORDER
        assert task_names.index("recon") < task_names.index("volume")

    def test_extra_tasks_not_in_task_order_appear_at_end(self):
        js = self.JOB_STATUS + [
            {"subject": "001", "task_name": "zzz_custom", "status": "SUCCESS",
             "duration_hours": 1.0, "start_time": "2024-01-01T10:00:00"}
        ]
        summary = self._run(job_status=js)
        task_names = [r["task"] for r in summary]
        assert task_names[-1] == "zzz_custom"

    # --- empty input ---

    def test_empty_job_status_returns_empty_list(self):
        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER):
            summary = compute_task_summary([], ["001", "002"])
        assert summary == []


    def test_success_rate_never_exceeds_100_percent_multi_session(self):
        # 2 subjects × 2 sessions = 4 SUCCESS records for the same task
        # When compute_task_summary is called with only session-01 jobs and
        # only session-01 subjects, ok/total must be ≤ 1.0
        js_sess01 = [
            {"subject": "001", "task_name": "recon", "session": "01",
             "status": "SUCCESS", "duration_hours": 1.0, "start_time": "2024-01-01"},
            {"subject": "002", "task_name": "recon", "session": "01",
             "status": "SUCCESS", "duration_hours": 1.0, "start_time": "2024-01-01"},
        ]
        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER):
            summary = compute_task_summary(js_sess01, ["001", "002"])
        recon = next(r for r in summary if r["task"] == "recon")
        assert recon["ok"] <= recon["total"]


# ---------------------------------------------------------------------------
# _build_sessions_data
# ---------------------------------------------------------------------------

class TestBuildSessionsData:

    def _make_jobs(self):
        return [
            {"subject": "001", "task_name": "recon", "session": "01",
             "status": "SUCCESS", "duration_hours": 1.0, "start_time": "2024-01-01"},
            {"subject": "002", "task_name": "recon", "session": "01",
             "status": "FAILED",  "duration_hours": None, "start_time": "2024-01-01"},
            {"subject": "001", "task_name": "recon", "session": "02",
             "status": "SUCCESS", "duration_hours": 2.0, "start_time": "2024-01-15"},
        ]

    def test_splits_into_one_entry_per_session(self):
        sessions_data = _build_sessions_data(self._make_jobs(), [], [])
        assert len(sessions_data) == 2
        assert {sd["session"] for sd in sessions_data} == {"01", "02"}

    def test_subjects_per_session_are_correct(self):
        sessions_data = _build_sessions_data(self._make_jobs(), [], [])
        sess01 = next(sd for sd in sessions_data if sd["session"] == "01")
        sess02 = next(sd for sd in sessions_data if sd["session"] == "02")
        assert set(sess01["all_subjects"]) == {"001", "002"}
        assert set(sess02["all_subjects"]) == {"001"}

    def test_task_summary_total_matches_session_subjects(self):
        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER):
            sessions_data = _build_sessions_data(self._make_jobs(), [], [])
        sess01 = next(sd for sd in sessions_data if sd["session"] == "01")
        recon = next(r for r in sess01["task_summary"] if r["task"] == "recon")
        assert recon["total"] == 2   # only 2 subjects in session 01

    def test_failed_jobs_split_by_session(self):
        failed = [
            {"subject": "002", "task_name": "recon", "session": "01", "status": "FAILED",
             "start_time": "2024-01-01", "exit_code": 1, "error_msg": "OOM",
             "stderr": "", "stdout": ""},
        ]
        sessions_data = _build_sessions_data(self._make_jobs(), failed, [])
        sess01 = next(sd for sd in sessions_data if sd["session"] == "01")
        sess02 = next(sd for sd in sessions_data if sd["session"] == "02")
        assert len(sess01["failed_jobs"]) == 1
        assert len(sess02["failed_jobs"]) == 0

    def test_no_session_field_groups_all_under_none(self):
        jobs_no_sess = [
            {"subject": "001", "task_name": "recon", "session": None,
             "status": "SUCCESS", "duration_hours": 1.0, "start_time": "2024-01-01"},
        ]
        sessions_data = _build_sessions_data(jobs_no_sess, [], [])
        assert len(sessions_data) == 1
        assert sessions_data[0]["session"] is None


# ---------------------------------------------------------------------------
# ordered_tasks_from_summary
# ---------------------------------------------------------------------------

class TestOrderedTasksFromSummary:

    def test_extracts_task_names_in_order(self):
        summary = [{"task": "recon"}, {"task": "volume"}, {"task": "rest_preprocess"}]
        assert ordered_tasks_from_summary(summary) == ["recon", "volume", "rest_preprocess"]

    def test_empty_summary(self):
        assert ordered_tasks_from_summary([]) == []


# ---------------------------------------------------------------------------
# get_report_data
# ---------------------------------------------------------------------------

class TestGetReportData:

    def test_collects_all_subjects_across_executions(self, tmp_path):
        db_path = _make_db(tmp_path)
        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER):
            data = get_report_data(db_path, "proj", "01")
        # Execution 1 has 001,002; execution 2 has 001,002,003 → union = {001,002,003}
        assert set(data["all_subjects"]) == {"001", "002", "003"}

    def test_subjects_sorted_alphabetically(self, tmp_path):
        db_path = _make_db(tmp_path)
        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER):
            data = get_report_data(db_path, "proj", "01")
        assert data["all_subjects"] == sorted(data["all_subjects"], key=str.lower)

    def test_metadata_is_latest_execution(self, tmp_path):
        db_path = _make_db(tmp_path)
        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER):
            data = get_report_data(db_path, "proj", "01")
        # execution_id 1002 is more recent (2024-01-02 > 2024-01-01)
        assert data["metadata"].get("execution_id") == 1002

    def test_job_status_returns_records(self, tmp_path):
        db_path = _make_db(tmp_path)
        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER):
            data = get_report_data(db_path, "proj", "01")
        assert len(data["job_status"]) > 0

    def test_failed_jobs_only_contains_failed_records(self, tmp_path):
        db_path = _make_db(tmp_path)
        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER):
            data = get_report_data(db_path, "proj", "01")
        for job in data["failed_jobs"]:
            assert job["status"] == "FAILED"

    def test_session_filter_excludes_other_sessions(self, tmp_path):
        db_path = _make_db(tmp_path, session="01")
        # Add a record for session 02
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO pipeline_executions "
            "(execution_id, project_name, session, status, subjects, requested_tasks, dry_run, total_jobs, execution_time) "
            "VALUES (9999, 'proj', '02', 'COMPLETED', '099', 'recon', 0, 1, '2024-01-03 09:00:00')"
        )
        conn.commit()
        conn.close()

        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER):
            data = get_report_data(db_path, "proj", "01")
        assert "099" not in data["all_subjects"]

    def test_no_session_filter_collects_all(self, tmp_path):
        db_path = _make_db(tmp_path, session="01")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO pipeline_executions "
            "(execution_id, project_name, session, status, subjects, requested_tasks, dry_run, total_jobs, execution_time) "
            "VALUES (9999, 'proj', '02', 'COMPLETED', '099', 'recon', 0, 1, '2024-01-03 09:00:00')"
        )
        conn.commit()
        conn.close()

        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER):
            data = get_report_data(db_path, "proj", session=None)
        assert "099" in data["all_subjects"]

    def test_comma_sessions_collect_subjects_from_all(self, tmp_path):
        db_path = _make_db(tmp_path, session="01")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO pipeline_executions "
            "(execution_id, project_name, session, status, subjects, requested_tasks, dry_run, total_jobs, execution_time) "
            "VALUES (8888, 'proj', '02', 'COMPLETED', '099', 'recon', 0, 1, '2024-01-04 09:00:00')"
        )
        conn.commit()
        conn.close()

        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER):
            data = get_report_data(db_path, "proj", "01,02")
        assert "099" in data["all_subjects"]
        assert "001" in data["all_subjects"]

    def test_comma_sessions_exclude_unlisted_session(self, tmp_path):
        db_path = _make_db(tmp_path, session="01")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO pipeline_executions "
            "(execution_id, project_name, session, status, subjects, requested_tasks, dry_run, total_jobs, execution_time) "
            "VALUES (7777, 'proj', '03', 'COMPLETED', '077', 'recon', 0, 1, '2024-01-05 09:00:00')"
        )
        conn.commit()
        conn.close()

        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER):
            data = get_report_data(db_path, "proj", "01")
        assert "077" not in data["all_subjects"]

    def test_comma_sessions_with_spaces(self, tmp_path):
        db_path = _make_db(tmp_path, session="01")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO pipeline_executions "
            "(execution_id, project_name, session, status, subjects, requested_tasks, dry_run, total_jobs, execution_time) "
            "VALUES (6666, 'proj', '02', 'COMPLETED', '088', 'recon', 0, 1, '2024-01-06 09:00:00')"
        )
        conn.commit()
        conn.close()

        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER):
            data = get_report_data(db_path, "proj", "01, 02")  # space after comma
        assert "088" in data["all_subjects"]
        assert "001" in data["all_subjects"]

    def test_empty_db_returns_empty_subjects(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        get_db_connection(db_path).close()
        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER):
            data = get_report_data(db_path, "proj", "01")
        assert data["all_subjects"] == []
        assert data["job_status"] == []
        assert data["failed_jobs"] == []


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------

class TestGenerateReport:

    def _make_check_csv(self, tmp_path):
        csv_path = tmp_path / "check_results.csv"
        pd.DataFrame({
            "task":    ["recon", "recon"],
            "subject": ["001", "002"],
            "status":  ["PASS", "PASS"],
        }).to_csv(csv_path, index=False)
        return str(csv_path)

    def test_raises_if_db_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Database not found"):
            generate_report(
                db_path=str(tmp_path / "nonexistent.db"),
                project_name="proj",
                check_results_path=str(tmp_path / "checks.csv"),
            )

    def test_raises_if_check_results_not_found(self, tmp_path):
        db_path = _make_db(tmp_path)
        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER):
            with pytest.raises(FileNotFoundError, match="check-results file not found"):
                generate_report(
                    db_path=db_path,
                    project_name="proj",
                    check_results_path=str(tmp_path / "nonexistent.csv"),
                )

    def test_raises_if_no_subjects_in_db(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        get_db_connection(db_path).close()
        csv_path = self._make_check_csv(tmp_path)
        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER):
            with pytest.raises(ValueError, match="No records found"):
                generate_report(
                    db_path=db_path,
                    project_name="proj",
                    check_results_path=csv_path,
                )

    def test_creates_html_file_at_default_path(self, tmp_path):
        db_path = _make_db(tmp_path)
        csv_path = self._make_check_csv(tmp_path)
        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER), \
             patch("neuro_pipeline.pipeline.utils.report_generator.render_html",
                   return_value="<html>mock</html>"):
            out = generate_report(
                db_path=db_path,
                project_name="proj",
                check_results_path=csv_path,
                session="01",
            )
        assert Path(out).exists()
        assert Path(out).read_text() == "<html>mock</html>"

    def test_creates_html_file_at_explicit_path(self, tmp_path):
        db_path = _make_db(tmp_path)
        csv_path = self._make_check_csv(tmp_path)
        out_path = str(tmp_path / "my_report.html")
        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER), \
             patch("neuro_pipeline.pipeline.utils.report_generator.render_html",
                   return_value="<html>mock</html>"):
            out = generate_report(
                db_path=db_path,
                project_name="proj",
                check_results_path=csv_path,
                output_path=out_path,
                session="01",
            )
        assert out == out_path
        assert Path(out_path).exists()

    def test_creates_html_file_in_output_directory(self, tmp_path):
        db_path = _make_db(tmp_path)
        csv_path = self._make_check_csv(tmp_path)
        out_dir = tmp_path / "reports"
        out_dir.mkdir()
        with patch(TASK_ORDER_PATH, MOCK_TASK_ORDER), \
             patch("neuro_pipeline.pipeline.utils.report_generator.render_html",
                   return_value="<html>mock</html>"):
            out = generate_report(
                db_path=db_path,
                project_name="proj",
                check_results_path=csv_path,
                output_path=str(out_dir),
                session="01",
            )
        assert Path(out).parent == out_dir
        assert Path(out).name.startswith("pipeline_report_proj_")
        assert Path(out).exists()
