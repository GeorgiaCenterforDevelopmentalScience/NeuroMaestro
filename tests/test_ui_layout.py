import re
from unittest.mock import patch

import pytest
from dash import html, dcc
import dash_bootstrap_components as dbc

from tests.conftest import MOCK_CONFIG

CONFIG_PATH = "neuromaestro.pipeline.utils.config_utils.config"


def collect_ids(component, ids=None):
    if ids is None:
        ids = set()
    if hasattr(component, "id") and component.id is not None:
        ids.add(component.id)
    children = getattr(component, "children", None)
    if children is None:
        return ids
    if isinstance(children, (list, tuple)):
        for child in children:
            collect_ids(child, ids)
    elif hasattr(children, "id") or hasattr(children, "children"):
        collect_ids(children, ids)
    return ids


class TestJobMonitorLayout:

    @pytest.fixture(autouse=True)
    def layout(self):
        from neuromaestro.interface.components.job_monitor import create_job_monitor_layout
        self.component = create_job_monitor_layout()
        self.ids = collect_ids(self.component)

    def test_returns_container(self):
        assert isinstance(self.component, dbc.Container)

    def test_global_config_ids_present(self):
        for id_ in ("db-path", "work-dir-input"):
            assert id_ in self.ids

    def test_db_tab_ids_present(self):
        for id_ in ("merge-logs-btn", "merge-logs-result", "force-rebuild-btn", "force-rebuild-result"):
            assert id_ in self.ids

    def test_query_tab_ids_present(self):
        for id_ in (
            "query-type", "subject-filter", "session-filter", "task-filter", "status-filter",
            "date-range", "execute-sql-query-btn", "export-csv-btn", "export-status",
            "sql-query-results", "sql-query-charts",
            "wrapper-task-filter", "wrapper-job-id", "load-wrapper-btn", "wrapper-inspect-result",
        ):
            assert id_ in self.ids

    def test_qa_tab_ids_present(self):
        for id_ in (
            "check-project-name", "check-subjects", "check-task-filter",
            "check-session", "check-prefix", "run-output-check-btn",
            "export-check-csv-btn", "output-check-result",
            "report-project", "report-session", "report-check-results",
            "report-output-path", "generate-report-btn", "generate-report-result",
        ):
            assert id_ in self.ids


class TestAnalysisControlLayout:

    @pytest.fixture(autouse=True)
    def layout(self):
        from neuromaestro.interface.components.analysis_control import create_analysis_control_layout
        self.component = create_analysis_control_layout()
        self.ids = collect_ids(self.component)

    def test_setup_and_subject_ids_present(self):
        for id_ in (
            "config-dir-input", "apply-config-dir-btn", "init-study-btn", "config-dir-status",
            "subject-prefix", "current-dir", "detect-subjects-btn", "clear-subjects-btn",
            "manual-subjects", "subjects-detection-result", "subjects-list-container",
        ):
            assert id_ in self.ids

    def test_pipeline_config_ids_present(self):
        for id_ in (
            "input-dir", "output-dir", "work-dir", "project-name", "session-id",
            "prep-options", "intermed-checklist", "bids-prep-checklist",
            "bids-post-checklist", "staged-prep-checklist", "staged-post-checklist",
            "mriqc-options",
        ):
            assert id_ in self.ids

    def test_execution_and_dag_ids_present(self):
        for id_ in (
            "dry-run-checkbox", "resume-checkbox", "skip-preflight-checkbox",
            "skip-bids-validation-checkbox", "generate-commands-btn",
            "execute-pipeline-btn", "execution-status", "command-preview",
            "dag-overview", "dag-reset-btn", "dag-download-btn",
        ):
            assert id_ in self.ids


class TestProjectConfigLayout:

    @pytest.fixture(autouse=True)
    def layout(self):
        from neuromaestro.interface.components.project_config import create_project_config_page
        self.component = create_project_config_page()
        self.ids = collect_ids(self.component)

    def test_project_config_tab_ids_present(self):
        for id_ in ("new-project-name", "generate-new-config-btn", "load-config-btn",
                    "new-config-result", "yaml-editor", "save-config-btn",
                    "validate-config-btn", "yaml-validation-result"):
            assert id_ in self.ids

    def test_results_check_tab_ids_present(self):
        for id_ in ("checks-project-name", "load-checks-btn", "new-checks-btn",
                    "checks-yaml-editor", "save-checks-btn", "validate-checks-btn",
                    "checks-validation-result"):
            assert id_ in self.ids

    def test_global_config_tab_ids_present(self):
        for id_ in ("load-global-config-btn", "global-config-editor",
                    "save-global-config-btn", "validate-global-config-btn",
                    "global-config-result"):
            assert id_ in self.ids

    def test_hpc_config_tab_ids_present(self):
        for id_ in ("load-hpc-config-btn", "hpc-config-editor",
                    "save-hpc-config-btn", "validate-hpc-config-btn",
                    "hpc-config-result"):
            assert id_ in self.ids


