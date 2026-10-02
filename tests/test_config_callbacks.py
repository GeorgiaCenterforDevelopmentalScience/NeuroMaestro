import os
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock

import dash_bootstrap_components as dbc

_CB_MOD = "neuromaestro.interface.callbacks.config_callbacks"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_triggered(component_id):
    ctx = MagicMock()
    ctx.triggered = [{"prop_id": f"{component_id}.n_clicks", "value": 1}]
    return ctx


def _get_alert_color(component):
    assert isinstance(component, dbc.Alert), f"Expected Alert, got {type(component)}"
    return component.color


def _no_config_dir():
    return patch(f"{_CB_MOD}._effective_config_dir", side_effect=RuntimeError("Config directory not set."))


# ---------------------------------------------------------------------------
# _effective_config_dir / _resolved_config_dir
#
# Every tab resolves its paths through these. Without a config dir the user
# must get an actionable message rather than a raw RuntimeError.
# ---------------------------------------------------------------------------

class TestResolvedConfigDir:

    @staticmethod
    def _resolve():
        from neuromaestro.interface.callbacks.config_callbacks import _resolved_config_dir
        return _resolved_config_dir()

    def test_test_seam_takes_precedence_over_the_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "from_env"))
        with patch(f"{_CB_MOD}._CONFIG_DIR", tmp_path / "from_seam"):
            path, err = self._resolve()
        assert err is None
        assert path == tmp_path / "from_seam"

    def test_environment_is_used_when_the_seam_is_unset(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "from_env"))
        with patch(f"{_CB_MOD}._CONFIG_DIR", None):
            path, err = self._resolve()
        assert err is None
        assert path == Path(str(tmp_path / "from_env"))

    def test_blank_environment_is_not_treated_as_a_path(self, tmp_path, monkeypatch):
        # An empty CONFIG_DIR would otherwise resolve to Path(""), i.e. the cwd
        monkeypatch.setenv("CONFIG_DIR", "")
        with patch(f"{_CB_MOD}._CONFIG_DIR", None), \
             patch(f"{_CB_MOD}.get_config_dir", return_value=tmp_path / "fallback"):
            path, err = self._resolve()
        assert err is None
        assert path == tmp_path / "fallback"

    def test_no_config_dir_anywhere_returns_an_actionable_message(self):
        with patch(f"{_CB_MOD}._effective_config_dir",
                   side_effect=RuntimeError("Config directory not set.")):
            path, err = self._resolve()
        assert path is None
        assert "Analysis Control" in err

    def test_generate_new_config_warns_instead_of_raising(self):
        # The regression: this was the one callback that skipped the helper and
        # surfaced the RuntimeError text through a generic error branch
        from neuromaestro.interface.callbacks.config_callbacks import generate_new_config_callback
        with patch(f"{_CB_MOD}._effective_config_dir",
                   side_effect=RuntimeError("Config directory not set.")):
            result = generate_new_config_callback(1, "demo")

        assert _get_alert_color(result) == "warning"
        assert "Analysis Control" in str(result.children)

    def test_loaders_report_the_missing_config_dir(self):
        from neuromaestro.interface.callbacks.config_callbacks import (
            load_global_config_callback, load_hpc_config_callback,
        )
        with patch(f"{_CB_MOD}._effective_config_dir",
                   side_effect=RuntimeError("Config directory not set.")):
            for loader in (load_global_config_callback, load_hpc_config_callback):
                content, alert = loader(1)
                assert content == ""
                assert _get_alert_color(alert) == "warning"


# ---------------------------------------------------------------------------
# _save_file / _load_file unit tests
# ---------------------------------------------------------------------------

