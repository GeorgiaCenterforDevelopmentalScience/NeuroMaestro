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


class TestCallbackWiring:
    """Checks the decorators, which the callback tests bypass by calling the functions directly."""

    SERVER_CALLBACKS = [
        "apply_config_dir", "detect_subjects_callback", "display_page",
        "execute_pipeline_callback", "execute_sql_query_callback",
        "export_check_csv_callback", "export_csv_callback", "force_rebuild_callback",
        "generate_command_callback", "generate_new_config_callback",
        "generate_report_callback", "init_study", "load_checks_callback",
        "load_config_callback", "load_global_config_callback", "load_hpc_config_callback",
        "load_wrapper_callback", "merge_logs_callback", "reset_dag_view",
        "run_output_check_callback", "save_checks_callback", "save_config_callback",
        "save_global_config_callback", "save_hpc_config_callback", "sync_status_options",
        "toggle_sidebar", "update_dag_elements",
    ]

    # these start a subprocess or write a file, so must not fire on page load
    SIDE_EFFECTS = {
        "apply_config_dir", "init_study", "execute_pipeline_callback",
        "force_rebuild_callback", "merge_logs_callback", "run_output_check_callback",
        "export_check_csv_callback", "generate_report_callback",
        "generate_new_config_callback", "save_config_callback", "save_checks_callback",
        "save_global_config_callback", "save_hpc_config_callback",
    }

    # parameters whose name does not echo the component that feeds them
    ALIASES = {
        ("detect_subjects_callback", "directory"): "current-dir",
        ("run_output_check_callback", "work_dir"): "check-output-dir",
        ("export_check_csv_callback", "work_dir"): "check-output-dir",
        ("save_global_config_callback", "yaml_content"): "global-config-editor",
        ("save_hpc_config_callback", "yaml_content"): "hpc-config-editor",
    }
    QUALIFIERS = ("_clicks", "_value", "_data", "_input", "_raw", "_class", "_content")

    @pytest.fixture
    def wiring(self):
        import inspect
        from neuromaestro.interface.app import app
        on_load = {entry["output"]: not entry["prevent_initial_call"]
                   for entry in app._callback_list}
        return [
            (inspect.unwrap(spec["callback"]), spec["inputs"] + spec["state"], on_load[output])
            for output, spec in app.callback_map.items()
            if "callback" in spec   # clientside callbacks have no Python function
        ]

    def _fed_by(self, fn_name, param, dep):
        alias = self.ALIASES.get((fn_name, param))
        if alias is not None:
            return dep["id"] == alias
        name = param.lstrip("_")
        if not name or name == dep["property"]:
            return True
        if name.endswith("_clicks") and dep["property"] != "n_clicks":
            return False
        for suffix in self.QUALIFIERS:
            name = name.removesuffix(suffix)
        return name.replace("_", "-") in dep["id"]

    def test_every_server_callback_is_registered(self, wiring):
        # a duplicate output without allow_duplicate can replace an earlier callback
        assert sorted(fn.__name__ for fn, _, _ in wiring) == self.SERVER_CALLBACKS

    def test_arguments_follow_the_decorator_order(self, wiring):
        # Dash passes Inputs then States positionally, matched to nothing but their order
        import inspect
        mismatches = []
        for fn, deps, _ in wiring:
            params = list(inspect.signature(fn).parameters)
            if len(params) != len(deps):
                mismatches.append(f"{fn.__name__}: {len(params)} parameters, {len(deps)} dependencies")
                continue
            mismatches += [
                f"{fn.__name__}({param}) <- {dep['id']}.{dep['property']}"
                for param, dep in zip(params, deps)
                if not self._fed_by(fn.__name__, param, dep)
            ]
        assert mismatches == []

    def test_side_effects_do_not_fire_on_page_load(self, wiring):
        fires_on_load = {fn.__name__ for fn, _, on_load in wiring if on_load}
        assert self.SIDE_EFFECTS <= {fn.__name__ for fn, _, _ in wiring}
        assert sorted(self.SIDE_EFFECTS & fires_on_load) == []

    def test_shared_outputs_are_marked_allow_duplicate(self):
        # the server registers a clash silently, the browser renderer rejects it
        from collections import Counter
        from neuromaestro.interface.app import app
        unmarked = Counter()
        for key in app.callback_map:
            outputs = key.strip(".").split("...") if key.startswith("..") else [key]
            unmarked.update(o for o in outputs if "@" not in o)
        assert sorted(o for o, n in unmarked.items() if n > 1) == []


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
        assert "recon: 2 failed" in html
        assert "001" in html

    def test_failed_job_rows(self):
        failed = [
            {"subject": "001", "task_name": "recon", "start_time": "2026-01-01T10:20:30.123", "exit_code": 0,
             "stdout": "partial output"},
            {"subject": "002", "task_name": "recon", "start_time": None, "exit_code": None, "stdout": "  \n"},
        ]
        html = self._minimal_html(failed_jobs=failed)
        log = ('<details><summary style="font-size:11px;color:#888">stdout</summary>'
               '<pre>partial output</pre></details>')
        assert f'<tr><td>001</td><td class="num">0</td><td>2026-01-01T10:20</td><td>{log}</td></tr>' in html
        assert '<tr><td>002</td><td class="num">—</td><td></td><td><span style="color:#bbb">—</span></td></tr>' in html

    def test_task_summary_row(self):
        summary = [
            {"task": "recon", "ok": 3, "total": 4, "failed": 1, "not_run": 0, "dur": "1.5 h", "last": "2026-01-01"},
            {"task": "unzip", "ok": 0, "total": 0, "failed": 0, "not_run": 2, "dur": "—", "last": ""},
        ]
        html = self._minimal_html(task_summary=summary)
        assert ('<tr><td>recon</td><td class="num">3 / 4</td><td class="num">75%</td>'
                '<td class="num fail">1</td><td class="num">0</td><td>1.5 h</td><td>2026-01-01</td></tr>') in html
        assert ('<tr><td>unzip</td><td class="num">0 / 0</td><td class="num">—</td>'
                '<td class="num">0</td><td class="num">2</td><td>—</td><td></td></tr>') in html

    EMPTY_STATES = [
        '<p class="empty">No task data found.</p>',
        '<p class="empty">No data.</p>',
        '<p class="empty">No failed jobs.</p>',
        '<p class="empty">None. Every job reported as SUCCESS also passed its output checks.</p>',
        '<p class="empty">No check-results data provided (use --check-results).</p>',
        '<p class="empty">No wrapper script records found.</p>',
    ]

    def test_every_section_says_when_it_is_empty(self):
        html = self._minimal_html()
        for message in self.EMPTY_STATES:
            assert message in html

    def test_matrix_needs_both_subjects_and_tasks(self):
        assert '<p class="empty">No data.</p>' in self._minimal_html(all_subjects=["001"])
        assert '<p class="empty">No data.</p>' in self._minimal_html(all_tasks=["recon"])

    @staticmethod
    def _session(sess, **sections):
        base = dict(session=sess, task_summary=[], job_status=[], all_subjects=[], all_tasks=[], all_runs=[],
                    failed_jobs=[], check_df=None, wrapper_scripts=[])
        return {**base, **sections}

    def test_suspicious_rows_and_count(self):
        suspicious = [
            {"task": "recon", "subject": "001", "check_type": "required_files", "pattern": "*.nii",
             "reason": "FAIL: missing"},
            {"task": "recon", "subject": "001", "check_type": "count_check:anat", "pattern": "*.gz",
             "reason": "FAIL: 0/2"},
        ]
        html = self.render_html(metadata={}, sessions_data=[self._session(None, suspicious=suspicious)],
                                project_name="qzx_project", session=None)
        assert '<span class="fail">2 check(s) across 1 subject(s)</span>' in html
        assert ('<tr><td>recon</td><td>001</td><td>required_files</td>'
                '<td style="font-size:12px;font-family:monospace">*.nii</td>'
                '<td class="fail">FAIL: missing</td></tr>') in html
        assert "Every job reported as SUCCESS also passed" not in html

    def test_environment_shows_only_recorded_fields(self):
        wrappers = [
            {"task_name": "recon", "submission_time": "2026-01-01T10:20:30", "slurm_cmd": "sbatch --mem=8gb",
             "env_modules": "", "global_python": None, "global_env_vars": "  ", "execute_cmd": "execute_wrapper x.sh"},
            {"task_name": "empty_task", "submission_time": "2026-01-02", "slurm_cmd": ""},
        ]
        html = self._minimal_html(wrapper_scripts=wrappers)
        fields = re.findall(r'<strong>([^<]+)</strong></p><pre>([^<]*)</pre>', html)
        assert fields == [("SLURM command", "sbatch --mem=8gb"), ("Execute command", "execute_wrapper x.sh")]
        assert "last submitted 2026-01-01T10:20</span>" in html
        assert "empty_task" not in html

    def test_environment_with_nothing_recorded(self):
        html = self._minimal_html(wrapper_scripts=[{"task_name": "recon", "slurm_cmd": ""}])
        assert '<p class="empty">No environment data recorded.</p>' in html

    def test_check_rows_group_under_their_task_in_subject_order(self):
        import pandas as pd
        rows = [("recon", "010", "required_files", "PASS"), ("recon", "002", "required_files", "FAIL"),
                ("recon", "010", "count_check:anat", "PASS"), ("recon", "002", "count_check:anat", "PASS"),
                ("unzip", "010", "required_files", "PASS"), ("unzip", "002", "required_files", "PASS")]
        check_df = pd.DataFrame([{"task": t, "subject": s, "session": "01", "check_type": c, "pattern": "*",
                                  "actual": 0, "status": st} for t, s, c, st in rows])
        html = self._minimal_html(check_df=check_df)
        assert "<tr><th>Task</th><th>Check</th><th>002</th><th>010</th></tr>" in html
        body = re.findall(r'<tr>(?:<td class="dot-row-label" rowspan="(\d)"[^>]*>(\w+)</td>)?'
                          r'<td class="dot-row-label">(\w+)</td>', html)
        assert body == [("2", "recon", "required_files"), ("", "", "anat"), ("1", "unzip", "required_files")]
        assert self._dots(html) == ["fail", "ok", "ok", "ok", "ok", "ok"]
        assert "6 checks &nbsp;·&nbsp; " in html

    def test_matrix_orders_subjects_by_number(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            html = self._minimal_html(all_subjects=["10", "sub-9", "002"], all_tasks=["recon"])
        assert "<tr><th>Task</th><th>002</th><th>sub-9</th><th>10</th></tr>" in html

    def test_one_nav_link_and_section_per_session(self):
        html = self.render_html(metadata={}, sessions_data=[self._session("01"), self._session("02")],
                                project_name="qzx_project", session="01,02")
        assert re.findall(r'<a href="#([\w-]+)">([^<]+)</a>', html) == [
            ("summary", "Summary"), ("session-01", "Session 01"), ("session-02", "Session 02")]
        assert re.findall(r'<section id="([\w-]+)">\s*<h2>([^<]+)</h2>', html) == [
            ("session-01", "Session 01"), ("session-02", "Session 02")]

    def test_no_session_gets_a_single_jobs_section(self):
        html = self.render_html(metadata={}, sessions_data=[self._session(None)],
                                project_name="qzx_project", session=None)
        assert '<a href="#session-all">Jobs</a>' in html
        assert re.findall(r'<section id="([\w-]+)">\s*<h2>([^<]+)</h2>', html) == [("session-all", "Job Status")]
        assert "Session: <strong>" not in html

    def test_header_metadata(self):
        metadata = {"input_dir": "/in", "output_dir": "", "work_dir": "/work",
                    "execution_time": "2026-01-01T10:20:30.5", "command_line": "neuromaestro run --dry-run"}
        html = self._minimal_html(metadata=metadata)
        items = re.findall(r'<span class="meta-label">([^<]+)</span><span class="meta-val"[^>]*>([^<]+)</span>', html)
        assert items == [("Input", "/in"), ("Work", "/work"), ("Last run", "2026-01-01T10:20"),
                         ("Command", "neuromaestro run --dry-run")]
        assert re.search(r"Generated: \d{4}-\d{2}-\d{2} \d{2}:\d{2}", html)

    def test_header_without_metadata(self):
        assert 'class="meta-label"' not in self._minimal_html(metadata={})

    def test_user_text_is_escaped(self):
        hostile = '<script>alert("x")</script>&'
        escaped = "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;&amp;"
        failed = [{"subject": hostile, "task_name": hostile, "start_time": "", "exit_code": 1, "stdout": hostile}]
        html = self.render_html(
            metadata={"command_line": hostile, "work_dir": hostile},
            sessions_data=[self._session(hostile, failed_jobs=failed, all_subjects=[hostile], all_tasks=[hostile])],
            project_name=hostile, session=hostile,
        )
        assert "<script>" not in html
        assert f'<a href="#session-{escaped}">Session {escaped}</a>' in html
        assert f'<section id="session-{escaped}">' in html
        assert f"<h2>Session {escaped}</h2>" in html
        assert f"Project: <strong>{escaped}</strong>" in html
        assert f'<span class="meta-label">Work</span><span class="meta-val">{escaped}</span>' in html
        assert f'font-size:12px">{escaped}</span>' in html
        assert f"<th>{escaped}</th>" in html
        assert f"<summary>{escaped}: 1 failed</summary>" in html
        assert f"<pre>{escaped}</pre>" in html
