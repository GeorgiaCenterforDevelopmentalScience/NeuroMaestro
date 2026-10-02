"""
test_analysis_callbacks.py

Unit tests for the analysis control callbacks:
  - apply_config_dir
  - init_study
  - detect_subjects_callback
  - generate_command_callback
  - execute_pipeline_callback
  - toggle_sidebar
  - update_dag_elements

Each covers a regression that shipped in this module: the sidebar collapsing
on first paint, detection wiping its own result, checkboxes that could not be
unchecked once a command had been generated, and a missing session reaching
the command line as the string "None".
"""

import os
import subprocess
import pytest
from unittest.mock import patch, MagicMock

import dash_bootstrap_components as dbc
from dash import html
from dash._callback import NoUpdate

_MOD = "neuromaestro.interface.callbacks.analysis_callbacks"


class FakeApp:
    """Records callbacks by function name; ignores clientside registrations."""

    def __init__(self):
        self._callbacks = {}

    def callback(self, *args, **kwargs):
        def decorator(fn):
            self._callbacks[fn.__name__] = fn
            return fn
        return decorator

    def clientside_callback(self, *args, **kwargs):
        pass

    def get(self, name):
        return self._callbacks[name]


@pytest.fixture(scope="module")
def callbacks():
    fake_app = FakeApp()
    from neuromaestro.interface.callbacks.analysis_callbacks import register_analysis_callbacks
    register_analysis_callbacks(fake_app)
    return fake_app


def _ctx(component_id, prop="n_clicks"):
    ctx = MagicMock()
    ctx.triggered = [{"prop_id": f"{component_id}.{prop}", "value": 1}]
    return ctx


# ---------------------------------------------------------------------------
# apply_config_dir
#
# Populates every checklist and exports CONFIG_DIR for the config editor.
# ---------------------------------------------------------------------------

_CFG_MOD = "neuromaestro.pipeline.utils.config_utils"


class TestApplyConfigDir:

    @staticmethod
    def _run(callbacks, config_dir, monkeypatch, **overrides):
        # setenv (not delenv) so pytest restores whatever the callback writes
        monkeypatch.setenv("CONFIG_DIR", "")
        targets = {
            "set_config_dir": MagicMock(),
            "get_intermed_task_names": MagicMock(return_value=["smooth"]),
            "get_bids_pipeline_names": MagicMock(return_value=["rest"]),
            "get_staged_pipeline_names": MagicMock(return_value=["dwi"]),
        }
        targets.update(overrides)
        with patch.multiple(_CFG_MOD, **targets):
            return callbacks.get("apply_config_dir")(1, config_dir)

    def test_blank_dir_warns_and_clears_every_checklist(self, callbacks):
        status, *option_lists = callbacks.get("apply_config_dir")(1, "")
        assert status.color == "warning"
        assert option_lists == [[], [], [], [], []]

    def test_success_publishes_options_for_each_checklist(self, callbacks, monkeypatch, tmp_path):
        status, intermed, bids_prep, bids_post, staged_prep, staged_post = self._run(
            callbacks, str(tmp_path), monkeypatch)

        assert status.color == "success"
        assert [o["value"] for o in intermed] == ["smooth"]
        # prep and post share one option list per pipeline family
        assert bids_prep == bids_post == [{"label": "Rest", "value": "rest"}]
        assert staged_prep == staged_post == [{"label": "Dwi", "value": "dwi"}]

    def test_success_exports_config_dir_for_the_subprocess(self, callbacks, monkeypatch, tmp_path):
        self._run(callbacks, str(tmp_path), monkeypatch)
        assert os.environ["CONFIG_DIR"] == str(tmp_path)

    def test_missing_config_file_points_at_init(self, callbacks, monkeypatch, tmp_path):
        status, *option_lists = self._run(
            callbacks, str(tmp_path), monkeypatch,
            set_config_dir=MagicMock(side_effect=FileNotFoundError("config.yaml")),
        )
        assert status.color == "warning"
        assert "Run Init first" in str(status.children)
        assert option_lists == [[], [], [], [], []]

    def test_unexpected_error_returns_danger_and_clears_options(self, callbacks, monkeypatch, tmp_path):
        status, *option_lists = self._run(
            callbacks, str(tmp_path), monkeypatch,
            set_config_dir=MagicMock(side_effect=ValueError("bad yaml")),
        )
        assert status.color == "danger"
        assert "bad yaml" in str(status.children)
        assert option_lists == [[], [], [], [], []]

    def test_failure_does_not_export_config_dir(self, callbacks, monkeypatch, tmp_path):
        # A half-applied config dir would send the subprocess somewhere the GUI
        # never managed to load
        self._run(callbacks, str(tmp_path), monkeypatch,
                  set_config_dir=MagicMock(side_effect=ValueError("bad yaml")))
        assert os.environ["CONFIG_DIR"] == ""