class TestSaveAndLoadFile:

    def test_save_creates_file(self, tmp_path):
        from neuromaestro.interface.callbacks.config_callbacks import _save_file
        dest = tmp_path / "out" / "test.yaml"
        result = _save_file(str(dest), "key: value")
        assert _get_alert_color(result) == "success"
        assert dest.exists()
        assert dest.read_text() == "key: value"

    def test_save_returns_error_on_bad_path(self, tmp_path):
        from neuromaestro.interface.callbacks.config_callbacks import _save_file
        # Use an existing file as if it were a directory
        existing_file = tmp_path / "blockfile.txt"
        existing_file.write_text("x")
        result = _save_file(str(existing_file / "sub" / "c.yaml"), "key: value")
        assert _get_alert_color(result) == "danger"

    def test_save_warns_on_empty_path(self):
        from neuromaestro.interface.callbacks.config_callbacks import _save_file
        result = _save_file("", "key: value")
        assert _get_alert_color(result) == "warning"

    def test_save_warns_on_none_path(self):
        from neuromaestro.interface.callbacks.config_callbacks import _save_file
        result = _save_file(None, "key: value")
        assert _get_alert_color(result) == "warning"

    def test_load_reads_existing_file(self, tmp_path):
        from neuromaestro.interface.callbacks.config_callbacks import _load_file
        f = tmp_path / "test.yaml"
        f.write_text("hello: world")
        content, err = _load_file(str(f))
        assert err is None
        assert content == "hello: world"

    def test_load_returns_error_for_missing_file(self, tmp_path):
        from neuromaestro.interface.callbacks.config_callbacks import _load_file
        _, err = _load_file(str(tmp_path / "nonexistent.yaml"))
        assert err is not None
        assert "not found" in err.lower()

    def test_load_returns_error_for_empty_path(self):
        from neuromaestro.interface.callbacks.config_callbacks import _load_file
        _, err = _load_file("")
        assert err is not None


# ---------------------------------------------------------------------------
# generate_project_config integration
# ---------------------------------------------------------------------------

class TestGenerateTemplate:

    def test_generates_yaml_file(self, tmp_path):
        from neuromaestro.pipeline.utils.generate_project_config import generate_project_config
        out_dir = tmp_path / "project_config"
        generate_project_config("myproject", str(out_dir))
        config_file = out_dir / "myproject_config.yaml"
        assert config_file.exists()
        data = yaml.safe_load(config_file.read_text())
        assert "tasks" in data
        assert "prefix" in data

    def test_generated_yaml_is_loadable(self, tmp_path):
        from neuromaestro.pipeline.utils.generate_project_config import generate_project_config
        from neuromaestro.interface.callbacks.config_callbacks import _load_file
        out_dir = tmp_path / "project_config"
        generate_project_config("testproj", str(out_dir))
        content, err = _load_file(str(out_dir / "testproj_config.yaml"))
        assert err is None
        assert "testproj" in content

    def test_callback_generates_and_shows_success(self, tmp_path):
        from neuromaestro.interface.callbacks.config_callbacks import generate_new_config_callback
        config_root = tmp_path / "config"

        with patch(f"{_CB_MOD}._CONFIG_DIR", config_root):
            result = generate_new_config_callback(1, "demo")

        assert _get_alert_color(result) == "success"
        created = config_root / "project_config" / "demo_config.yaml"
        assert created.exists()
        assert result.children[1].children[0] == f"Configuration template generated: {created}"

    def test_existing_config_is_not_overwritten(self, tmp_path):
        from neuromaestro.interface.callbacks.config_callbacks import generate_new_config_callback
        config_root = tmp_path / "config"
        with patch(f"{_CB_MOD}._CONFIG_DIR", config_root):
            generate_new_config_callback(1, "demo")
            edited = config_root / "project_config" / "demo_config.yaml"
            edited.write_text("# my edits\n", encoding="utf-8")
            result = generate_new_config_callback(1, "demo")
        assert _get_alert_color(result) == "warning"
        assert result.children[1].children[0] == "A config for 'demo' already exists."
        assert edited.read_text(encoding="utf-8") == "# my edits\n"

    def test_generator_failure_is_reported(self, tmp_path):
        from neuromaestro.interface.callbacks.config_callbacks import generate_new_config_callback
        with patch(f"{_CB_MOD}._CONFIG_DIR", tmp_path / "config"), \
             patch("neuromaestro.pipeline.utils.generate_project_config.generate_project_config",
                   side_effect=ValueError("bad name")):
            result = generate_new_config_callback(1, "demo")
        assert _get_alert_color(result) == "danger"
        assert result.children[1] == "Error generating configuration: bad name"

    def test_callback_warns_on_missing_project_name(self):
        from neuromaestro.interface.callbacks.config_callbacks import generate_new_config_callback
        result = generate_new_config_callback(1, "")
        assert _get_alert_color(result) == "warning"

    def test_callback_warns_on_none_project_name(self):
        from neuromaestro.interface.callbacks.config_callbacks import generate_new_config_callback
        result = generate_new_config_callback(1, None)
        assert _get_alert_color(result) == "warning"