class TestCallbackIdsExistInLayouts:
    """Every id a callback reads or writes must exist somewhere in the layout.
    Catches renames on either side that no other test would notice."""

    @pytest.fixture(autouse=True)
    def app_ids(self):
        import neuromaestro.interface.app as app_module
        self.layout_ids = collect_ids(app_module.app.layout)

    @staticmethod
    def _referenced_ids():
        from dash import Input, Output, State

        seen = set()

        class RecordingApp:
            def callback(self, *args, **kwargs):
                for arg in args:
                    for dep in (arg if isinstance(arg, (list, tuple)) else [arg]):
                        if isinstance(dep, (Input, Output, State)):
                            seen.add(dep.component_id)
                for value in kwargs.values():
                    for dep in (value if isinstance(value, (list, tuple)) else [value]):
                        if isinstance(dep, (Input, Output, State)):
                            seen.add(dep.component_id)

                def decorator(fn):
                    return fn
                return decorator

            def clientside_callback(self, _js, *args, **kwargs):
                self.callback(*args, **kwargs)

        from neuromaestro.interface.callbacks import register_callbacks
        register_callbacks(RecordingApp())
        return seen

    def test_no_callback_references_a_missing_id(self):
        missing = sorted(self._referenced_ids() - self.layout_ids)
        assert not missing, f"callbacks reference ids absent from the layout: {missing}"


class TestAppRouting:

    @pytest.fixture(autouse=True)
    def setup(self):
        import neuromaestro.interface.app as app_module
        self._display_page = app_module.display_page
        self._SHOW = app_module._SHOW
        self._HIDE = app_module._HIDE

    def test_root_shows_analysis_control(self):
        ac, pc, jm, _ = self._display_page("/")
        assert ac == self._SHOW
        assert pc == self._HIDE
        assert jm == self._HIDE

    def test_analysis_control_route(self):
        ac, pc, jm, _ = self._display_page("/analysis-control")
        assert ac == self._SHOW

    def test_job_monitor_route(self):
        ac, pc, jm, _ = self._display_page("/job-monitor")
        assert jm == self._SHOW
        assert ac == self._HIDE

    def test_project_config_route(self):
        ac, pc, jm, _ = self._display_page("/project-config")
        assert pc == self._SHOW
        assert ac == self._HIDE

    def test_unknown_route_defaults_to_analysis_control(self):
        ac, pc, jm, _ = self._display_page("/nonexistent")
        assert ac == self._SHOW