# ---------------------------------------------------------------------------
# init_study
# ---------------------------------------------------------------------------

_INIT_FN = "neuromaestro.pipeline.utils.init_utils.init_project_templates"


class TestInitStudy:

    def test_blank_dir_warns(self, callbacks):
        result = callbacks.get("init_study")(1, "")
        assert result.color == "warning"

    def test_nothing_copied_warns(self, callbacks, tmp_path):
        with patch(_INIT_FN, return_value=[]):
            result = callbacks.get("init_study")(1, str(tmp_path))
        assert result.color == "warning"

    def test_scripts_are_reported_beside_the_config_dir(self, callbacks, tmp_path):
        # init_project_templates writes scripts/ next to config/, not inside it
        config_dir = tmp_path / "study" / "config"
        with patch(_INIT_FN, return_value=["config.yaml", "scripts/"]) as mock_init:
            result = callbacks.get("init_study")(1, str(config_dir))

        mock_init.assert_called_once_with(config_dir)
        assert result.color == "success"
        # _text, not str(children): repr() escapes the backslashes in a Windows path
        assert str(config_dir.parent / "scripts") in _text(result)

    def test_missing_script_templates_is_flagged(self, callbacks, tmp_path):
        with patch(_INIT_FN, return_value=["config.yaml"]):
            result = callbacks.get("init_study")(1, str(tmp_path))

        assert result.color == "success"
        assert "script templates not found" in _text(result)

    def test_exception_returns_danger(self, callbacks, tmp_path):
        with patch(_INIT_FN, side_effect=PermissionError("read-only")):
            result = callbacks.get("init_study")(1, str(tmp_path))

        assert result.color == "danger"
        assert "read-only" in _text(result)


def _no_ctx():
    ctx = MagicMock()
    ctx.triggered = []
    return ctx


def _text(node):
    """Flatten a Dash component tree down to its string content."""
    if isinstance(node, NoUpdate) or node is None:
        return ""
    if isinstance(node, str):
        return node
    children = getattr(node, "children", None)
    if children is None:
        return ""
    if isinstance(children, (list, tuple)):
        return " ".join(_text(c) for c in children)
    return _text(children)


# ---------------------------------------------------------------------------
# detect_subjects_callback
# ---------------------------------------------------------------------------