# ---------------------------------------------------------------------------
# load_config_callback
# ---------------------------------------------------------------------------

class TestLoadConfigCallback:

    def test_loads_existing_file_into_editor(self, tmp_path):
        from neuromaestro.interface.callbacks.config_callbacks import load_config_callback
        config_root = tmp_path / "config"
        yaml_file = config_root / "project_config" / "test_config.yaml"
        yaml_file.parent.mkdir(parents=True)
        yaml_file.write_text("prefix: sub-\ntasks: {}")

        with patch(f"{_CB_MOD}._CONFIG_DIR", config_root):
            result = load_config_callback(1, "test")

        assert "prefix: sub-" in result

    def test_returns_error_comment_for_missing_file(self, tmp_path):
        from neuromaestro.interface.callbacks.config_callbacks import load_config_callback
        with patch(f"{_CB_MOD}._CONFIG_DIR", tmp_path / "config"):
            result = load_config_callback(1, "missing")
        assert result == f"# File not found: {tmp_path / 'config' / 'project_config' / 'missing_config.yaml'}"

    def test_returns_error_comment_for_no_project_name(self, tmp_path):
        from neuromaestro.interface.callbacks.config_callbacks import load_config_callback
        with patch(f"{_CB_MOD}._CONFIG_DIR", tmp_path / "config"):
            result = load_config_callback(1, "")
        assert result == "# Please provide a project name."

    def test_returns_error_comment_without_a_config_dir(self):
        from neuromaestro.interface.callbacks.config_callbacks import load_config_callback, _NO_CONFIG_DIR
        with _no_config_dir():
            assert load_config_callback(1, "proj") == f"# {_NO_CONFIG_DIR}"

    def test_returns_empty_string_on_initial_call(self, tmp_path):
        from neuromaestro.interface.callbacks.config_callbacks import load_config_callback
        with patch(f"{_CB_MOD}._CONFIG_DIR", tmp_path / "config"):
            result = load_config_callback(None, "test")
        assert result == ""


# ---------------------------------------------------------------------------
# save_config_callback
# ---------------------------------------------------------------------------

class TestSaveConfigCallback:

    def _call_save(self, tmp_path, yaml_content, project_name, trigger="save-config-btn"):
        from neuromaestro.interface.callbacks.config_callbacks import save_config_callback
        mock_ctx = _make_triggered(trigger)
        with patch(f"{_CB_MOD}._CONFIG_DIR", tmp_path / "config"), \
             patch(f"{_CB_MOD}.callback_context", mock_ctx):
            return save_config_callback(1, None, project_name, yaml_content)

    def test_saves_valid_yaml(self, tmp_path):
        # a comment and a non-ASCII character: the file must be the editor text, byte for byte
        content = "# geändert\nprefix: sub-\ntasks: {}\n"
        result = self._call_save(tmp_path, content, "save_test")
        assert _get_alert_color(result) == "success"
        saved = (tmp_path / "config" / "project_config" / "save_test_config.yaml").read_text(encoding="utf-8")
        assert saved == content

    def test_warns_on_empty_editor(self, tmp_path):
        result = self._call_save(tmp_path, "", "x")
        assert _get_alert_color(result) == "warning"

    def test_warns_on_none_content(self, tmp_path):
        result = self._call_save(tmp_path, None, "x")
        assert _get_alert_color(result) == "warning"

    def test_warns_on_missing_project_name(self, tmp_path):
        result = self._call_save(tmp_path, "key: value", "")
        assert _get_alert_color(result) == "warning"

    def test_errors_on_invalid_yaml(self, tmp_path):
        result = self._call_save(tmp_path, "key: [unclosed", "x")
        assert _get_alert_color(result) == "danger"
        # the catch-all handler is danger too, so the message tells them apart
        assert result.children[1].startswith("Invalid YAML")

    def test_validate_does_not_write_file(self, tmp_path):
        result = self._call_save(tmp_path, "key: value", "nowrite", trigger="validate-config-btn")
        assert _get_alert_color(result) == "success"
        assert not (tmp_path / "config" / "project_config" / "nowrite_config.yaml").exists()

    def test_roundtrip_generate_load_save(self, tmp_path):
        """Full workflow: generate template → load → save under new project name."""
        from neuromaestro.pipeline.utils.generate_project_config import generate_project_config
        from neuromaestro.interface.callbacks.config_callbacks import load_config_callback, save_config_callback

        config_root = tmp_path / "config"
        generate_project_config("roundtrip", str(config_root / "project_config"))

        with patch(f"{_CB_MOD}._CONFIG_DIR", config_root):
            editor_content = load_config_callback(1, "roundtrip")

        assert "roundtrip" in editor_content
        assert not editor_content.startswith("# ")

        mock_ctx = _make_triggered("save-config-btn")
        with patch(f"{_CB_MOD}._CONFIG_DIR", config_root), \
             patch(f"{_CB_MOD}.callback_context", mock_ctx):
            save_result = save_config_callback(1, None, "roundtrip_copy", editor_content)

        assert _get_alert_color(save_result) == "success"
        saved_file = config_root / "project_config" / "roundtrip_copy_config.yaml"
        assert saved_file.read_text(encoding="utf-8") == editor_content


