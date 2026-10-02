"""
test_preflight.py

Tests for the pre-flight schema validation
in neuromaestro.pipeline.utils.preflight.
"""

import copy
import os
import pytest
import yaml
from pathlib import Path

from tests.conftest import MOCK_CONFIG, MOCK_HPC_CONFIG, MOCK_PROJECT_CONFIG
from neuromaestro.pipeline.utils.preflight import (
    PreflightChecker,
    PreflightResult,
    Issue,
    print_preflight_report,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_checker(project_config=None, global_config=None, hpc_config=None, **_):
    return PreflightChecker(
        project_config=project_config or MOCK_PROJECT_CONFIG,
        global_config=global_config or MOCK_CONFIG,
        hpc_config=hpc_config if hpc_config is not None else MOCK_HPC_CONFIG,
    )

# ---------------------------------------------------------------------------
# PreflightResult
# ---------------------------------------------------------------------------

class TestPreflightResult:

    def test_ok_when_no_issues(self):
        r = PreflightResult()
        assert r.ok is True

    def test_not_ok_when_has_error(self):
        r = PreflightResult(issues=[Issue("ERROR", "schema", "bad")])
        assert r.ok is False

    def test_ok_when_only_warnings(self):
        r = PreflightResult(issues=[Issue("WARNING", "containers", "missing")])
        assert r.ok is True

    def test_errors_property_filters(self):
        r = PreflightResult(issues=[
            Issue("ERROR", "schema", "e"),
            Issue("WARNING", "containers", "w"),
        ])
        assert len(r.errors) == 1
        assert len(r.warnings) == 1


# ===========================================================================
# Schema checks
# ===========================================================================

class TestSchemaChecks:

    # --- Required top-level keys -------------------------------------------

    def test_passes_valid_project_config(self, tmp_path):
        checker = make_checker(tmp_path=tmp_path)
        checker.check_schema()
        errors = [i for i in checker._issues if i.severity == "ERROR" and i.category == "schema"]
        assert errors == [], f"Unexpected schema errors: {errors}"

    @pytest.mark.parametrize("missing_key", ["prefix", "scripts_dir", "envir_dir", "database", "tasks"])
    def test_error_for_missing_required_key(self, missing_key, tmp_path):
        pc = {k: v for k, v in MOCK_PROJECT_CONFIG.items() if k != missing_key}
        checker = make_checker(project_config=pc, tmp_path=tmp_path)
        checker.check_schema()
        messages = [i.message for i in checker._issues if i.severity == "ERROR"]
        assert any(missing_key in m for m in messages)

    def test_error_when_container_dir_missing_from_envir_dir(self, tmp_path):
        pc = {**MOCK_PROJECT_CONFIG, "envir_dir": {"template_dir": "/some/path"}}
        checker = make_checker(project_config=pc, tmp_path=tmp_path)
        checker.check_schema()
        messages = [i.message for i in checker._issues if i.severity == "ERROR"]
        assert any("container_dir" in m for m in messages)

    def test_error_when_db_path_missing(self, tmp_path):
        pc = {**MOCK_PROJECT_CONFIG, "database": {}}
        checker = make_checker(project_config=pc, tmp_path=tmp_path)
        checker.check_schema()
        messages = [i.message for i in checker._issues if i.severity == "ERROR"]
        assert any("db_path" in m for m in messages)

    # --- Tasks entry references --------------------------------------------

    def test_error_when_task_not_in_global_config(self, tmp_path):
        pc = {**MOCK_PROJECT_CONFIG, "tasks": {"nonexistent_task": {}}}
        checker = make_checker(project_config=pc, tmp_path=tmp_path)
        checker.check_schema()
        messages = [i.message for i in checker._issues if i.severity == "ERROR"]
        assert any("nonexistent_task" in m for m in messages)

    def test_no_error_for_known_task(self, tmp_path):
        # unzip exists in MOCK_CONFIG
        pc = {**MOCK_PROJECT_CONFIG, "tasks": {"unzip": {"environ": ["data_manage_1"]}}}
        checker = make_checker(project_config=pc, tmp_path=tmp_path)
        checker.check_schema()
        task_errors = [
            i for i in checker._issues
            if i.severity == "ERROR" and "unzip" in i.message
        ]
        assert task_errors == []

    def test_error_when_tasks_is_not_a_dict(self, tmp_path):
        pc = {**MOCK_PROJECT_CONFIG, "tasks": "not_a_dict"}
        checker = make_checker(project_config=pc, tmp_path=tmp_path)
        checker.check_schema()
        messages = [i.message for i in checker._issues if i.severity == "ERROR"]
        assert any("must be a mapping" in m for m in messages)

    def test_error_when_task_entry_is_not_a_dict(self, tmp_path):
        pc = {**MOCK_PROJECT_CONFIG, "tasks": {"unzip": "invalid"}}
        checker = make_checker(project_config=pc, tmp_path=tmp_path)
        checker.check_schema()
        messages = [i.message for i in checker._issues if i.severity == "ERROR"]
        assert any("must be a mapping" in m for m in messages)

    # --- Environ references ------------------------------------------------

    def test_error_when_environ_module_not_defined(self, tmp_path):
        pc = {**MOCK_PROJECT_CONFIG, "tasks": {"unzip": {"environ": ["nonexistent_module"]}}}
        checker = make_checker(project_config=pc, tmp_path=tmp_path)
        checker.check_schema()
        messages = [i.message for i in checker._issues if i.severity == "ERROR"]
        assert any("nonexistent_module" in m for m in messages)

    def test_no_error_for_known_module(self, tmp_path):
        # data_manage_1 is defined in MOCK_PROJECT_CONFIG.modules
        checker = make_checker(tmp_path=tmp_path)
        checker.check_schema()
        module_errors = [
            i for i in checker._issues
            if i.severity == "ERROR" and "data_manage_1" in i.message
        ]
        assert module_errors == []

    # --- Resource profile references ---------------------------------------

    def test_error_when_profile_not_in_hpc_config(self, tmp_path):
        checker = make_checker(hpc_config={"resource_profiles": {}}, tmp_path=tmp_path)
        checker.check_schema()
        profile_errors = [
            i for i in checker._issues
            if i.severity == "ERROR" and "profile" in i.message
        ]
        assert len(profile_errors) > 0

    def test_error_when_task_sets_no_profile(self, tmp_path):
        gc = copy.deepcopy(MOCK_CONFIG)
        gc["prep"][0].pop("profile")
        broken = gc["prep"][0]["name"]
        checker = make_checker(global_config=gc, tmp_path=tmp_path)
        checker.check_schema()
        assert any(
            i.severity == "ERROR" and broken in i.message and "no resource profile" in i.message
            for i in checker._issues
        )

    def test_profile_checked_without_a_project_config_entry(self, tmp_path):
        """A task is submittable with no project entry, so it must still be checked."""
        gc = copy.deepcopy(MOCK_CONFIG)
        gc["prep"][0].pop("profile")
        broken = gc["prep"][0]["name"]
        pc = {**MOCK_PROJECT_CONFIG, "tasks": {}}
        checker = make_checker(project_config=pc, global_config=gc, tmp_path=tmp_path)
        checker.check_schema()
        assert any(
            i.severity == "ERROR" and broken in i.message for i in checker._issues
        )


# ===========================================================================
# run_all integration
# ===========================================================================

class TestRunAll:

    def test_returns_preflight_result(self):
        result = make_checker().run_all()
        assert isinstance(result, PreflightResult)

    def test_clean_state_resets_between_calls(self):
        # a config that produces issues: comparing two empty lists would pass
        # even if _issues accumulated across calls
        checker = make_checker(project_config={"prefix": "sub-"})
        r1 = checker.run_all()
        r2 = checker.run_all()
        assert len(r1.issues) > 0
        assert [(i.severity, i.category, i.message) for i in r1.issues] == \
               [(i.severity, i.category, i.message) for i in r2.issues]

    def test_bad_config_produces_errors(self):
        pc = {"prefix": "sub-"}  # missing most keys
        result = make_checker(project_config=pc).run_all()
        assert not result.ok


# ===========================================================================
# print_preflight_report
# ===========================================================================

class TestPrintPreflightReport:

    def test_prints_all_passed(self, capsys):
        print_preflight_report(PreflightResult())
        out = capsys.readouterr().out
        assert "All checks passed" in out

    def test_prints_error_count(self, capsys):
        r = PreflightResult(issues=[
            Issue("ERROR", "schema", "bad key"),
            Issue("WARNING", "containers", "missing sif"),
        ])
        print_preflight_report(r)
        out = capsys.readouterr().out
        assert "1 error" in out
        assert "1 warning" in out

    def test_groups_by_category(self, capsys):
        r = PreflightResult(issues=[
            Issue("ERROR", "schema", "key missing"),
            Issue("ERROR", "scripts", "script missing"),
        ])
        print_preflight_report(r)
        out = capsys.readouterr().out
        assert "[schema]" in out
        assert "[scripts]" in out

    def test_only_warnings_no_blocking_message(self, capsys):
        r = PreflightResult(issues=[Issue("WARNING", "containers", "sif not found")])
        print_preflight_report(r)
        out = capsys.readouterr().out
        assert "No blocking errors" in out
        assert "must be resolved" not in out