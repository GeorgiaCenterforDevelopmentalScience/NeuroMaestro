import os
import subprocess
import sqlite3
from contextlib import closing
from datetime import datetime
from dash import html, dcc, Input, Output, State
import dash_bootstrap_components as dbc
import pandas as pd
from neuro_pipeline.pipeline.utils.output_checker import (
    OutputChecker,
    load_checks_config,
    run_output_checks,
)
from ..utils.plot_utils import (
    create_timeline_chart,
    create_status_donut,
    create_duration_radar,
    create_exit_code_bar
)

def _end_of_day(date_str):
    """Timestamps are stored as 'YYYY-MM-DD HH:MM:SS', so a bare end date would
    exclude everything recorded on that day."""
    return f"{date_str} 23:59:59" if date_str and len(date_str) == 10 else date_str


def _auto_detect_subjects(work_dir: str, prefix: str):
    """Return (subjects, None) on success or (None, Alert) on failure."""
    from ...pipeline.utils.detect_subjects import detect_subjects
    scan_dir = os.path.join(work_dir, "BIDS") if os.path.isdir(os.path.join(work_dir, "BIDS")) else work_dir
    subjects = detect_subjects(scan_dir, prefix)
    if not subjects:
        return None, dbc.Alert(f"No subjects auto-detected in {scan_dir}.", color="warning")
    return subjects, None


def _parse_sessions(session_input):
    """Return (sessions, None) on success or (None, Alert) when unusable.

    A blank session used to fall back to "*", which globs every session at
    once: a required file present in any one of them satisfied the check and
    the missing sessions were reported as PASS.
    """
    sessions = ([s.strip() for s in session_input.split(',') if s.strip()]
                if session_input and session_input.strip() else [])
    if not sessions:
        return None, dbc.Alert(
            "Please enter a session (e.g. 01, or 01,02). Checking every session at "
            "once would report a file found in any one session as a pass for all of "
            "them. Projects without sessions may enter any value.",
            color="warning",
        )
    return sessions, None


def _run_checks(checks_path: str, work_dir: str, prefix: str,
                sessions: list, task_filter, subjects: list):
    """Thin wrapper over the shared run_output_checks service."""
    tasks = [task_filter.strip()] if task_filter and task_filter.strip() else None
    df, _checked, _unconfigured = run_output_checks(
        config_path=checks_path, work_dir=work_dir, sessions=sessions,
        subjects=subjects, prefix=prefix, tasks=tasks,
    )
    return sessions, df


def _render_check_table(df: pd.DataFrame):
    """Render the output check results DataFrame as an HTML table with PASS/FAIL row colouring."""
    header = html.Thead(html.Tr([html.Th(col) for col in df.columns]))
    rows = []
    for _, row in df.iterrows():
        is_pass = str(row.get("status", "")).startswith("PASS")
        style = {"backgroundColor": "rgba(40,167,69,0.15)"} if is_pass else {"backgroundColor": "rgba(220,53,69,0.15)"}
        rows.append(html.Tr([html.Td(str(row[col])) for col in df.columns], style=style))
    return html.Table(
        [header, html.Tbody(rows)],
        className="table table-sm table-bordered",
        style={"fontSize": "12px"}
    )