# ---------------------------------------------------------------------------
# save_checks / save_global_config / save_hpc_config
#
# Each writes one file under the config dir; config.yaml affects every project.
# ---------------------------------------------------------------------------

class TestSiblingEditorsSave:

    # (callback, save button, validate button, extra args before the content, target)
    EDITORS = [
        ("save_checks_callback", "save-checks-btn", "validate-checks-btn", ("proj",),
         "results_check/proj_checks.yaml"),
        ("save_global_config_callback", "save-global-config-btn", "validate-global-config-btn", (),
         "config.yaml"),
        ("save_hpc_config_callback", "save-hpc-config-btn", "validate-hpc-config-btn", (),
         "hpc_config.yaml"),
    ]
    CONTENT = "# geändert\nkey: value\n"

    def _call(self, tmp_path, editor, trigger, content):
        import neuromaestro.interface.callbacks.config_callbacks as mod
        name, _save, _validate, extra, _target = editor
        with patch(f"{_CB_MOD}._CONFIG_DIR", tmp_path), \
             patch(f"{_CB_MOD}.callback_context", _make_triggered(trigger)):
            return getattr(mod, name)(1, None, *extra, content)

    @staticmethod
    def _written(root):
        return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())

    @pytest.mark.parametrize("editor", EDITORS, ids=[e[0] for e in EDITORS])
    def test_save_writes_only_its_own_file(self, tmp_path, editor):
        result = self._call(tmp_path, editor, editor[1], self.CONTENT)
        assert _get_alert_color(result) == "success"
        assert self._written(tmp_path) == [editor[4]]
        assert (tmp_path / editor[4]).read_text(encoding="utf-8") == self.CONTENT

    @pytest.mark.parametrize("editor", EDITORS, ids=[e[0] for e in EDITORS])
    def test_validate_writes_nothing(self, tmp_path, editor):
        self._call(tmp_path, editor, editor[2], self.CONTENT)
        assert self._written(tmp_path) == []

    @pytest.mark.parametrize("editor", EDITORS, ids=[e[0] for e in EDITORS])
    def test_invalid_yaml_writes_nothing(self, tmp_path, editor):
        result = self._call(tmp_path, editor, editor[1], "key: [unclosed")
        assert result.children[1].startswith("Invalid YAML")
        assert self._written(tmp_path) == []

    # config.yaml and hpc_config.yaml are read once at startup, the checks file on every run
    @pytest.mark.parametrize("editor, needs_restart", list(zip(EDITORS, (False, True, True))),
                             ids=[e[0] for e in EDITORS])
    def test_restart_note_only_where_the_file_is_cached(self, tmp_path, editor, needs_restart):
        result = self._call(tmp_path, editor, editor[1], self.CONTENT)
        assert ("Restart the pipeline process for changes to take effect." in str(result)) is needs_restart


