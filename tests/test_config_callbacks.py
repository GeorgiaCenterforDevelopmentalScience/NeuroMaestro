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
        assert (config_root / "project_config" / "demo_config.yaml").exists()

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
        assert result.startswith("# ")

    def test_returns_error_comment_for_no_project_name(self, tmp_path):
        from neuromaestro.interface.callbacks.config_callbacks import load_config_callback
        with patch(f"{_CB_MOD}._CONFIG_DIR", tmp_path / "config"):
            result = load_config_callback(1, "")
        assert result.startswith("# ")

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
    @pytest.mark.parametrize("editor, needs_restart", zip(EDITORS, (False, True, True)),
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