def register_job_monitor_callbacks(app):
    
    @app.callback(
        [Output("sql-query-results", "children"),
         Output("sql-query-charts", "children")],
        [Input("execute-sql-query-btn", "n_clicks")],
        [State("db-path", "value"),
         State("query-type", "value"),
         State("subject-filter", "value"),
         State("session-filter", "value"),
         State("task-filter", "value"),
         State("status-filter", "value"),
         State("date-range", "start_date"),
         State("date-range", "end_date"),
         State("execution-id-filter", "value")]
    )
    def execute_sql_query_callback(n_clicks, db_path, query_type, subject, session, task, status, start_date, end_date, execution_id):
        if n_clicks is None:
            return "Click 'Execute Query' to see results", ""
        
        if not db_path or not os.path.exists(db_path):
            return dbc.Alert(f"Database file not found: {db_path}", color="danger"), ""
        
        try:
            if query_type == "job_status":
                query = "SELECT * FROM job_status WHERE 1=1"
                params = []

                if subject:
                    query += " AND subject LIKE ?"
                    params.append(f"%{subject}%")

                if session:
                    query += " AND session LIKE ?"
                    params.append(f"%{session}%")

                if task:
                    query += " AND task_name LIKE ?"
                    params.append(f"%{task}%")

                if status and status != "all":
                    query += " AND status = ?"
                    params.append(status)

                if execution_id and execution_id.strip():
                    query += " AND execution_id = ?"
                    params.append(execution_id.strip())

                if start_date:
                    query += " AND start_time >= ?"
                    params.append(start_date)

                if end_date:
                    query += " AND start_time <= ?"
                    params.append(_end_of_day(end_date))

                query += " ORDER BY start_time DESC LIMIT 100"
                
            elif query_type == "command_outputs":
                query = "SELECT * FROM command_outputs WHERE 1=1"
                params = []
                
                if subject:
                    query += " AND subject LIKE ?"
                    params.append(f"%{subject}%")
                
                if task:
                    query += " AND task_name LIKE ?"
                    params.append(f"%{task}%")
                
                if start_date:
                    query += " AND execution_time >= ?"
                    params.append(start_date)
                
                if end_date:
                    query += " AND execution_time <= ?"
                    params.append(_end_of_day(end_date))
                
                query += " ORDER BY execution_time DESC LIMIT 100"
                
            elif query_type == "pipeline_executions":
                query = "SELECT * FROM pipeline_executions WHERE 1=1"
                params = []
                
                if session:
                    query += " AND session LIKE ?"
                    params.append(f"%{session}%")
                
                if start_date:
                    query += " AND execution_time >= ?"
                    params.append(start_date)
                
                if end_date:
                    query += " AND execution_time <= ?"
                    params.append(_end_of_day(end_date))
                
                if status and status != "all":
                    query += " AND status = ?"
                    params.append(status)
                
                query += " ORDER BY execution_time DESC LIMIT 50"
            
            elif query_type == "wrapper_scripts":
                query = "SELECT id, execution_id, task_name, job_id, submission_time, wrapper_path FROM wrapper_scripts WHERE 1=1"
                params = []

                if task:
                    query += " AND task_name LIKE ?"
                    params.append(f"%{task}%")

                if start_date:
                    query += " AND submission_time >= ?"
                    params.append(start_date)

                if end_date:
                    query += " AND submission_time <= ?"
                    params.append(_end_of_day(end_date))

                query += " ORDER BY submission_time DESC LIMIT 100"

            else:
                return dbc.Alert("Invalid query type", color="warning"), ""

            with closing(sqlite3.connect(db_path)) as conn:
                df = pd.read_sql_query(query, conn, params=params)

            if df.empty:
                return dbc.Alert("No data found matching the criteria", color="secondary"), ""
            
            table = dbc.Table.from_dataframe(
                df.head(50), 
                striped=True, 
                bordered=True, 
                hover=True,
                size='sm',
                style={'fontSize': '12px'}
            )
            
            results = html.Div([
                html.H6(f"Query Results ({len(df)} records found, showing first 50)"),
                html.Div(table, style={'overflowX': 'auto', 'maxHeight': '400px', 'overflowY': 'auto'})
            ])
            
            charts = create_query_charts(df, query_type)
            
            return results, charts
            
        except sqlite3.Error as e:
            return dbc.Alert(f"Database error: {str(e)}", color="danger"), ""
        except Exception as e:
            return dbc.Alert(f"Error executing query: {str(e)}", color="danger"), ""
    
    @app.callback(
        Output("export-status", "children"),
        [Input("export-csv-btn", "n_clicks")],
        [State("db-path", "value"),
         State("query-type", "value"),
         State("subject-filter", "value"),
         State("session-filter", "value"),
         State("task-filter", "value"),
         State("status-filter", "value"),
         State("execution-id-filter", "value")]
    )
    def export_csv_callback(n_clicks, db_path, query_type, subject, session, task, status, execution_id):
        if n_clicks is None:
            return ""
        
        if not db_path or not os.path.exists(db_path):
            return dbc.Alert("Database file not found", color="danger")
        
        try:
            if query_type == "job_status":
                query = "SELECT * FROM job_status WHERE 1=1"
                params = []

                if subject:
                    query += " AND subject LIKE ?"
                    params.append(f"%{subject}%")

                if session:
                    query += " AND session LIKE ?"
                    params.append(f"%{session}%")

                if task:
                    query += " AND task_name LIKE ?"
                    params.append(f"%{task}%")

                if status and status != "all":
                    query += " AND status = ?"
                    params.append(status)

                if execution_id and execution_id.strip():
                    query += " AND execution_id = ?"
                    params.append(execution_id.strip())

            elif query_type == "command_outputs":
                query = "SELECT * FROM command_outputs WHERE 1=1"
                params = []

                if subject:
                    query += " AND subject LIKE ?"
                    params.append(f"%{subject}%")

                if task:
                    query += " AND task_name LIKE ?"
                    params.append(f"%{task}%")

            elif query_type == "wrapper_scripts":
                query = "SELECT * FROM wrapper_scripts WHERE 1=1"
                params = []

                if task:
                    query += " AND task_name LIKE ?"
                    params.append(f"%{task}%")

                if execution_id and execution_id.strip():
                    query += " AND execution_id = ?"
                    params.append(execution_id.strip())

            elif query_type == "pipeline_executions":
                query = "SELECT * FROM pipeline_executions WHERE 1=1"
                params = []

                if session:
                    query += " AND session LIKE ?"
                    params.append(f"%{session}%")

                if status and status != "all":
                    query += " AND status = ?"
                    params.append(status)

            else:
                return dbc.Alert("Invalid query type", color="warning")

            with closing(sqlite3.connect(db_path)) as conn:
                df = pd.read_sql_query(query, conn, params=params)

            output_dir = os.path.dirname(db_path)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_path = os.path.join(output_dir, f"{query_type}_{timestamp}.csv")
            df.to_csv(csv_path, index=False)
            
            return dbc.Alert(f"Exported {len(df)} records to {csv_path}", color="success")
            
        except Exception as e:
            return dbc.Alert(f"Export failed: {str(e)}", color="danger")

    @app.callback(
        Output("force-rebuild-result", "children"),
        Input("force-rebuild-btn", "n_clicks"),
        State("work-dir-input", "value"),
        State("db-path", "value"),
        prevent_initial_call=True
    )
    def force_rebuild_callback(n_clicks, work_dir, db_path):
        if not work_dir:
            return dbc.Alert("Please enter the work directory.", color="warning")

        if not os.path.isdir(work_dir):
            return dbc.Alert(f"Directory not found: {work_dir}", color="danger")

        try:
            cmd = ["neuropipe", "force-rebuild", work_dir]
            if db_path and db_path.strip():
                cmd += ["--db-path", db_path.strip()]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode == 0:
                msg = result.stdout.strip() or "Rebuild complete."
                return dbc.Alert(
                    [html.Strong("Rebuild complete. "), msg],
                    color="success"
                )
            else:
                err = result.stderr.strip() or result.stdout.strip() or "Unknown error."
                return dbc.Alert(f"force-rebuild failed: {err}", color="danger")
        except subprocess.TimeoutExpired:
            return dbc.Alert("force-rebuild timed out after 300 seconds.", color="danger")
        except FileNotFoundError:
            return dbc.Alert(
                "neuropipe command not found. Make sure the package is installed in the active environment.",
                color="danger"
            )
        except Exception as e:
            return dbc.Alert(f"Error: {str(e)}", color="danger")

    @app.callback(
        Output("merge-logs-result", "children"),
        Input("merge-logs-btn", "n_clicks"),
        State("work-dir-input", "value"),
        State("db-path", "value"),
        prevent_initial_call=True
    )
    def merge_logs_callback(n_clicks, work_dir, db_path):
        if not work_dir:
            return dbc.Alert("Please enter the work directory.", color="warning")

        if not os.path.isdir(work_dir):
            return dbc.Alert(f"Directory not found: {work_dir}", color="danger")

        try:
            cmd = ["neuropipe", "merge-logs", work_dir]
            if db_path and db_path.strip():
                cmd += ["--db-path", db_path.strip()]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600
            )
            if result.returncode == 0:
                msg = result.stdout.strip() or "Sync complete."
                return dbc.Alert(
                    [html.Strong("Sync complete. "), msg, " Click 'Execute Query' to refresh results."],
                    color="success"
                )
            else:
                err = result.stderr.strip() or result.stdout.strip() or "Unknown error."
                return dbc.Alert(f"merge-logs failed: {err}", color="danger")
        except subprocess.TimeoutExpired:
            return dbc.Alert("merge-logs timed out after 600 seconds.", color="danger")
        except FileNotFoundError:
            return dbc.Alert(
                "neuropipe command not found. Make sure the package is installed in the active environment.",
                color="danger"
            )
        except Exception as e:
            return dbc.Alert(f"Error: {str(e)}", color="danger")

    @app.callback(
        Output("output-check-result", "children"),
        Input("run-output-check-btn", "n_clicks"),
        State("check-project-name", "value"),
        State("check-output-dir", "value"),
        State("check-subjects", "value"),
        State("check-task-filter", "value"),
        State("check-session", "value"),
        State("check-prefix", "value"),
        prevent_initial_call=True
    )
    def run_output_check_callback(n_clicks, project, work_dir, subjects_raw, task_filter, session, prefix):
        if not project:
            return dbc.Alert("Please enter a project name.", color="warning")
        if not work_dir:
            return dbc.Alert("Please enter the output data directory.", color="warning")

        sessions, err = _parse_sessions(session)
        if err:
            return err

        if subjects_raw and subjects_raw.strip():
            subjects = [s.strip() for s in subjects_raw.split(",") if s.strip()]
            if not subjects:
                return dbc.Alert("No valid subjects found in the subject list.", color="warning")
        else:
            subjects, err = _auto_detect_subjects(work_dir, prefix or "sub-")
            if err:
                return err

        try:
            checks_path = load_checks_config(project)
        except FileNotFoundError as e:
            return dbc.Alert(str(e), color="danger")
        except Exception as e:
            return dbc.Alert(f"Error loading checks config: {str(e)}", color="danger")

        try:
            sessions, df = _run_checks(checks_path, work_dir, prefix or "sub-", sessions, task_filter, subjects)
        except Exception as e:
            return dbc.Alert(f"Error running checks: {str(e)}", color="danger")

        if df.empty:
            return dbc.Alert(
                "No checks were run. Verify that task names in the checks file match those in config.yaml.",
                color="secondary"
            )

        n_pass = (df["status"] == "PASS").sum()
        n_fail = (df["status"] != "PASS").sum()
        failed_subjects = sorted(df.loc[df["status"] != "PASS", "subject"].unique().tolist())

        summary_items = [
            html.Strong(f"{n_pass} checks passed, {n_fail} checks failed. "),
        ]
        if failed_subjects:
            summary_items.append(f"Subjects with failures: {', '.join(failed_subjects)}")

        summary_color = "success" if n_fail == 0 else "warning"

        return html.Div([
            dbc.Alert(summary_items, color=summary_color, className="mb-3"),
            html.Div(
                _render_check_table(df),
                style={"overflowX": "auto", "maxHeight": "400px", "overflowY": "auto"}
            )
        ])

    @app.callback(
        Output("output-check-result", "children", allow_duplicate=True),
        Input("export-check-csv-btn", "n_clicks"),
        State("check-project-name", "value"),
        State("check-output-dir", "value"),
        State("check-subjects", "value"),
        State("check-task-filter", "value"),
        State("check-session", "value"),
        State("check-prefix", "value"),
        prevent_initial_call=True
    )
    def export_check_csv_callback(n_clicks, project, work_dir, subjects_raw, task_filter, session, prefix):
        if not project:
            return dbc.Alert("Please enter a project name.", color="warning")
        if not work_dir:
            return dbc.Alert("Please enter the output data directory.", color="warning")

        sessions, err = _parse_sessions(session)
        if err:
            return err

        if subjects_raw and subjects_raw.strip():
            subjects = [s.strip() for s in subjects_raw.split(",") if s.strip()]
        else:
            subjects, err = _auto_detect_subjects(work_dir, prefix or "sub-")
            if err:
                return err

        try:
            checks_path = load_checks_config(project)
        except FileNotFoundError as e:
            return dbc.Alert(str(e), color="danger")
        except Exception as e:
            return dbc.Alert(f"Error loading checks config: {str(e)}", color="danger")

        try:
            sessions, df = _run_checks(checks_path, work_dir, prefix or "sub-", sessions, task_filter, subjects)
            csv_path = OutputChecker(
                config_path=checks_path, work_dir=work_dir,
                prefix=prefix or "sub-", session=sessions[0],
            ).save_csv(df, work_dir)
        except Exception as e:
            return dbc.Alert(f"Error exporting CSV: {str(e)}", color="danger")

        return dbc.Alert(f"Exported to {csv_path}", color="success")

    @app.callback(
        Output("wrapper-inspect-result", "children"),
        Input("load-wrapper-btn", "n_clicks"),
        State("db-path", "value"),
        State("wrapper-task-filter", "value"),
        State("wrapper-job-id", "value"),
        prevent_initial_call=True
    )
    def load_wrapper_callback(n_clicks, db_path, task_filter, job_id):
        if not db_path or not os.path.exists(db_path):
            return dbc.Alert(f"Database file not found: {db_path}", color="danger")

        try:
            # wrapper_scripts carries no project or session of its own; both
            # come from the execution it belongs to. LEFT JOIN so wrappers
            # whose execution cannot be resolved are still shown.
            query = (
                "SELECT ws.*, pe.project_name, pe.session "
                "FROM wrapper_scripts ws "
                "LEFT JOIN pipeline_executions pe ON pe.execution_id = ws.execution_id "
                "WHERE 1=1"
            )
            params = []
            if task_filter and task_filter.strip():
                query += " AND ws.task_name LIKE ?"
                params.append(f"%{task_filter.strip()}%")
            if job_id and job_id.strip():
                query += " AND ws.job_id LIKE ?"
                params.append(f"{job_id.strip()}%")
            query += " ORDER BY ws.submission_time DESC LIMIT 1"

            with closing(sqlite3.connect(db_path)) as conn:
                df = pd.read_sql_query(query, conn, params=params)

            if df.empty:
                return dbc.Alert("No wrapper script found matching the filters.", color="secondary")

            row = df.iloc[0]

            SECTION_LABELS = [
                ("slurm_cmd",       "SLURM Submission Command"),
                ("basic_paths",     "Basic Paths and Configuration"),
                ("global_python",   "Global Python Environment"),
                ("env_modules",     "Environment Module Commands"),
                ("global_env_vars", "Global Environment Variables"),
                ("task_params",     "Task-Specific Parameters"),
                ("execute_cmd",     "Execute Command"),
            ]

            def _code_block(text):
                return html.Pre(
                    text or "(empty)",
                    style={
                        "backgroundColor": "#1e1e1e",
                        "color": "#d4d4d4",
                        "padding": "12px",
                        "borderRadius": "4px",
                        "fontSize": "12px",
                        "whiteSpace": "pre-wrap",
                        "wordBreak": "break-all",
                        "maxHeight": "200px",
                        "overflowY": "auto",
                    }
                )

            section_cards = []
            for col, label in SECTION_LABELS:
                content = str(row.get(col, "") or "")
                if not content.strip():
                    continue
                section_cards.append(
                    dbc.Card([
                        dbc.CardHeader(html.Strong(label)),
                        dbc.CardBody(_code_block(content))
                    ], className="mb-2")
                )

            full_content_card = dbc.Card([
                dbc.CardHeader(html.Strong("Full Wrapper Script")),
                dbc.CardBody(
                    html.Pre(
                        str(row.get("full_content", "") or ""),
                        style={
                            "backgroundColor": "#1e1e1e",
                            "color": "#d4d4d4",
                            "padding": "12px",
                            "borderRadius": "4px",
                            "fontSize": "11px",
                            "whiteSpace": "pre-wrap",
                            "wordBreak": "break-all",
                            "maxHeight": "400px",
                            "overflowY": "auto",
                        }
                    )
                )
            ], className="mb-2")

            project = row.get("project_name") or "unknown"
            session = row.get("session") or "unknown"
            meta = dbc.Alert([
                html.Strong(f"Task: {row.get('task_name', '')}"),
                f"   |   Job ID: {row.get('job_id', '')}",
                f"   |   Submitted: {row.get('submission_time', '')}",
                html.Br(),
                f"Project: {project}   |   Session: {session}",
                html.Br(),
                html.Small(f"Wrapper path: {row.get('wrapper_path', '')}", className="text-muted"),
            ], color="secondary", className="mb-3")

            return html.Div([meta] + section_cards + [full_content_card])

        except Exception as e:
            return dbc.Alert(f"Error loading wrapper: {str(e)}", color="danger")

    @app.callback(
        Output("generate-report-result", "children"),
        Input("generate-report-btn", "n_clicks"),
        State("db-path", "value"),
        State("report-project", "value"),
        State("report-session", "value"),
        State("report-check-results", "value"),
        State("report-output-path", "value"),
        prevent_initial_call=True
    )
    def generate_report_callback(n_clicks, db_path, project, session, check_results, output_path):
        if not db_path or not project:
            return dbc.Alert("Database path and project name are required.", color="warning")
        if not check_results or not check_results.strip():
            return dbc.Alert("Check Results CSV is required.", color="warning")
        if not os.path.exists(db_path):
            return dbc.Alert(f"Database not found: {db_path}", color="danger")
        try:
            from neuro_pipeline.pipeline.utils.report_generator import generate_report
            out = generate_report(
                db_path=db_path,
                project_name=project.strip(),
                check_results_path=check_results.strip(),
                output_path=output_path.strip() if output_path and output_path.strip() else None,
                session=session.strip() if session and session.strip() else None,
            )
            return dbc.Alert([
                "Report saved: ",
                html.Code(out, style={"fontSize": "12px"})
            ], color="success")
        except (FileNotFoundError, ValueError) as e:
            return dbc.Alert(str(e), color="danger")
        except Exception as e:
            return dbc.Alert(f"Error generating report: {str(e)}", color="danger")