class TestDetectSubjectsCallback:

    def _call(self, callbacks, trigger, *, detect=None, manual=None, clear=None,
              prefix="sub-", directory="/data", detected=None, side_effect=None):
        fn = callbacks.get("detect_subjects_callback")
        ctx = _ctx(trigger) if trigger else _no_ctx()
        patcher = patch("neuromaestro.pipeline.utils.detect_subjects.detect_subjects",
                        side_effect=side_effect,
                        return_value=detected if detected is not None else [])
        with patch(f"{_MOD}.callback_context", ctx), patcher:
            return fn(detect, manual, clear, prefix, directory)

    def test_no_trigger_returns_empty(self, callbacks):
        alert, _, store, manual = self._call(callbacks, None)
        assert alert == "" and store == [] and manual == ""

    def test_clear_button_empties_everything(self, callbacks):
        alert, _, store, manual = self._call(callbacks, "clear-subjects-btn", clear=1)
        assert alert == "" and store == [] and manual == ""

    def test_manual_entry_populates_store(self, callbacks):
        alert, _, store, _ = self._call(callbacks, "manual-subjects", manual="001,002")
        assert store == ["001", "002"]
        assert "Manually entered 2 subjects" in _text(alert)

    def test_manual_entry_strips_prefix(self, callbacks):
        _, _, store, _ = self._call(callbacks, "manual-subjects", manual="sub-001,sub-002")
        assert store == ["001", "002"]

    def test_manual_entry_tolerates_whitespace_and_blanks(self, callbacks):
        _, _, store, _ = self._call(callbacks, "manual-subjects", manual=" 001 , ,002 ")
        assert store == ["001", "002"]

    def test_manual_entry_with_nothing_usable_clears_store(self, callbacks):
        alert, _, store, _ = self._call(callbacks, "manual-subjects", manual=",,,")
        assert alert == "" and store == []

    def test_empty_prefix_does_not_crash(self, callbacks):
        _, _, store, _ = self._call(callbacks, "manual-subjects", manual="001", prefix=None)
        assert store == ["001"]

    def test_detection_populates_store(self, callbacks):
        alert, _, store, _ = self._call(callbacks, "detect-subjects-btn", detect=1,
                                        detected=["101", "102"])
        assert store == ["101", "102"]
        assert "Found 2 subjects" in _text(alert)

    def test_detection_scans_the_entered_directory_with_the_prefix(self, callbacks):
        fn = callbacks.get("detect_subjects_callback")
        with patch(f"{_MOD}.callback_context", _ctx("detect-subjects-btn")), \
             patch("neuromaestro.pipeline.utils.detect_subjects.detect_subjects",
                   return_value=["101"]) as mock_detect:
            fn(1, None, None, "sub-", "/data")
        mock_detect.assert_called_once_with("/data", "sub-")

    def test_detection_clears_the_manual_field(self, callbacks):
        _, _, _, manual = self._call(callbacks, "detect-subjects-btn", detect=1,
                                     detected=["101"])
        assert manual == ""

    def test_detection_without_directory_warns(self, callbacks):
        alert, _, store, _ = self._call(callbacks, "detect-subjects-btn", detect=1,
                                        directory="")
        assert isinstance(alert, dbc.Alert) and alert.color == "warning"
        assert store == []

    def test_detection_finding_nothing_warns(self, callbacks):
        alert, _, store, _ = self._call(callbacks, "detect-subjects-btn", detect=1,
                                        detected=[])
        assert isinstance(alert, dbc.Alert) and alert.color == "warning"
        assert store == []

    def test_detection_error_is_reported(self, callbacks):
        alert, _, store, _ = self._call(callbacks, "detect-subjects-btn", detect=1,
                                        side_effect=OSError("permission denied"))
        assert isinstance(alert, dbc.Alert) and alert.color == "danger"
        assert "permission denied" in _text(alert)
        assert store == []

    def test_failed_detection_leaves_the_manual_field_alone(self, callbacks):
        _, _, _, manual = self._call(callbacks, "detect-subjects-btn", detect=1,
                                     directory="")
        assert isinstance(manual, NoUpdate)

    def test_refire_after_clearing_manual_field_holds_everything(self, callbacks):
        """The regression: detection writes "" to manual-subjects, which is also
        an Input, so the callback re-fires. It used to reset every output and
        discard the result that had just been produced."""
        alert, lst, store, manual = self._call(callbacks, "manual-subjects", manual="")
        assert all(isinstance(x, NoUpdate) for x in (alert, lst, store, manual))

    def test_alert_and_store_never_disagree(self, callbacks):
        """Whatever the alert claims must be what gets submitted."""
        cases = [
            ("manual-subjects", dict(manual="001,002"), ["001", "002"]),
            ("manual-subjects", dict(manual="sub-007"), ["007"]),
            ("detect-subjects-btn", dict(detect=1, detected=["101", "102"]), ["101", "102"]),
            ("detect-subjects-btn", dict(detect=1, detected=[]), []),
            ("clear-subjects-btn", dict(clear=1), []),
        ]
        for trigger, kwargs, expected_store in cases:
            alert, _, store, _ = self._call(callbacks, trigger, **kwargs)
            assert store == expected_store, f"{trigger} {kwargs}"
            for subject in expected_store:
                assert subject in _text(alert), f"{subject} missing from alert for {trigger}"