class TestValidateFeedback:

    @staticmethod
    def _validate(name, button, content, *extra):
        import neuromaestro.interface.callbacks.config_callbacks as mod
        with patch(f"{_CB_MOD}.callback_context", _make_triggered(button)):
            return getattr(mod, name)(None, 1, *extra, content)

    @staticmethod
    def _message(alert):
        return alert.children if isinstance(alert.children, str) else alert.children[1]

    @pytest.mark.parametrize("content, color, message", [
        ("prep: [{}, {}]\nintermed: [{}]\nqc: none\n", "success", "Valid YAML · 3 task(s) across 2 section(s)"),
        ("prep: []\n", "warning", "Valid YAML but missing expected top-level keys: intermed, qc"),
        ("- a\n- b\n", "warning", "Valid YAML but missing expected top-level keys: intermed, prep, qc"),
    ])
    def test_global_config(self, content, color, message):
        result = self._validate("save_global_config_callback", "validate-global-config-btn", content)
        assert (_get_alert_color(result), self._message(result)) == (color, message)

    @pytest.mark.parametrize("content, color, message", [
        ("resource_profiles:\n  a: {}\n  b: {}\ndefaults: {}\n", "success", "Valid YAML · 2 resource profile(s)"),
        ("defaults: {}\n", "warning", "Valid YAML but missing expected keys: resource_profiles"),
        ("- x\n", "warning", "Valid YAML but missing expected keys: defaults, resource_profiles"),
    ])
    def test_hpc_config(self, content, color, message):
        result = self._validate("save_hpc_config_callback", "validate-hpc-config-btn", content)
        assert (_get_alert_color(result), self._message(result)) == (color, message)

    @pytest.mark.parametrize("content, color, message", [
        ("recon: {}\nunzip: {}\n", "success", "Valid YAML · 2 task(s) defined: recon, unzip"),
        ("- recon\n", "warning", "Top-level must be a YAML mapping (task_name: ...)."),
    ])
    def test_checks(self, content, color, message):
        result = self._validate("save_checks_callback", "validate-checks-btn", content, "proj")
        assert (_get_alert_color(result), self._message(result)) == (color, message)


# ---------------------------------------------------------------------------
# Loading into the editors
# ---------------------------------------------------------------------------

class TestLoadChecksCallback:

    @staticmethod
    def _load(config_dir, trigger, project="proj"):
        from neuromaestro.interface.callbacks.config_callbacks import load_checks_callback
        ctx = _make_triggered(trigger) if trigger else MagicMock(triggered=[])
        with patch(f"{_CB_MOD}._CONFIG_DIR", config_dir), patch(f"{_CB_MOD}.callback_context", ctx):
            return load_checks_callback(1, None, project)

    def test_nothing_triggered(self, tmp_path):
        assert self._load(tmp_path, None) == ("", "")

    def test_new_starts_from_the_template_without_a_project(self, tmp_path):
        from neuromaestro.pipeline.utils.generate_results_check import RESULTS_CHECK_TEMPLATE
        content, alert = self._load(tmp_path, "new-checks-btn", project=None)
        assert content == RESULTS_CHECK_TEMPLATE
        assert (alert.color, alert.children) == ("info", "New template loaded. Fill in your task checks and save.")

    def test_existing_file_is_loaded_as_written(self, tmp_path):
        path = tmp_path / "results_check" / "proj_checks.yaml"
        path.parent.mkdir()
        path.write_text("# geändert\nrecon: {}\n", encoding="utf-8")
        content, alert = self._load(tmp_path, "load-checks-btn")
        assert content == "# geändert\nrecon: {}\n"
        assert (alert.color, alert.children[1]) == ("success", f"Loaded: {path}")

    def test_missing_file_points_to_new(self, tmp_path):
        content, alert = self._load(tmp_path, "load-checks-btn")
        path = tmp_path / "results_check" / "proj_checks.yaml"
        assert content == ""
        assert (alert.color, alert.children) == (
            "warning", f"File not found: {path}. Click 'New' to start from a template.")

    @pytest.mark.parametrize("project", ["", None])
    def test_project_name_is_required(self, tmp_path, project):
        content, alert = self._load(tmp_path, "load-checks-btn", project=project)
        assert (content, alert.color, alert.children) == ("", "warning", "Please provide a project name.")

    def test_no_config_dir(self, tmp_path):
        from neuromaestro.interface.callbacks.config_callbacks import _NO_CONFIG_DIR
        with _no_config_dir():
            content, alert = self._load(None, "load-checks-btn")
        assert (content, alert.color, alert.children) == ("", "warning", _NO_CONFIG_DIR)

    def test_unreadable_file(self, tmp_path):
        # a directory where the file should be: it exists but cannot be read
        (tmp_path / "results_check" / "proj_checks.yaml").mkdir(parents=True)
        content, alert = self._load(tmp_path, "load-checks-btn")
        assert (content, alert.color) == ("", "danger")
        assert alert.children.startswith("Error loading file: ")


