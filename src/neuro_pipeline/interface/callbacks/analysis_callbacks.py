import os
import subprocess
from pathlib import Path

from dash import html, no_update, Input, Output, State, callback_context
import dash_bootstrap_components as dbc


def register_analysis_callbacks(app):

    # Apply config-dir: load config and update pipeline module options
    @app.callback(
        [Output("config-dir-status", "children"),
         Output("intermed-checklist", "options"),
         Output("bids-prep-checklist", "options"),
         Output("bids-post-checklist", "options"),
         Output("staged-prep-checklist", "options"),
         Output("staged-post-checklist", "options")],
        Input("apply-config-dir-btn", "n_clicks"),
        State("config-dir-input", "value"),
        prevent_initial_call=True
    )
    def apply_config_dir(n_clicks, config_dir):
        if not config_dir:
            return dbc.Alert("Please enter a config directory path.", color="warning"), [], [], [], [], []
        try:
            from ...pipeline.utils.config_utils import (
                set_config_dir, get_intermed_task_names,
                get_bids_pipeline_names, get_staged_pipeline_names,
            )
            set_config_dir(config_dir)
            os.environ["CONFIG_DIR"] = str(config_dir)

            intermed_opts = [{"label": n, "value": n} for n in get_intermed_task_names()]
            bids_opts = [{"label": n.capitalize(), "value": n} for n in get_bids_pipeline_names()]
            staged_opts = [{"label": n.capitalize(), "value": n} for n in get_staged_pipeline_names()]

            status = dbc.Alert([
                html.I(className="fas fa-check-circle me-2"),
                f"Config loaded from: {config_dir}",
            ], color="success", className="mb-0")
            return status, intermed_opts, bids_opts, bids_opts, staged_opts, staged_opts

        except FileNotFoundError as e:
            msg = dbc.Alert(
                f"Config file not found: {e}. Run Init first, then edit the YAML files.",
                color="warning", className="mb-0"
            )
            return msg, [], [], [], [], []
        except Exception as e:
            return dbc.Alert(f"Error loading config: {e}", color="danger", className="mb-0"), [], [], [], [], []

    # Init: copy package templates to the given config directory
    @app.callback(
        Output("config-dir-status", "children", allow_duplicate=True),
        Input("init-study-btn", "n_clicks"),
        State("config-dir-input", "value"),
        prevent_initial_call=True
    )
    def init_study(n_clicks, config_dir):
        if not config_dir:
            return dbc.Alert("Please enter a config directory path first.", color="warning")
        try:
            from neuro_pipeline.pipeline.utils.init_utils import init_project_templates
            config_path = Path(config_dir)
            copied = init_project_templates(config_path)
            if not copied:
                return dbc.Alert("No template files found in package.", color="warning", className="mb-0")

            scripts_out = config_path.parent / "scripts"
            has_scripts = "scripts/" in copied
            lines = [
                html.I(className="fas fa-check-circle me-2"),
                f"Initialized. Copied: {', '.join(copied)}.",
                html.Br(),
                f"Config: {config_path}",
            ]
            if has_scripts:
                lines += [html.Br(), f"Scripts: {scripts_out}"]
            else:
                lines += [html.Br(), html.Span(
                    "Warning: script templates not found in package — scripts/ was not created.",
                    style={"color": "orange"},
                )]
            lines += [html.Br(), "Click Apply to load the config."]
            return dbc.Alert(lines, color="success", className="mb-0")
        except Exception as e:
            return dbc.Alert(f"Init error: {e}", color="danger", className="mb-0")

    # Subject detection and manual input callback
    @app.callback(
        [Output("subjects-detection-result", "children"),
         Output("subjects-list-container", "children"),
         Output("subjects-store", "data"),
         Output("manual-subjects", "value")],
        [Input("detect-subjects-btn", "n_clicks"),
         Input("manual-subjects", "value"),
         Input("clear-subjects-btn", "n_clicks")],
        [State("subject-prefix", "value"),
         State("current-dir", "value")]
    )
    def detect_subjects_callback(detect_clicks, manual_input, clear_clicks, prefix, directory):
        ctx = callback_context
        if not ctx.triggered:
            return "", "", [], ""

        trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
        prefix = prefix or ""

        if trigger_id == "clear-subjects-btn":
            return "", "", [], ""

        if trigger_id == "manual-subjects" and manual_input:
            try:
                subjects = []
                for s in manual_input.split(","):
                    s = s.strip()
                    if s:
                        if s.startswith(prefix):
                            s = s[len(prefix):]
                        subjects.append(s)

                if not subjects:
                    return "", "", [], manual_input

                result = dbc.Alert([
                    html.I(className="fas fa-check-circle me-2"),
                    html.Div([
                        f"Manually entered {len(subjects)} subjects",
                        html.Br(),
                        html.Small(f"Subjects: {', '.join(subjects)}", className="text-muted")
                    ])
                ], color="info")

                return result, "", subjects, manual_input

            except Exception as e:
                return dbc.Alert(f"Error parsing subjects: {str(e)}", color="danger"), "", [], manual_input

        # A successful detection clears the manual field so that only one source
        # of subjects is ever visible. Failures leave whatever the user typed.
        if trigger_id == "detect-subjects-btn":
            if detect_clicks is None:
                return "", "", [], no_update

            if not directory:
                return dbc.Alert("Please provide a directory", color="warning"), "", [], no_update

            try:
                from ...pipeline.utils.detect_subjects import detect_subjects

                subjects = detect_subjects(directory, prefix)

                if not subjects:
                    result = dbc.Alert(f"No subjects found with prefix '{prefix}' in {directory}", color="warning")
                    return result, "", [], no_update

                result = dbc.Alert([
                    html.I(className="fas fa-check-circle me-2"),
                    html.Div([
                        f"Found {len(subjects)} subjects",
                        html.Br(),
                        html.Small(f"Subjects: {', '.join(subjects)}", className="text-muted")
                    ])
                ], color="success")

                return result, "", subjects, ""

            except Exception as e:
                error_msg = f"Error detecting subjects: {str(e)}"
                return dbc.Alert([
                    html.I(className="fas fa-exclamation-triangle me-2"),
                    error_msg
                ], color="danger"), "", [], no_update

        # Reached when clearing the manual field re-fires this callback, which
        # happens right after a detection writes "" to it. Holding everything
        # would otherwise discard the detection result that just landed.
        return no_update, no_update, no_update, no_update

    # Generate command preview callback
    @app.callback(
        [Output("command-preview", "children"),
        Output("pipeline-commands-store", "data")],
        [Input("generate-commands-btn", "n_clicks")],
        [State("subjects-store", "data"),
        State("config-dir-input", "value"),
        State("input-dir", "value"),
        State("output-dir", "value"),
        State("work-dir", "value"),
        State("project-name", "value"),
        State("session-id", "value"),
        State("prep-options", "value"),
        State("intermed-checklist", "value"),
        State("bids-prep-checklist", "value"),
        State("bids-post-checklist", "value"),
        State("staged-prep-checklist", "value"),
        State("staged-post-checklist", "value"),
        State("mriqc-options", "value"),
        State("dry-run-checkbox", "value"),
        State("resume-checkbox", "value"),
        State("skip-preflight-checkbox", "value"),
        State("skip-bids-validation-checkbox", "value")]
    )
    def generate_command_callback(n_clicks, subjects, config_dir, input_dir, output_dir, work_dir,
                                project_name, session, prep_option, intermed_value,
                                bids_prep, bids_post, staged_prep, staged_post,
                                mriqc_option, dry_run, resume, skip_preflight, skip_bids_validation):
        if n_clicks is None:
            return "Click 'Generate Command' to preview the pipeline command", {}

        if not subjects:
            return "Error: No subjects selected. Please detect subjects first.", {}

        if not all([input_dir, output_dir, work_dir, project_name, session]):
            return "Error: Please fill in all required fields (input, output, work directories, project name, session)", {}

        try:
            cmd_parts = []

            cmd_parts.append(f'input_dir="{input_dir}"')
            cmd_parts.append(f'output_dir="{output_dir}"')
            cmd_parts.append(f'work_dir="{work_dir}"')
            cmd_parts.append('')

            cmd_parts.append('neuropipe run \\')

            if config_dir:
                cmd_parts.append(f'  --config-dir "{config_dir}" \\')

            subjects_str = ",".join(subjects)
            cmd_parts.append(f'  --subjects {subjects_str} \\')

            cmd_parts.append(f'  --input "$input_dir" \\')
            cmd_parts.append(f'  --output "$output_dir" \\')
            cmd_parts.append(f'  --work "$work_dir" \\')

            cmd_parts.append(f'  --session {session} \\')
            cmd_parts.append(f'  --project {project_name} \\')

            if prep_option and prep_option != "none":
                cmd_parts.append(f'  --prep {prep_option} \\')

            if intermed_value:
                cmd_parts.append(f'  --intermed {",".join(intermed_value)} \\')

            if bids_prep:
                cmd_parts.append(f'  --bids-prep {",".join(bids_prep)} \\')
            if bids_post:
                cmd_parts.append(f'  --bids-post {",".join(bids_post)} \\')

            if staged_prep:
                cmd_parts.append(f'  --staged-prep {",".join(staged_prep)} \\')
            if staged_post:
                cmd_parts.append(f'  --staged-post {",".join(staged_post)} \\')

            if mriqc_option and mriqc_option != "none":
                cmd_parts.append(f'  --mriqc {mriqc_option} \\')

            if dry_run and "dry_run" in dry_run:
                cmd_parts.append(f'  --dry-run \\')

            if resume and "resume" in resume:
                cmd_parts.append(f'  --resume \\')

            if skip_preflight and "skip_preflight" in skip_preflight:
                cmd_parts.append(f'  --skip-preflight \\')

            if skip_bids_validation and "skip_bids_validation" in skip_bids_validation:
                cmd_parts.append(f'  --skip-bids-validation \\')

            if cmd_parts[-1].endswith(' \\'):
                cmd_parts[-1] = cmd_parts[-1][:-2]

            command_str = "\n".join(cmd_parts)

            command_data = {
                "subjects": subjects,
                "config_dir": config_dir,
                "input_dir": input_dir,
                "output_dir": output_dir,
                "work_dir": work_dir,
                "project_name": project_name,
                "session": session,
                "prep_option": prep_option,
                "intermed_value": intermed_value,
                "bids_prep": bids_prep,
                "bids_post": bids_post,
                "staged_prep": staged_prep,
                "staged_post": staged_post,
                "mriqc_option": mriqc_option,
                "dry_run": dry_run,
                "resume": resume,
                "skip_preflight": skip_preflight,
                "skip_bids_validation": skip_bids_validation
            }

            return command_str, command_data

        except Exception as e:
            return f"Error generating command: {str(e)}", {}

    # Execute pipeline callback
    @app.callback(
        Output("execution-status", "children"),
        [Input("execute-pipeline-btn", "n_clicks")],
        [State("pipeline-commands-store", "data"),
        State("dry-run-checkbox", "value"),
        State("resume-checkbox", "value"),
        State("skip-preflight-checkbox", "value"),
        State("skip-bids-validation-checkbox", "value")],
        prevent_initial_call=True
    )
    def execute_pipeline_callback(n_clicks, command_data, dry_run, resume, skip_preflight, skip_bids_validation):
        if n_clicks is None:
            return ""

        if not command_data:
            return dbc.Alert([
                html.I(className="fas fa-exclamation-triangle me-2"),
                "No command available. Please generate command first."
            ], color="warning")

        if not command_data.get("session"):
            return dbc.Alert([
                html.I(className="fas fa-exclamation-triangle me-2"),
                "Session is missing from the generated command. Fill in Session ID and generate again."
            ], color="warning")

        try:
            cmd = ["neuropipe", "run"]

            if command_data.get("config_dir"):
                cmd.extend(["--config-dir", command_data["config_dir"]])

            subjects_str = ",".join(command_data["subjects"])
            cmd.extend(["--subjects", subjects_str])

            cmd.extend(["--input", command_data["input_dir"]])
            cmd.extend(["--output", command_data["output_dir"]])
            cmd.extend(["--work", command_data["work_dir"]])

            cmd.extend(["--session", command_data["session"]])
            cmd.extend(["--project", command_data["project_name"]])

            if command_data.get("prep_option") and command_data["prep_option"] != "none":
                cmd.extend(["--prep", command_data["prep_option"]])

            if command_data.get("intermed_value"):
                cmd.extend(["--intermed", ",".join(command_data["intermed_value"])])

            if command_data.get("bids_prep"):
                cmd.extend(["--bids-prep", ",".join(command_data["bids_prep"])])
            if command_data.get("bids_post"):
                cmd.extend(["--bids-post", ",".join(command_data["bids_post"])])

            if command_data.get("staged_prep"):
                cmd.extend(["--staged-prep", ",".join(command_data["staged_prep"])])
            if command_data.get("staged_post"):
                cmd.extend(["--staged-post", ",".join(command_data["staged_post"])])

            if command_data.get("mriqc_option") and command_data["mriqc_option"] != "none":
                cmd.extend(["--mriqc", command_data["mriqc_option"]])

            # Flags come from the live checkboxes only. ORing them with the
            # values stored at generate time made an unchecked box impossible.
            if "dry_run" in (dry_run or []):
                cmd.append("--dry-run")
            if "resume" in (resume or []):
                cmd.append("--resume")
            if "skip_preflight" in (skip_preflight or []):
                cmd.append("--skip-preflight")
            if "skip_bids_validation" in (skip_bids_validation or []):
                cmd.append("--skip-bids-validation")

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                return dbc.Alert([
                    html.I(className="fas fa-check-circle me-2"),
                    "Pipeline execution initiated. Check Job Monitor for status.",
                    html.Br(),
                    html.Small(result.stdout)
                ], color="success")
            else:
                return dbc.Alert([
                    html.I(className="fas fa-exclamation-triangle me-2"),
                    f"Pipeline execution failed: {result.stderr}"
                ], color="danger")

        except FileNotFoundError:
            return dbc.Alert([
                html.I(className="fas fa-exclamation-triangle me-2"),
                "neuropipe command not found. Make sure the package is installed in the active environment.",
            ], color="danger")
        except Exception as e:
            return dbc.Alert([
                html.I(className="fas fa-exclamation-triangle me-2"),
                f"Error executing pipeline: {str(e)}"
            ], color="danger")

    # Dynamic DAG visualization
    @app.callback(
        Output("dag-overview", "elements"),
        [Input("page-rendered-store", "data"),
         Input("prep-options", "value"),
         Input("intermed-checklist", "value"),
         Input("bids-prep-checklist", "value"),
         Input("bids-post-checklist", "value"),
         Input("staged-prep-checklist", "value"),
         Input("staged-post-checklist", "value"),
         Input("mriqc-options", "value")]
    )
    def update_dag_elements(_page, prep_option, intermed_value, bids_prep, bids_post,
                            staged_prep, staged_post, mriqc_option):
        from ..components.analysis_control import build_dag_elements
        return build_dag_elements(
            prep_option or 'none',
            intermed_value or [],
            bids_prep or [],
            bids_post or [],
            staged_prep or [],
            staged_post or [],
            mriqc_option or 'none',
        )

    @app.callback(
        Output("dag-overview", "layout"),
        Input("dag-reset-btn", "n_clicks"),
        prevent_initial_call=True
    )
    def reset_dag_view(_):
        return {'name': 'dagre', 'rankDir': 'LR', 'nodeSep': 40, 'rankSep': 90, 'spacingFactor': 1.0}

    app.clientside_callback(
        """
        function(n_clicks) {
            if (!n_clicks) return window.dash_clientside.no_update;

            var cy = document.getElementById('dag-overview')._cyreg?.cy;
            if (!cy) return window.dash_clientside.no_update;

            var png = cy.png({
                output: 'blob',
                scale: 4,
                full: true,
                bg: '#FAFAFA'
            });

            var url = URL.createObjectURL(png);
            var a = document.createElement('a');
            a.href = url;
            a.download = 'pipeline_dag.png';
            a.click();
            URL.revokeObjectURL(url);

            return window.dash_clientside.no_update;
        }
        """,
        Output("dag-overview", "generateImage"),
        Input("dag-download-btn", "n_clicks"),
        prevent_initial_call=True
    )

    # Sidebar toggle callback
    @app.callback(
        [Output("sidebar", "className"),
         Output("main-content", "className")],
        [Input("sidebar-toggle", "n_clicks")],
        [State("sidebar", "className")],
        prevent_initial_call=True
    )
    def toggle_sidebar(n_clicks, sidebar_class):
        if "collapsed" in sidebar_class:
            new_class = sidebar_class.replace("collapsed", "").strip()
            main_class = "main-content"
        else:
            new_class = sidebar_class + " collapsed"
            main_class = "main-content expanded"

        return new_class, main_class