# ---------------------------------------------------------------------------
# generate_command_callback
# ---------------------------------------------------------------------------

class TestGenerateCommandCallback:

    BASE = dict(
        subjects=["001"], config_dir="/cfg", input_dir="/in", output_dir="/out",
        work_dir="/work", project_name="proj", session="01", prep_option="none",
        intermed_value=[], bids_prep=[], bids_post=[], staged_prep=[], staged_post=[],
        mriqc_option="none", dry_run=[], resume=[], skip_preflight=[],
        skip_bids_validation=[],
    )

    def _call(self, callbacks, n_clicks=1, **overrides):
        fn = callbacks.get("generate_command_callback")
        kwargs = {**self.BASE, **overrides}
        return fn(
            n_clicks, kwargs["subjects"], kwargs["config_dir"], kwargs["input_dir"],
            kwargs["output_dir"], kwargs["work_dir"], kwargs["project_name"],
            kwargs["session"], kwargs["prep_option"], kwargs["intermed_value"],
            kwargs["bids_prep"], kwargs["bids_post"], kwargs["staged_prep"],
            kwargs["staged_post"], kwargs["mriqc_option"], kwargs["dry_run"],
            kwargs["resume"], kwargs["skip_preflight"], kwargs["skip_bids_validation"],
        )

    def test_initial_call_shows_hint(self, callbacks):
        text, data = self._call(callbacks, n_clicks=None)
        assert "Generate Command" in text
        assert data == {}

    def test_no_subjects_is_an_error(self, callbacks):
        text, data = self._call(callbacks, subjects=[])
        assert text.startswith("Error:")
        assert data == {}

    @pytest.mark.parametrize("field", ["input_dir", "output_dir", "work_dir", "project_name",
                                       "session"])
    def test_missing_required_field_is_an_error(self, callbacks, field):
        text, data = self._call(callbacks, **{field: ""})
        assert text.startswith("Error:")
        assert data == {}

    def test_missing_session_is_an_error(self, callbacks):
        """The regression: a blank session produced '--session None'."""
        text, data = self._call(callbacks, session=None)
        assert text.startswith("Error:")
        assert data == {}

    def test_session_never_renders_as_none(self, callbacks):
        for session in (None, ""):
            text, _ = self._call(callbacks, session=session)
            assert "--session None" not in text
            assert text.startswith("Error:")

    def test_command_contains_core_flags(self, callbacks):
        text, data = self._call(callbacks)
        assert text.splitlines() == [
            'input_dir="/in"',
            'output_dir="/out"',
            'work_dir="/work"',
            '',
            'neuromaestro run \\',
            '  --config-dir "/cfg" \\',
            '  --subjects 001 \\',
            '  --input "$input_dir" \\',
            '  --output "$output_dir" \\',
            '  --work "$work_dir" \\',
            '  --session 01 \\',
            '  --project proj',
        ]
        assert data["subjects"] == ["001"]

    def test_optional_flags_omitted_when_unset(self, callbacks):
        text, _ = self._call(callbacks)
        for flag in ("--prep", "--intermed", "--bids-prep", "--bids-post",
                     "--staged-prep", "--staged-post", "--mriqc", "--dry-run",
                     "--resume", "--skip-preflight", "--skip-bids-validation"):
            assert flag not in text

    def test_selected_modules_appear(self, callbacks):
        text, _ = self._call(callbacks, prep_option="unzip_recon",
                             intermed_value=["volume", "bfc"], bids_prep=["rest"],
                             staged_post=["cards"], mriqc_option="all")
        assert "--prep unzip_recon" in text
        assert "--intermed volume,bfc" in text
        assert "--bids-prep rest" in text
        assert "--staged-post cards" in text
        assert "--mriqc all" in text

    def test_checkbox_flags_appear(self, callbacks):
        text, _ = self._call(callbacks, dry_run=["dry_run"], resume=["resume"],
                             skip_preflight=["skip_preflight"],
                             skip_bids_validation=["skip_bids_validation"])
        for flag in ("--dry-run", "--resume", "--skip-preflight", "--skip-bids-validation"):
            assert flag in text

    def test_last_line_has_no_dangling_continuation(self, callbacks):
        text, _ = self._call(callbacks, dry_run=["dry_run"])
        assert not text.rstrip().endswith("\\")