class TestReportHtml:

    @pytest.fixture(autouse=True)
    def imports(self):
        from neuromaestro.pipeline.utils.report_html import render_html
        self.render_html = render_html

    def _minimal_html(self, **overrides):
        session        = overrides.pop("session", None)
        metadata       = overrides.pop("metadata", {})
        # deliberately not "test": that substring occurs in unrelated markup
        project_name   = overrides.pop("project_name", "qzx_project")
        sess_data = dict(
            session=session,
            task_summary=overrides.pop("task_summary", []),
            job_status=overrides.pop("job_status", []),
            all_subjects=overrides.pop("all_subjects", []),
            all_tasks=overrides.pop("all_tasks", []),
            all_runs=overrides.pop("all_runs", []),
            failed_jobs=overrides.pop("failed_jobs", []),
            check_df=overrides.pop("check_df", None),
            wrapper_scripts=overrides.pop("wrapper_scripts", []),
        )
        return self.render_html(
            metadata=metadata,
            sessions_data=[sess_data],
            project_name=project_name,
            session=session,
        )

    def test_renders_without_data(self):
        html = self._minimal_html()
        assert "Pipeline Report" in html
        assert "qzx_project" in html

    # the bare class names also occur in the embedded CSS, so match rendered markup
    @staticmethod
    def _cells(html):
        return re.findall(r'<td class="cell-(ok|fail|notrun)">', html)

    @staticmethod
    def _dots(html):
        return re.findall(r'<span class="dot dot-(ok|fail|notrun)"></span>', html)

    def test_renders_with_session(self):
        html = self._minimal_html(session="01")
        assert "Session: <strong>01</strong>" in html
        assert "<h2>Session 01</h2>" in html

    def test_status_matrix_renders_subjects_and_tasks(self):
        job_status = [
            {"subject": "001", "task_name": "recon", "status": "SUCCESS"},
            {"subject": "002", "task_name": "recon", "status": "FAILED"},
        ]
        # without config every task reads as a group task, and recon is an array task
        with patch(CONFIG_PATH, MOCK_CONFIG):
            html = self._minimal_html(
                job_status=job_status,
                all_subjects=["001", "002"],
                all_tasks=["recon"],
            )
        assert "<th>Task</th><th>001</th><th>002</th>" in html
        assert "<td>recon</td>" in html
        assert self._cells(html) == ["ok", "fail"]

    def test_group_task_result_fills_every_subject_cell(self):
        job_status = [{"subject": "001", "task_name": "mriqc_post", "status": "FAILED"}]
        with patch(CONFIG_PATH, MOCK_CONFIG):
            html = self._minimal_html(
                job_status=job_status,
                all_subjects=["001", "002"],
                all_tasks=["mriqc_post"],
            )
        assert self._cells(html) == ["fail", "fail"]

    def test_history_section_hidden_for_single_run(self):
        single_run = [{"label": "2026-01-01", "tasks": "recon", "jobs": []}]
        html = self._minimal_html(all_runs=single_run)
        assert "Run history" not in html

    def test_history_matrix_renders_for_multiple_runs(self):
        runs = [
            {"label": "2026-01-01", "tasks": "recon",
             "jobs": [{"subject": "001", "task_name": "recon", "status": "SUCCESS"}]},
            {"label": "2026-01-15", "tasks": "recon",
             "jobs": [{"subject": "001", "task_name": "recon", "status": "FAILED"}]},
        ]
        html = self._minimal_html(all_runs=runs, all_tasks=["recon"])
        assert "Run history" in html
        assert self._dots(html) == ["ok", "fail"]

    def test_check_results_dot_matrix_renders(self):
        import pandas as pd
        # check_type values as output_checker writes them
        check_df = pd.DataFrame([
            {"task": "recon", "subject": "001", "session": "01",
             "check_type": "required_files", "pattern": "*.nii", "actual": 0, "status": "FAIL"},
            {"task": "recon", "subject": "002", "session": "01",
             "check_type": "required_files", "pattern": "*.nii", "actual": 1, "status": "PASS"},
            {"task": "recon", "subject": "001", "session": "01",
             "check_type": "count_check:anat", "pattern": "*.nii.gz", "actual": 2, "status": "PASS"},
            {"task": "recon", "subject": "002", "session": "01",
             "check_type": "count_check:anat", "pattern": "*.nii.gz", "actual": 2, "status": "PASS"},
        ])
        html = self._minimal_html(check_df=check_df)
        assert self._dots(html) == ["fail", "ok", "ok", "ok"]
        assert '<span class="fail">1 failed</span>' in html
        assert "Failed checks (1)" in html
        assert "<td>recon</td><td>001</td>" in html
        assert "<td>recon</td><td>002</td>" not in html

    def test_check_results_all_pass_hides_detail(self):
        import pandas as pd
        check_df = pd.DataFrame([
            {"task": "recon", "subject": "001", "session": "01",
             "check_type": "required_files", "pattern": "*.nii", "actual": 1, "status": "PASS"},
        ])
        html = self._minimal_html(check_df=check_df)
        assert "All passed" in html
        assert "Failed checks" not in html

    def test_failed_jobs_collapsed_by_task(self):
        failed = [
            {"subject": "001", "task_name": "recon", "start_time": "2026-01-01", "exit_code": 1,
             "stdout": "error msg", "stderr": ""},
            {"subject": "002", "task_name": "recon", "start_time": "2026-01-01", "exit_code": 1,
             "stdout": "", "stderr": ""},
        ]
        html = self._minimal_html(failed_jobs=failed)
        assert "recon — 2 failed" in html
        assert "001" in html