class TestLoadGlobalAndHpcConfig:

    LOADERS = [("load_global_config_callback", "config.yaml"), ("load_hpc_config_callback", "hpc_config.yaml")]

    @staticmethod
    def _load(name, config_dir, clicks=1):
        import neuromaestro.interface.callbacks.config_callbacks as mod
        with patch(f"{_CB_MOD}._CONFIG_DIR", config_dir):
            return getattr(mod, name)(clicks)

    @pytest.mark.parametrize("name, filename", LOADERS)
    def test_file_is_loaded_as_written(self, tmp_path, name, filename):
        (tmp_path / filename).write_text("# geändert\nkey: 1\n", encoding="utf-8")
        content, alert = self._load(name, tmp_path)
        assert content == "# geändert\nkey: 1\n"
        assert (alert.color, alert.children[1]) == ("success", f"Loaded: {tmp_path / filename}")

    @pytest.mark.parametrize("name, filename", LOADERS)
    def test_missing_file(self, tmp_path, name, filename):
        content, alert = self._load(name, tmp_path)
        assert (content, alert.color, alert.children[1]) == ("", "danger", f"File not found: {tmp_path / filename}")

    @pytest.mark.parametrize("name, filename", LOADERS)
    def test_unreadable_file(self, tmp_path, name, filename):
        (tmp_path / filename).mkdir()
        content, alert = self._load(name, tmp_path)
        assert (content, alert.color) == ("", "danger")
        assert alert.children[1].startswith("Error loading file: ")

    @pytest.mark.parametrize("name, filename", LOADERS)
    @pytest.mark.parametrize("clicks", [None, 0])
    def test_nothing_happens_before_a_click(self, tmp_path, name, filename, clicks):
        (tmp_path / filename).write_text("key: 1\n", encoding="utf-8")
        assert self._load(name, tmp_path, clicks=clicks) == ("", "")


# ---------------------------------------------------------------------------
# What every save does when it cannot save
# ---------------------------------------------------------------------------

class TestSaveErrorPaths:

    # (callback, save button, arguments before the content)
    EDITORS = [
        ("save_config_callback", "save-config-btn", ("proj",)),
        ("save_checks_callback", "save-checks-btn", ("proj",)),
        ("save_global_config_callback", "save-global-config-btn", ()),
        ("save_hpc_config_callback", "save-hpc-config-btn", ()),
    ]
    IDS = [e[0] for e in EDITORS]

    @staticmethod
    def _save(editor, content, config_dir, args=None):
        import neuromaestro.interface.callbacks.config_callbacks as mod
        name, button, extra = editor
        with patch(f"{_CB_MOD}._CONFIG_DIR", config_dir), \
             patch(f"{_CB_MOD}.callback_context", _make_triggered(button)):
            return getattr(mod, name)(1, None, *(extra if args is None else args), content)

    @staticmethod
    def _written(root):
        return [p for p in root.rglob("*") if p.is_file()]

    @pytest.mark.parametrize("editor", EDITORS, ids=IDS)
    @pytest.mark.parametrize("content", ["", None])
    def test_empty_editor(self, tmp_path, editor, content):
        result = self._save(editor, content, tmp_path)
        assert (result.color, result.children) == ("warning", "Editor is empty.")
        assert self._written(tmp_path) == []

    @pytest.mark.parametrize("editor", EDITORS, ids=IDS)
    def test_no_config_dir(self, editor):
        from neuromaestro.interface.callbacks.config_callbacks import _NO_CONFIG_DIR
        with _no_config_dir():
            result = self._save(editor, "key: value\n", None)
        assert (result.color, result.children) == ("warning", _NO_CONFIG_DIR)

    @pytest.mark.parametrize("editor", EDITORS, ids=IDS)
    def test_unexpected_error_is_reported(self, tmp_path, editor):
        with patch(f"{_CB_MOD}._save_file", side_effect=RuntimeError("disk gone")):
            result = self._save(editor, "key: value\n", tmp_path)
        assert (result.color, result.children[1]) == ("danger", "Unexpected error: disk gone")

    @pytest.mark.parametrize("project", ["", None])
    def test_checks_need_a_project_name(self, tmp_path, project):
        result = self._save(self.EDITORS[1], "recon: {}\n", tmp_path, args=(project,))
        assert (result.color, result.children) == ("warning", "Please provide a project name.")
        assert self._written(tmp_path) == []