# ---------------------------------------------------------------------------
# execute_pipeline_callback
# ---------------------------------------------------------------------------

class TestExecutePipelineCallback:

    COMMAND_DATA = dict(
        subjects=["001"], config_dir="/cfg", input_dir="/in", output_dir="/out",
        work_dir="/work", project_name="proj", session="01", prep_option="none",
        intermed_value=[], bids_prep=[], bids_post=[], staged_prep=[],
        staged_post=[], mriqc_option="none",
    )

    def _run(self, callbacks, command_data=None, *, dry_run=None, resume=None,
             skip_preflight=None, skip_bids_validation=None, returncode=0,
             side_effect=None):
        fn = callbacks.get("execute_pipeline_callback")
        result = MagicMock(returncode=returncode, stdout="submitted", stderr="boom")
        with patch(f"{_MOD}.subprocess.run", return_value=result,
                   side_effect=side_effect) as mock_run:
            alert = fn(1,
                       self.COMMAND_DATA if command_data is None else command_data,
                       dry_run, resume, skip_preflight, skip_bids_validation)
        return alert, mock_run

    def _cmd(self, mock_run):
        return mock_run.call_args.args[0]

    def test_without_generated_command_warns(self, callbacks):
        alert, mock_run = self._run(callbacks, command_data={})
        assert alert.color == "warning"
        mock_run.assert_not_called()

    def test_missing_session_warns_instead_of_crashing(self, callbacks):
        data = {**self.COMMAND_DATA, "session": None}
        alert, mock_run = self._run(callbacks, command_data=data)
        assert alert.color == "warning"
        mock_run.assert_not_called()

    def test_success_reports_stdout(self, callbacks):
        alert, _ = self._run(callbacks)
        assert alert.color == "success"
        assert "submitted" in _text(alert)

    def test_failure_reports_stderr(self, callbacks):
        alert, _ = self._run(callbacks, returncode=1)
        assert alert.color == "danger"
        assert "boom" in _text(alert)

    def test_missing_executable_is_explained(self, callbacks):
        alert, _ = self._run(callbacks, side_effect=FileNotFoundError)
        assert alert.color == "danger"
        assert "not found" in _text(alert).lower()

    def test_unchecked_flags_are_not_passed(self, callbacks):
        """The regression: flags were ORed with the values stored at generate
        time, so unchecking a box could never remove them."""
        stale = {**self.COMMAND_DATA, "resume": ["resume"],
                 "skip_preflight": ["skip_preflight"],
                 "skip_bids_validation": ["skip_bids_validation"],
                 "dry_run": ["dry_run"]}
        _, mock_run = self._run(callbacks, command_data=stale,
                                resume=[], skip_preflight=[],
                                skip_bids_validation=[], dry_run=[])
        cmd = self._cmd(mock_run)
        for flag in ("--resume", "--skip-preflight", "--skip-bids-validation", "--dry-run"):
            assert flag not in cmd

    def test_checked_flags_are_passed(self, callbacks):
        _, mock_run = self._run(callbacks, dry_run=["dry_run"], resume=["resume"],
                                skip_preflight=["skip_preflight"],
                                skip_bids_validation=["skip_bids_validation"])
        cmd = self._cmd(mock_run)
        for flag in ("--dry-run", "--resume", "--skip-preflight", "--skip-bids-validation"):
            assert flag in cmd

    FULL_SELECTION = {
        **COMMAND_DATA, "subjects": ["001", "002"], "prep_option": "unzip_recon",
        "intermed_value": ["volume", "bfc"], "bids_prep": ["rest"], "bids_post": ["rest", "dwi"],
        "staged_prep": ["cards"], "staged_post": ["cards", "kidvid"], "mriqc_option": "all",
    }
    ALL_FLAGS = dict(dry_run=["dry_run"], resume=["resume"], skip_preflight=["skip_preflight"],
                     skip_bids_validation=["skip_bids_validation"])

    def test_full_selection_builds_the_exact_command(self, callbacks):
        _, mock_run = self._run(callbacks, command_data=self.FULL_SELECTION, **self.ALL_FLAGS)
        assert mock_run.call_args.args[0] == [
            "neuromaestro", "run",
            "--config-dir", "/cfg", "--subjects", "001,002",
            "--input", "/in", "--output", "/out", "--work", "/work",
            "--session", "01", "--project", "proj",
            "--prep", "unzip_recon", "--intermed", "volume,bfc",
            "--bids-prep", "rest", "--bids-post", "rest,dwi",
            "--staged-prep", "cards", "--staged-post", "cards,kidvid", "--mriqc", "all",
            "--dry-run", "--resume", "--skip-preflight", "--skip-bids-validation",
        ]
        # the mock returns str output regardless, so the decoding flags are pinned here
        assert mock_run.call_args.kwargs == {"capture_output": True, "text": True}

    def test_nothing_selected_builds_the_bare_command(self, callbacks):
        # "none" is a dropdown value, not a task: it must not reach the CLI
        _, mock_run = self._run(callbacks)
        assert mock_run.call_args.args[0] == [
            "neuromaestro", "run",
            "--config-dir", "/cfg", "--subjects", "001",
            "--input", "/in", "--output", "/out", "--work", "/work",
            "--session", "01", "--project", "proj",
        ]

    def test_command_parses_with_the_real_cli(self, callbacks):
        # the GUI and the CLI declare these flags separately
        import typer
        from neuromaestro.pipeline.core import app as cli
        _, mock_run = self._run(callbacks, command_data=self.FULL_SELECTION, **self.ALL_FLAGS)
        argv = mock_run.call_args.args[0]
        run = typer.main.get_command(cli).commands[argv[1]]
        params = run.make_context(argv[1], argv[2:]).params
        assert (params["subjects"], params["session"], params["project"]) == ("001,002", "01", "proj")
        assert (params["input_dir"], params["output_dir"], params["work_dir"]) == ("/in", "/out", "/work")
        assert params["config_dir"] == "/cfg"
        assert (params["prep"], params["mriqc"]) == ("unzip_recon", "all")
        assert params["intermed"] == ("volume,bfc",)
        assert (params["bids_prep"], params["bids_post"]) == (("rest",), ("rest,dwi",))
        assert (params["staged_prep"], params["staged_post"]) == (("cards",), ("cards,kidvid",))
        assert all(params[f] for f in ("dry_run", "resume", "skip_preflight", "skip_bids_validation"))

    def test_config_dir_reaches_the_subprocess_as_an_argument(self, callbacks):
        # neuromaestro run reads --config-dir or NEUROMAESTRO_CONFIG_DIR, never CONFIG_DIR
        _, mock_run = self._run(callbacks)
        cmd = self._cmd(mock_run)
        assert cmd[cmd.index("--config-dir") + 1] == "/cfg"

    def test_command_is_a_list_not_a_shell_string(self, callbacks):
        _, mock_run = self._run(callbacks)
        cmd = self._cmd(mock_run)
        assert isinstance(cmd, list)
        assert cmd[:2] == ["neuromaestro", "run"]

    def test_every_argument_is_a_string(self, callbacks):
        _, mock_run = self._run(callbacks)
        assert all(isinstance(part, str) for part in self._cmd(mock_run))