def create_query_charts(df, query_type):
    """Create visualization charts based on query results"""
    charts = []
    
    try:
        if query_type == "job_status":
            layout_parts = []
            
            # Timeline chart
            if 'start_time' in df.columns:
                timeline_fig = create_timeline_chart(df)
                layout_parts.append(
                    dbc.Row([
                        dbc.Col(dcc.Graph(figure=timeline_fig), width=12)
                    ], className="mb-4")
                )
            
            # Duration Radar + Status Donut
            second_row_charts = []
            
            if 'duration_hours' in df.columns and 'task_name' in df.columns:
                radar_fig = create_duration_radar(df)
                second_row_charts.append(
                    dbc.Col(dcc.Graph(figure=radar_fig), width=6)
                )
            
            if 'status' in df.columns:
                donut_fig = create_status_donut(df)
                second_row_charts.append(
                    dbc.Col(dcc.Graph(figure=donut_fig), width=6)
                )
            
            if second_row_charts:
                layout_parts.append(
                    dbc.Row(second_row_charts, className="mb-4")
                )
            
            return html.Div(layout_parts)
        
        elif query_type == "pipeline_executions":
            if 'status' in df.columns:
                donut_fig = create_status_donut(df)
                charts.append(dcc.Graph(figure=donut_fig))
            
            if 'execution_time' in df.columns:
                df_renamed = df.rename(columns={'execution_time': 'start_time'})
                timeline_fig = create_timeline_chart(df_renamed)
                charts.append(dcc.Graph(figure=timeline_fig))
        
        elif query_type == "command_outputs":
            if 'exit_code' in df.columns:
                exit_fig = create_exit_code_bar(df)
                charts.append(dcc.Graph(figure=exit_fig))
    
    except Exception as e:
        charts.append(html.Div(f"Error creating charts: {str(e)}", className="text-danger"))
    
    if len(charts) == 0:
        return ""
    elif len(charts) == 1:
        return html.Div(charts)
    else:
        return dbc.Row([
            dbc.Col(charts[0], width=6),
            dbc.Col(charts[1], width=6)
        ])