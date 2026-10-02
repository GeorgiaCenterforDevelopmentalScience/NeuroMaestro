"""
test_job_db.py

Tests for pipeline/utils/job_db.py:
  - get_db_connection: all tables and indexes created
  - log_job_start: JSONL file created with correct content
  - log_job_end: resolves its own log by job_id and subject, raises when absent
  - log_pipeline_execution: returns execution_id; serialises subjects correctly
  - update_pipeline_execution: appends update record; silent when file missing
  - log_command_output: truncates stdout/stderr to last 50 lines
  - query_pipeline_executions / query_jobs: filter logic on a pre-populated SQLite
"""

import json
import os
import sqlite3
import pytest
import typer
from pathlib import Path

from neuromaestro.pipeline.utils.job_db import (
    get_db_connection,
    log_job_start,
    log_job_end,
    log_pipeline_execution,
    update_pipeline_execution,
    log_command_output,
    query_pipeline_executions,
    query_jobs,
)


# ---------------------------------------------------------------------------
# get_db_connection — schema and indexes
# ---------------------------------------------------------------------------

class TestGetDbConnection:

    def test_all_tables_created(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = get_db_connection(db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert {"job_status", "pipeline_executions", "command_outputs", "wrapper_scripts"} <= tables

    def test_indexes_created(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = get_db_connection(db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert "idx_job_status_lookup" in indexes
        assert "idx_wrapper_execution" in indexes
        assert "idx_command_outputs_lookup" in indexes

    def test_creates_missing_directory(self, tmp_path):
        db_path = str(tmp_path / "nested" / "dir" / "test.db")
        conn = get_db_connection(db_path)
        conn.close()
        assert Path(db_path).exists()

    def test_idempotent_second_call(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = get_db_connection(db_path)
        conn.execute("INSERT INTO job_status (subject, task_name) VALUES ('001', 'recon')")
        conn.commit()
        conn.close()

        conn2 = get_db_connection(db_path)
        # re-running CREATE TABLE must not drop what a previous run wrote
        rows = conn2.execute("SELECT subject, task_name FROM job_status").fetchall()
        conn2.close()
        assert rows == [("001", "recon")]


# ---------------------------------------------------------------------------
# log_job_start
# ---------------------------------------------------------------------------

class TestLogJobStart:

    def test_creates_jsonl_with_start_event(self, tmp_path):
        db_path = str(tmp_path / "db" / "pipeline_jobs.db")
        log_job_start("001", "recon", session="01", job_id="12345", db_path=db_path)
        json_dir = tmp_path / "db" / "json" / "recon"
        files = list(json_dir.glob("*.jsonl"))
        assert len(files) == 1
        record = json.loads(files[0].read_text().strip())
        assert record["event"] == "start"
        assert record["subject"] == "001"
        assert record["task_name"] == "recon"
        assert record["session"] == "01"
        assert record["job_id"] == "12345"

    def test_file_named_by_job_id(self, tmp_path):
        db_path = str(tmp_path / "db" / "pipeline_jobs.db")
        log_job_start("001", "recon", job_id="42", db_path=db_path)
        json_dir = tmp_path / "db" / "json" / "recon"
        files = list(json_dir.glob("42_*.jsonl"))
        assert len(files) == 1


# ---------------------------------------------------------------------------
# log_job_end
# ---------------------------------------------------------------------------

class TestLogJobEnd:

    def test_appends_end_event_by_job_id(self, tmp_path):
        db_path = str(tmp_path / "db" / "pipeline_jobs.db")
        log_job_start("001", "recon", session="01", job_id="12345", db_path=db_path)
        log_job_end("001", "recon", "COMPLETED", session="01", job_id="12345", db_path=db_path)

        json_dir = tmp_path / "db" / "json" / "recon"
        files = list(json_dir.glob("*.jsonl"))
        assert len(files) == 1
        lines = files[0].read_text().strip().splitlines()
        assert len(lines) == 2
        end_record = json.loads(lines[1])
        assert end_record["event"] == "end"
        assert end_record["status"] == "COMPLETED"

    def test_unmatched_job_id_raises_instead_of_guessing(self, tmp_path):
        # The regression: it fell back to the most recently written file in the
        # directory, which belongs to whichever array task logged last
        db_path = str(tmp_path / "db" / "pipeline_jobs.db")
        json_dir = tmp_path / "db" / "json" / "recon"
        json_dir.mkdir(parents=True)
        other = json_dir / "unknown_000000.jsonl"
        other.write_text(json.dumps(
            {"event": "start", "subject": "002", "session": "01"}) + "\n")

        with pytest.raises(typer.Exit) as excinfo:
            log_job_end("001", "recon", "FAILED", session="01",
                        job_id="nonexistent_id", db_path=db_path)
        assert excinfo.value.exit_code == 1

        assert len(other.read_text().strip().splitlines()) == 1

    def test_subject_disambiguates_when_there_is_no_job_id(self, tmp_path):
        # Outside SLURM every task of one name writes unknown_*.jsonl
        db_path = str(tmp_path / "db" / "pipeline_jobs.db")
        json_dir = tmp_path / "db" / "json" / "recon"
        json_dir.mkdir(parents=True)

        mine = json_dir / "unknown_100.jsonl"
        mine.write_text(json.dumps(
            {"event": "start", "subject": "001", "session": "01"}) + "\n")
        newer = json_dir / "unknown_200.jsonl"
        newer.write_text(json.dumps(
            {"event": "start", "subject": "002", "session": "01"}) + "\n")
        os.utime(newer, (2_000_000_000, 2_000_000_000))

        log_job_end("001", "recon", "SUCCESS", session="01", job_id="",
                    db_path=db_path)

        assert len(mine.read_text().strip().splitlines()) == 2
        assert len(newer.read_text().strip().splitlines()) == 1

    def test_requeued_job_ends_in_its_latest_start_log(self, tmp_path):
        # a requeue writes a second start log with the same job id, subject and session
        db_path = str(tmp_path / "db" / "pipeline_jobs.db")
        json_dir = tmp_path / "db" / "json" / "recon"
        json_dir.mkdir(parents=True)
        start = json.dumps({"event": "start", "subject": "001", "session": "01"}) + "\n"
        first = json_dir / "77_100.jsonl"
        first.write_text(start)
        os.utime(first, (1_000_000_000, 1_000_000_000))
        requeued = json_dir / "77_200.jsonl"
        requeued.write_text(start)
        os.utime(requeued, (2_000_000_000, 2_000_000_000))

        log_job_end("001", "recon", "SUCCESS", session="01", job_id="77", db_path=db_path)

        assert len(requeued.read_text().strip().splitlines()) == 2
        assert len(first.read_text().strip().splitlines()) == 1

    def test_session_is_part_of_the_identity(self, tmp_path):
        db_path = str(tmp_path / "db" / "pipeline_jobs.db")
        log_job_start("001", "recon", session="01", job_id="900", db_path=db_path)

        with pytest.raises(typer.Exit) as excinfo:
            log_job_end("001", "recon", "SUCCESS", session="02", job_id="900",
                        db_path=db_path)
        assert excinfo.value.exit_code == 1

    def test_missing_json_dir_raises(self, tmp_path):
        # Returning 0 here meant warn_if_failed in the wrapper never fired, so
        # a job absent from the database left no trace in its own log
        db_path = str(tmp_path / "db" / "pipeline_jobs.db")
        with pytest.raises(typer.Exit) as excinfo:
            log_job_end("001", "recon", "COMPLETED", db_path=db_path)
        assert excinfo.value.exit_code == 1


# ---------------------------------------------------------------------------
# log_pipeline_execution + update_pipeline_execution
# ---------------------------------------------------------------------------

class TestLogPipelineExecution:

    def test_returns_integer_execution_id(self, tmp_path):
        db_path = str(tmp_path / "db" / "pipeline_jobs.db")
        eid = log_pipeline_execution(
            command_line="neuromaestro run",
            project_name="proj",
            input_dir="/in",
            output_dir="/out",
            work_dir="/work",
            db_path=db_path,
        )
        assert isinstance(eid, int)

    def test_subjects_list_serialised_as_csv(self, tmp_path):
        db_path = str(tmp_path / "db" / "pipeline_jobs.db")
        log_pipeline_execution(
            command_line="cmd",
            project_name="proj",
            input_dir="/in",
            output_dir="/out",
            work_dir="/work",
            subjects=["001", "002", "003"],
            db_path=db_path,
        )
        json_dir = tmp_path / "db" / "json" / "_pipeline"
        records = [
            json.loads(line)
            for f in json_dir.glob("*.jsonl")
            for line in f.read_text().splitlines()
            if line
        ]
        start = next(r for r in records if r["event"] == "pipeline_start")
        assert start["subjects"] == "001,002,003"

    def test_subjects_string_preserved(self, tmp_path):
        db_path = str(tmp_path / "db" / "pipeline_jobs.db")
        log_pipeline_execution(
            command_line="cmd",
            project_name="proj",
            input_dir="/in",
            output_dir="/out",
            work_dir="/work",
            subjects="001,002",
            db_path=db_path,
        )
        json_dir = tmp_path / "db" / "json" / "_pipeline"
        records = [
            json.loads(line)
            for f in json_dir.glob("*.jsonl")
            for line in f.read_text().splitlines()
            if line
        ]
        start = next(r for r in records if r["event"] == "pipeline_start")
        assert start["subjects"] == "001,002"

    def test_tasks_list_serialised_as_csv(self, tmp_path):
        db_path = str(tmp_path / "db" / "pipeline_jobs.db")
        log_pipeline_execution(
            command_line="cmd",
            project_name="proj",
            input_dir="/in",
            output_dir="/out",
            work_dir="/work",
            requested_tasks=["recon", "volume"],
            db_path=db_path,
        )
        json_dir = tmp_path / "db" / "json" / "_pipeline"
        records = [
            json.loads(line)
            for f in json_dir.glob("*.jsonl")
            for line in f.read_text().splitlines()
            if line
        ]
        start = next(r for r in records if r["event"] == "pipeline_start")
        assert start["requested_tasks"] == "recon,volume"


class TestUpdatePipelineExecution:

    def test_appends_update_record(self, tmp_path):
        db_path = str(tmp_path / "db" / "pipeline_jobs.db")
        eid = log_pipeline_execution(
            command_line="cmd",
            project_name="proj",
            input_dir="/in",
            output_dir="/out",
            work_dir="/work",
            db_path=db_path,
        )
        update_pipeline_execution(eid, status="COMPLETED", db_path=db_path)

        json_dir = tmp_path / "db" / "json" / "_pipeline"
        jsonl_file = json_dir / f"execution_{eid}.jsonl"
        lines = jsonl_file.read_text().strip().splitlines()
        assert len(lines) == 2
        update_record = json.loads(lines[1])
        assert update_record["event"] == "pipeline_update"
        assert update_record["status"] == "COMPLETED"

    def test_missing_file_does_not_raise(self, tmp_path, capsys):
        db_path = str(tmp_path / "db" / "pipeline_jobs.db")
        update_pipeline_execution(999999, status="COMPLETED", db_path=db_path)

        # warns instead of raising, and does not fabricate the missing log
        assert "not found" in capsys.readouterr().err
        assert not (tmp_path / "db" / "json").exists()


# ---------------------------------------------------------------------------
# log_command_output — stdout/stderr truncation
# ---------------------------------------------------------------------------

class TestLogCommandOutput:

    def _setup_job(self, tmp_path, job_id="99"):
        db_path = str(tmp_path / "db" / "pipeline_jobs.db")
        log_job_start("001", "recon", job_id=job_id, db_path=db_path)
        return db_path

    def _read_command_record(self, tmp_path):
        json_dir = tmp_path / "db" / "json" / "recon"
        lines = list(json_dir.glob("*.jsonl"))[0].read_text().strip().splitlines()
        return json.loads(lines[1])

    def test_long_stdout_truncated_to_last_50_lines(self, tmp_path):
        db_path = self._setup_job(tmp_path)
        long_out = "\n".join(f"line {i}" for i in range(100))
        log_command_output("001", "recon", "script.sh", "cmd",
                           stdout=long_out, job_id="99", db_path=db_path)
        record = self._read_command_record(tmp_path)
        result_lines = record["stdout"].split("\n")
        assert len(result_lines) == 50
        assert result_lines[-1] == "line 99"

    def test_short_stdout_unchanged(self, tmp_path):
        db_path = self._setup_job(tmp_path)
        short_out = "\n".join(f"line {i}" for i in range(10))
        log_command_output("001", "recon", "script.sh", "cmd",
                           stdout=short_out, job_id="99", db_path=db_path)
        record = self._read_command_record(tmp_path)
        assert len(record["stdout"].split("\n")) == 10

    def test_long_stderr_truncated(self, tmp_path):
        db_path = self._setup_job(tmp_path)
        long_err = "\n".join(f"err {i}" for i in range(80))
        log_command_output("001", "recon", "script.sh", "cmd",
                           stderr=long_err, job_id="99", db_path=db_path)
        record = self._read_command_record(tmp_path)
        assert len(record["stderr"].split("\n")) == 50

    def test_missing_json_dir_raises(self, tmp_path):
        db_path = str(tmp_path / "db" / "pipeline_jobs.db")
        with pytest.raises(typer.Exit) as excinfo:
            log_command_output("001", "recon", "script.sh", "cmd", db_path=db_path)
        assert excinfo.value.exit_code == 1

    def test_output_goes_to_its_own_subject(self, tmp_path):
        db_path = str(tmp_path / "db" / "pipeline_jobs.db")
        json_dir = tmp_path / "db" / "json" / "recon"
        json_dir.mkdir(parents=True)

        mine = json_dir / "unknown_100.jsonl"
        mine.write_text(json.dumps({"event": "start", "subject": "001"}) + "\n")
        newer = json_dir / "unknown_200.jsonl"
        newer.write_text(json.dumps({"event": "start", "subject": "002"}) + "\n")
        os.utime(newer, (2_000_000_000, 2_000_000_000))

        log_command_output("001", "recon", "script.sh", "cmd",
                           stdout="hello", job_id="", db_path=db_path)

        assert len(mine.read_text().strip().splitlines()) == 2
        assert len(newer.read_text().strip().splitlines()) == 1


# ---------------------------------------------------------------------------
# query_pipeline_executions / query_jobs
# ---------------------------------------------------------------------------

class TestQueryFunctions:

    def _make_db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = get_db_connection(db_path)
        conn.execute(
            "INSERT INTO pipeline_executions "
            "(execution_id, project_name, session, status, subjects, requested_tasks, dry_run, total_jobs) "
            "VALUES (1001, 'proj_a', '01', 'COMPLETED', '001,002', 'recon', 0, 2)"
        )
        conn.execute(
            "INSERT INTO pipeline_executions "
            "(execution_id, project_name, session, status, subjects, requested_tasks, dry_run, total_jobs) "
            "VALUES (1002, 'proj_b', '02', 'RUNNING', '003', 'volume', 0, 1)"
        )
        conn.execute(
            "INSERT INTO job_status "
            "(execution_id, subject, task_name, session, status) "
            "VALUES (1001, '001', 'recon', '01', 'COMPLETED')"
        )
        conn.execute(
            "INSERT INTO job_status "
            "(execution_id, subject, task_name, session, status) "
            "VALUES (1001, '002', 'recon', '01', 'FAILED')"
        )
        conn.commit()
        conn.close()
        return db_path

    # pipeline_executions queries
    # col order: id(0), execution_id(1), execution_time(2), command_line(3),
    #            project_name(4), session(5), ..., total_jobs(12), status(13), error_msg(14)

    def test_query_executions_filter_by_project(self, tmp_path):
        db_path = self._make_db(tmp_path)
        rows = query_pipeline_executions(project_name="proj_a", db_path=db_path)
        assert len(rows) == 1
        assert rows[0][4] == "proj_a"

    def test_query_executions_filter_by_session(self, tmp_path):
        db_path = self._make_db(tmp_path)
        rows = query_pipeline_executions(session="02", db_path=db_path)
        assert len(rows) == 1
        assert rows[0][5] == "02"

    def test_query_executions_filter_by_status(self, tmp_path):
        db_path = self._make_db(tmp_path)
        rows = query_pipeline_executions(status="RUNNING", db_path=db_path)
        assert len(rows) == 1
        assert rows[0][13] == "RUNNING"

    def test_query_executions_no_match_returns_empty(self, tmp_path):
        db_path = self._make_db(tmp_path)
        rows = query_pipeline_executions(project_name="nonexistent", db_path=db_path)
        assert rows == []

    def test_query_executions_default_returns_all(self, tmp_path):
        db_path = self._make_db(tmp_path)
        rows = query_pipeline_executions(limit=10, db_path=db_path)
        assert len(rows) == 2

    # job_status queries
    # col order: id(0), execution_id(1), subject(2), task_name(3), session(4),
    #            start_time(5), end_time(6), status(7), exit_code(8), ...

    def test_query_jobs_filter_by_subject(self, tmp_path):
        db_path = self._make_db(tmp_path)
        rows = query_jobs(subject="001", db_path=db_path)
        assert len(rows) == 1
        assert rows[0][2] == "001"

    def test_query_jobs_filter_by_status(self, tmp_path):
        db_path = self._make_db(tmp_path)
        rows = query_jobs(status="FAILED", db_path=db_path)
        assert len(rows) == 1
        assert rows[0][7] == "FAILED"

    @staticmethod
    def _add_other_job(db_path):
        # the fixture's jobs are all recon/01, which no task or session filter can tell apart
        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO job_status (execution_id, subject, task_name, session, status) "
                     "VALUES (1002, '003', 'volume', '02', 'SUCCESS')")
        conn.commit()
        conn.close()

    def test_query_jobs_filter_by_task(self, tmp_path):
        db_path = self._make_db(tmp_path)
        self._add_other_job(db_path)
        rows = query_jobs(task_name="recon", db_path=db_path)
        assert sorted(r[2] for r in rows) == ["001", "002"]

    def test_query_jobs_filter_by_session(self, tmp_path):
        db_path = self._make_db(tmp_path)
        self._add_other_job(db_path)
        rows = query_jobs(session="02", db_path=db_path)
        assert [r[2] for r in rows] == ["003"]

    def test_query_jobs_no_match_returns_empty(self, tmp_path):
        db_path = self._make_db(tmp_path)
        rows = query_jobs(subject="999", db_path=db_path)
        assert rows == []


class TestQueryOutput:
    """What the query commands print, through the CLI that run() tells users to call."""

    @staticmethod
    def _insert(db_path, table, rows):
        conn = get_db_connection(db_path)
        for row in rows:
            cols = ", ".join(row)
            conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
        conn.commit()
        conn.close()

    @staticmethod
    def _cli(*args):
        from typer.testing import CliRunner
        from neuromaestro.pipeline.utils.job_db import app
        result = CliRunner().invoke(app, list(args))
        assert result.exit_code == 0, result.output
        return result.output.splitlines()

    FAILED_JOB = dict(execution_id=1001, subject="001", task_name="recon", session="01",
                      start_time="2026-10-01T10:00:00", end_time="2026-10-01T12:30:00", status="FAILED",
                      exit_code=1, error_msg="segfault", duration_hours=2.5, log_path="/logs/recon_1.out",
                      job_id="555_1", node_name="node7")
    RUNNING_JOB = dict(execution_id=1001, subject="002", task_name="recon", session=None,
                       start_time="2026-10-01T11:00:00", status="RUNNING", log_path="/logs/recon_2.out",
                       job_id="555_2", node_name="node8")

    def test_job_fields_are_printed_from_the_right_columns(self, tmp_path):
        db = str(tmp_path / "jobs.db")
        self._insert(db, "job_status", [self.FAILED_JOB, self.RUNNING_JOB])
        # newest start first
        assert self._cli("query_jobs", "--db-path", db) == [
            "Subject: 002 | Task: recon | Session: N/A",
            "Status: RUNNING | Exit code: None",
            "Start: 2026-10-01T11:00:00",
            "End: Running",
            "Log: /logs/recon_2.out",
            "Job ID: 555_2 | Node: node8",
            "-" * 60,
            "Subject: 001 | Task: recon | Session: 01",
            "Status: FAILED | Exit code: 1",
            "Start: 2026-10-01T10:00:00",
            "End: 2026-10-01T12:30:00",
            "Duration: 2.500h",
            "Error: segfault",
            "Log: /logs/recon_1.out",
            "Job ID: 555_1 | Node: node7",
            "-" * 60,
        ]

    def test_job_filters_parse_from_the_command_line(self, tmp_path):
        db = str(tmp_path / "jobs.db")
        self._insert(db, "job_status", [self.FAILED_JOB, self.RUNNING_JOB])
        lines = self._cli("query_jobs", "--task-name", "recon", "--status", "FAILED", "--subject", "001",
                          "--session", "01", "--db-path", db)
        assert [l for l in lines if l.startswith("Subject:")] == ["Subject: 001 | Task: recon | Session: 01"]

    @pytest.mark.parametrize("args, shown", [((), 20), (("--limit", "3"), 3)])
    def test_job_limit(self, tmp_path, args, shown):
        db = str(tmp_path / "jobs.db")
        self._insert(db, "job_status", [{**self.FAILED_JOB, "subject": f"{i:03d}",
                                         "start_time": f"2026-10-01T10:{i:02d}:00"} for i in range(21)])
        lines = self._cli("query_jobs", *args, "--db-path", db)
        assert len([l for l in lines if l.startswith("Subject:")]) == shown

    def test_no_jobs(self, tmp_path):
        db = str(tmp_path / "jobs.db")
        self._insert(db, "job_status", [])
        assert self._cli("query_jobs", "--db-path", db) == ["No matching records found"]

    FAILED_RUN = dict(execution_id=1001, execution_time="2026-10-01T10:00:00", command_line="neuromaestro run",
                      project_name="proj_a", session="01", subjects="001,002", requested_tasks="recon",
                      dry_run=0, total_jobs=2, status="FAILED", error_msg="scheduler down")
    BARE_RUN = dict(execution_id=1002, execution_time="2026-10-01T11:00:00", project_name="proj_b",
                    total_jobs=0, status="COMPLETED")

    def test_execution_fields_are_printed_from_the_right_columns(self, tmp_path):
        db = str(tmp_path / "jobs.db")
        self._insert(db, "pipeline_executions", [self.FAILED_RUN, self.BARE_RUN])
        assert self._cli("query_pipeline_executions", "--db-path", db) == [
            "Execution ID: 1002",
            "Project: proj_b",
            "Session: N/A",
            "Status: COMPLETED",
            "Execution time: 2026-10-01T11:00:00",
            "Subjects: N/A",
            "Tasks: N/A",
            "Total jobs: 0",
            "-" * 40,
            "Execution ID: 1001",
            "Project: proj_a",
            "Session: 01",
            "Status: FAILED",
            "Execution time: 2026-10-01T10:00:00",
            "Subjects: 001,002",
            "Tasks: recon",
            "Total jobs: 2",
            "Error: scheduler down",
            "-" * 40,
        ]

    def test_execution_filters_parse_from_the_command_line(self, tmp_path):
        db = str(tmp_path / "jobs.db")
        self._insert(db, "pipeline_executions", [self.FAILED_RUN, self.BARE_RUN])
        lines = self._cli("query_pipeline_executions", "--project-name", "proj_a", "--session", "01",
                          "--status", "FAILED", "--db-path", db)
        assert [l for l in lines if l.startswith("Execution ID:")] == ["Execution ID: 1001"]

    @pytest.mark.parametrize("args, shown", [((), 10), (("--limit", "2"), 2)])
    def test_execution_limit(self, tmp_path, args, shown):
        db = str(tmp_path / "jobs.db")
        self._insert(db, "pipeline_executions", [{**self.BARE_RUN, "execution_id": i,
                                                  "execution_time": f"2026-10-01T10:{i:02d}:00"} for i in range(11)])
        lines = self._cli("query_pipeline_executions", *args, "--db-path", db)
        assert len([l for l in lines if l.startswith("Execution ID:")]) == shown

    def test_no_executions(self, tmp_path):
        db = str(tmp_path / "jobs.db")
        self._insert(db, "pipeline_executions", [])
        assert self._cli("query_pipeline_executions", "--db-path", db) == ["No matching records found"]