# ---------------------------------------------------------------------------
# toggle_sidebar
# ---------------------------------------------------------------------------

class TestToggleSidebar:
    """The regression: the button declared n_clicks=0 and the callback guarded
    on `is None`, so the initial fire collapsed the sidebar on first paint.
    prevent_initial_call now stops that fire entirely."""

    def test_collapses_an_expanded_sidebar(self, callbacks):
        fn = callbacks.get("toggle_sidebar")
        sidebar, main = fn(1, "sidebar sidebar-transition")
        assert "collapsed" in sidebar
        assert main == "main-content expanded"

    def test_expands_a_collapsed_sidebar(self, callbacks):
        fn = callbacks.get("toggle_sidebar")
        sidebar, main = fn(2, "sidebar sidebar-transition collapsed")
        assert "collapsed" not in sidebar
        assert main == "main-content"

    def test_toggling_twice_returns_to_the_start(self, callbacks):
        fn = callbacks.get("toggle_sidebar")
        once, _ = fn(1, "sidebar sidebar-transition")
        twice, _ = fn(2, once)
        assert twice == "sidebar sidebar-transition"

    def test_registered_with_prevent_initial_call(self):
        """Guards the actual fix: without this the sidebar starts collapsed."""
        seen = {}

        class RecordingApp:
            def callback(self, *args, **kwargs):
                def decorator(fn):
                    seen[fn.__name__] = kwargs
                    return fn
                return decorator

            def clientside_callback(self, *args, **kwargs):
                pass

        from neuromaestro.interface.callbacks.analysis_callbacks import register_analysis_callbacks
        register_analysis_callbacks(RecordingApp())
        assert seen["toggle_sidebar"].get("prevent_initial_call") is True


