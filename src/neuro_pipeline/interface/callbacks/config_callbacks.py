import os
from pathlib import Path
from typing import Optional

import yaml as _yaml
from neuro_pipeline.pipeline.utils.config_utils import get_config_dir
from neuro_pipeline.pipeline.utils.generate_results_check import RESULTS_CHECK_TEMPLATE

# Overridden by tests to redirect config reads and writes at a tmp_path.
# Production always resolves through CONFIG_DIR or get_config_dir().
_CONFIG_DIR: Optional[Path] = None


def _effective_config_dir() -> Path:
    if _CONFIG_DIR is not None:
        return _CONFIG_DIR
    env = os.environ.get("CONFIG_DIR")
    if env:
        return Path(env)
    return get_config_dir()


_NO_CONFIG_DIR = ("No config directory set. Enter one under Analysis Control "
                  "and click Apply first.")


def _resolved_config_dir():
    """Returns (path, None) or (None, message) when no config dir is available."""
    try:
        return _effective_config_dir(), None
    except RuntimeError:
        return None, _NO_CONFIG_DIR


from dash import html, Input, Output, State, callback_context
import dash_bootstrap_components as dbc

def _alert_ok(message, extra=None):
    children = [html.I(className="fas fa-check-circle me-2"), message]
    if extra:
        children.append(extra)
    return dbc.Alert(children, color="success", className="mt-2")

def _alert_warn(message):
    return dbc.Alert(message, color="warning")

def _alert_err(message):
    return dbc.Alert(
        [html.I(className="fas fa-exclamation-triangle me-2"), message],
        color="danger"
    )

def _parse_yaml(content):
    """Returns (parsed, None) on success, (None, error_alert) on failure."""
    try:
        return _yaml.safe_load(content), None
    except _yaml.YAMLError as e:
        return None, _alert_err(f"Invalid YAML: {e}")

def _load_file(path):
    """Returns (content, None) on success, (None, error_message) on failure."""
    if not path:
        return None, "Please provide a file path."
    if not os.path.exists(path):
        return None, f"File not found: {path}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, f"Error loading file: {e}"