# ---------------------------------------------------------------------------
# update_dag_elements
# ---------------------------------------------------------------------------

class TestUpdateDagElements:

    def test_none_values_are_tolerated(self, callbacks):
        fn = callbacks.get("update_dag_elements")
        assert fn(None, None, None, None, None, None, None, None) == []

    def test_selection_produces_elements(self, callbacks):
        fn = callbacks.get("update_dag_elements")
        elements = fn("/", "unzip_recon", ["volume"], [], [], [], [], "none")
        ids = {e["data"]["id"] for e in elements if "source" not in e["data"]}
        assert {"unzip", "recon", "intermed"} <= ids

    BUILDER = "neuromaestro.interface.components.analysis_control.build_dag_elements"

    def test_every_selection_reaches_the_builder(self, callbacks):
        with patch(self.BUILDER, return_value=[]) as build:
            callbacks.get("update_dag_elements")("/", "unzip_recon", ["volume"], ["rest"], ["dwi"],
                                                 ["cards"], ["kidvid"], "all")
        build.assert_called_once_with("unzip_recon", ["volume"], ["rest"], ["dwi"], ["cards"], ["kidvid"], "all")

    def test_unset_controls_become_empty_selections(self, callbacks):
        with patch(self.BUILDER, return_value=[]) as build:
            callbacks.get("update_dag_elements")(None, None, None, None, None, None, None, None)
        build.assert_called_once_with("none", [], [], [], [], [], "none")