def _save_file(path, content, restart_note=False):
    """Saves content to path. Returns success or error alert."""
    if not path:
        return _alert_warn("Please provide a file path before saving.")
    try:
        dir_part = os.path.dirname(path)
        if dir_part:
            os.makedirs(dir_part, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        if restart_note:
            return dbc.Alert([
                html.I(className="fas fa-check-circle me-2"),
                f"Saved to {path}",
                html.Br(),
                html.Small("Restart the pipeline process for changes to take effect.",
                           className="text-muted")
            ], color="success")
        return _alert_ok(f"Saved to {path}")
    except Exception as e:
        return _alert_err(f"Error saving: {e}")

def _trigger_id():
    ctx = callback_context
    if not ctx.triggered:
        return None
    return ctx.triggered[0]["prop_id"].split(".")[0]


# ── Tab 1: Project Config ─────────────────────────────────────────────────────

def _project_config_path(project_name: str) -> Path:
    return _effective_config_dir() / "project_config" / f"{project_name}_config.yaml"


def generate_new_config_callback(_n_clicks, project_name):
    if not project_name:
        return dbc.Alert([
            html.I(className="fas fa-exclamation-triangle me-2"),
            "Please provide a project name"
        ], color="warning")

    config_dir, cfg_err = _resolved_config_dir()
    if cfg_err:
        return _alert_warn(cfg_err)

    try:
        from neuro_pipeline.pipeline.utils.generate_project_config import generate_project_config

        resolved_dir = str(config_dir / "project_config")
        generate_project_config(project_name, resolved_dir)
        config_file = os.path.join(resolved_dir, f"{project_name}_config.yaml")

        return dbc.Alert([
            html.I(className="fas fa-check-circle me-2"),
            html.Div([
                f"Configuration template generated: {config_file}",
                html.Br(),
                "Click 'Load' to open it in the editor."
            ])
        ], color="success")

    except FileExistsError:
        # The CLI wording mentions --force, which means nothing in the GUI.
        return dbc.Alert([
            html.I(className="fas fa-exclamation-triangle me-2"),
            html.Div([
                f"A config for '{project_name}' already exists.",
                html.Br(),
                "Click 'Load' to edit it, or delete the file first to start over.",
            ])
        ], color="warning")
    except Exception as e:
        return dbc.Alert([
            html.I(className="fas fa-exclamation-triangle me-2"),
            f"Error generating configuration: {str(e)}"
        ], color="danger")


def load_config_callback(n_clicks, project_name):
    if n_clicks is None:
        return ""
    if not project_name:
        return "# Please provide a project name."
    config_dir, err = _resolved_config_dir()
    if err:
        return f"# {err}"
    content, err = _load_file(str(_project_config_path(project_name)))
    if err:
        return f"# {err}"
    return content


def save_config_callback(_save_clicks, _validate_clicks, project_name, yaml_content):
    try:
        if not yaml_content:
            return _alert_warn("Editor is empty.")
        _, err = _parse_yaml(yaml_content)
        if err:
            return err
        if _trigger_id() == "validate-config-btn":
            return _alert_ok("Valid YAML")
        if not project_name:
            return _alert_warn("Please provide a project name.")
        _config_dir, cfg_err = _resolved_config_dir()
        if cfg_err:
            return _alert_warn(cfg_err)
        return _save_file(str(_project_config_path(project_name)), yaml_content)
    except Exception as e:
        return _alert_err(f"Unexpected error: {e}")


# ── Tab 2: Results Check ──────────────────────────────────────────────────────

def _checks_path(project_name: str) -> Path:
    return _effective_config_dir() / "results_check" / f"{project_name}_checks.yaml"


def load_checks_callback(load_clicks, new_clicks, project_name):
    ctx = callback_context
    if not ctx.triggered:
        return "", ""

    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if trigger_id == "new-checks-btn":
        return RESULTS_CHECK_TEMPLATE, dbc.Alert(
            "New template loaded. Fill in your task checks and save.",
            color="info", className="mt-2"
        )

    if not project_name:
        return "", dbc.Alert("Please provide a project name.", color="warning")

    _config_dir, cfg_err = _resolved_config_dir()
    if cfg_err:
        return "", dbc.Alert(cfg_err, color="warning")

    resolved = _checks_path(project_name)
    if not resolved.exists():
        return "", dbc.Alert(
            f"File not found: {resolved}. Click 'New' to start from a template.",
            color="warning"
        )

    try:
        content = resolved.read_text(encoding="utf-8")
        return content, dbc.Alert(
            [html.I(className="fas fa-check-circle me-2"), f"Loaded: {resolved}"],
            color="success", className="mt-2"
        )
    except Exception as e:
        return "", dbc.Alert(f"Error loading file: {e}", color="danger")


def save_checks_callback(save_clicks, validate_clicks, project_name, yaml_content):
    try:
        if not yaml_content:
            return _alert_warn("Editor is empty.")
        parsed, err = _parse_yaml(yaml_content)
        if err:
            return err
        if _trigger_id() == "validate-checks-btn":
            if not isinstance(parsed, dict):
                return _alert_warn("Top-level must be a YAML mapping (task_name: ...).")
            return _alert_ok(f"Valid YAML · {len(parsed)} task(s) defined: {', '.join(parsed.keys())}")
        if not project_name:
            return _alert_warn("Please provide a project name.")
        _config_dir, cfg_err = _resolved_config_dir()
        if cfg_err:
            return _alert_warn(cfg_err)
        return _save_file(str(_checks_path(project_name)), yaml_content)
    except Exception as e:
        return _alert_err(f"Unexpected error: {e}")


# ── Tab 3: Global Pipeline Config ─────────────────────────────────────────────

def load_global_config_callback(n_clicks):
    if not n_clicks:
        return "", ""
    config_dir, cfg_err = _resolved_config_dir()
    if cfg_err:
        return "", _alert_warn(cfg_err)
    config_path = config_dir / "config.yaml"
    content, err = _load_file(str(config_path))
    if err:
        return "", _alert_err(err)
    return content, _alert_ok(f"Loaded: {config_path}")


def save_global_config_callback(save_clicks, validate_clicks, yaml_content):
    try:
        if not yaml_content:
            return _alert_warn("Editor is empty.")
        parsed, err = _parse_yaml(yaml_content)
        if err:
            return err
        if _trigger_id() == "validate-global-config-btn":
            expected = {"prep", "intermed", "qc", "array_config"}
            missing = expected - (set(parsed.keys()) if isinstance(parsed, dict) else set())
            if missing:
                return _alert_warn(f"Valid YAML but missing expected top-level keys: {', '.join(sorted(missing))}")
            task_count = sum(len(v) for v in parsed.values() if isinstance(v, list))
            section_count = sum(1 for v in parsed.values() if isinstance(v, list))
            return _alert_ok(f"Valid YAML · {task_count} task(s) across {section_count} section(s)")
        config_dir, cfg_err = _resolved_config_dir()
        if cfg_err:
            return _alert_warn(cfg_err)
        return _save_file(str(config_dir / "config.yaml"), yaml_content, restart_note=True)
    except Exception as e:
        return _alert_err(f"Unexpected error: {e}")


# ── Tab 4: HPC Config ────────────────────────────────────────────────────────

def load_hpc_config_callback(n_clicks):
    if not n_clicks:
        return "", ""
    config_dir, cfg_err = _resolved_config_dir()
    if cfg_err:
        return "", _alert_warn(cfg_err)
    config_path = config_dir / "hpc_config.yaml"
    content, err = _load_file(str(config_path))
    if err:
        return "", _alert_err(err)
    return content, _alert_ok(f"Loaded: {config_path}")


def save_hpc_config_callback(_save_clicks, _validate_clicks, yaml_content):
    try:
        if not yaml_content:
            return _alert_warn("Editor is empty.")
        parsed, err = _parse_yaml(yaml_content)
        if err:
            return err
        if _trigger_id() == "validate-hpc-config-btn":
            expected = {"resource_profiles", "defaults"}
            missing = expected - (set(parsed.keys()) if isinstance(parsed, dict) else set())
            if missing:
                return _alert_warn(f"Valid YAML but missing expected keys: {', '.join(sorted(missing))}")
            profile_count = len(parsed.get("resource_profiles") or {})
            return _alert_ok(f"Valid YAML · {profile_count} resource profile(s)")
        config_dir, cfg_err = _resolved_config_dir()
        if cfg_err:
            return _alert_warn(cfg_err)
        return _save_file(str(config_dir / "hpc_config.yaml"), yaml_content, restart_note=True)
    except Exception as e:
        return _alert_err(f"Unexpected error: {e}")


# ── Registration ──────────────────────────────────────────────────────────────

def register_config_callbacks(app):

    app.callback(
        Output("new-config-result", "children"),
        [Input("generate-new-config-btn", "n_clicks")],
        [State("new-project-name", "value")],
        prevent_initial_call=True
    )(generate_new_config_callback)

    app.callback(
        Output("yaml-editor", "value"),
        [Input("load-config-btn", "n_clicks")],
        [State("new-project-name", "value")]
    )(load_config_callback)

    app.callback(
        Output("yaml-validation-result", "children"),
        [Input("save-config-btn", "n_clicks"),
         Input("validate-config-btn", "n_clicks")],
        [State("new-project-name", "value"),
         State("yaml-editor", "value")],
        prevent_initial_call=True
    )(save_config_callback)

    app.callback(
        [Output("checks-yaml-editor", "value"),
         Output("checks-validation-result", "children")],
        [Input("load-checks-btn", "n_clicks"),
         Input("new-checks-btn", "n_clicks")],
        State("checks-project-name", "value"),
        prevent_initial_call=True
    )(load_checks_callback)

    app.callback(
        Output("checks-validation-result", "children", allow_duplicate=True),
        [Input("save-checks-btn", "n_clicks"),
         Input("validate-checks-btn", "n_clicks")],
        [State("checks-project-name", "value"),
         State("checks-yaml-editor", "value")],
        prevent_initial_call=True
    )(save_checks_callback)

    app.callback(
        [Output("global-config-editor", "value"),
         Output("global-config-result", "children")],
        Input("load-global-config-btn", "n_clicks"),
        prevent_initial_call=True
    )(load_global_config_callback)

    app.callback(
        Output("global-config-result", "children", allow_duplicate=True),
        [Input("save-global-config-btn", "n_clicks"),
         Input("validate-global-config-btn", "n_clicks")],
        State("global-config-editor", "value"),
        prevent_initial_call=True
    )(save_global_config_callback)

    app.callback(
        [Output("hpc-config-editor", "value"),
         Output("hpc-config-result", "children")],
        Input("load-hpc-config-btn", "n_clicks"),
        prevent_initial_call=True
    )(load_hpc_config_callback)

    app.callback(
        Output("hpc-config-result", "children", allow_duplicate=True),
        [Input("save-hpc-config-btn", "n_clicks"),
         Input("validate-hpc-config-btn", "n_clicks")],
        State("hpc-config-editor", "value"),
        prevent_initial_call=True
    )(save_hpc_config_callback)
