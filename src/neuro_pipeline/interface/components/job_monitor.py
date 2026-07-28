from dash import dcc, html
import dash_bootstrap_components as dbc
import os


def create_job_monitor_layout():
    return dbc.Container([
        dbc.Row([
            dbc.Col([
                html.H3("Job Monitor", className="mb-4"),
                html.Hr()
            ])
        ]),

        # Global session config — shared by all tabs
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Work Directory:", html_for="work-dir-input"),
                        dbc.Input(
                            id="work-dir-input",
                            type="text",
                            placeholder="/data/work/my_study",
                            value=os.getcwd(),
                        )
                    ], width=5),
                    dbc.Col([
                        dbc.Label("Database Path:", html_for="db-path"),
                        dbc.Input(
                            id="db-path",
                            type="text",
                            placeholder="e.g. {work_dir}/database/pipeline_jobs.db",
                            value=os.path.join(os.getcwd(), "database", "pipeline_jobs.db"),
                        )
                    ], width=7),
                ])
            ])
        ], className="mb-4"),

        dbc.Tabs([

            # ── Tab 1: Database Maintenance ─────────────────────────────────
            dbc.Tab(label="Database", tab_id="tab-db", children=[
                dbc.Alert([
                    html.I(className="fas fa-info-circle me-2"),
                    html.Strong("Setup: "),
                    "Fill in ",
                    html.Strong("Work Directory"),
                    " first. The database is auto-created at ",
                    html.Code("{work_dir}/database/pipeline_jobs.db"),
                    " on the first pipeline run. Set ",
                    html.Strong("Database Path"),
                    " to that file before querying or syncing."
                ], color="info", className="mt-3 mb-0"),
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Button(
                                    "Sync Database from JSONL Logs",
                                    id="merge-logs-btn",
                                    color="primary",
                                    className="me-2"
                                ),
                                html.Small([
                                    "Re-processes raw JSONL event logs and fills missing records. "
                                    "Use after a cluster crash or if the database looks incomplete. "
                                    "Processes files one at a time (each committed then archived), so it is safe to re-run: it resumes where it left off. "
                                    "This button is capped at 10 minutes; for a large backlog run ",
                                    html.Code("neuropipe merge-logs <work_dir>"),
                                    " in a terminal instead (no time limit).",
                                ], className="text-muted ms-2"),
                                html.Div(id="merge-logs-result", className="mt-3")
                            ])
                        ], className="mb-3"),
                        dbc.Row([
                            dbc.Col([
                                dbc.Button(
                                    "Force Rebuild Database",
                                    id="force-rebuild-btn",
                                    color="outline-danger",
                                    className="me-2"
                                ),
                                html.Small(
                                    "Rebuilds the database from all JSONL logs including archived files. "
                                    "Original is preserved; writes a new pipeline_jobs_rebuild_*.db next to it.",
                                    className="text-muted ms-2"
                                ),
                                html.Div(id="force-rebuild-result", className="mt-3")
                            ])
                        ])
                    ])
                ], className="mt-3")
            ]),

            # ── Tab 2: Query ────────────────────────────────────────────────
            dbc.Tab(label="Query", tab_id="tab-query", children=[
                html.Div([

                    # Wrapper Script Inspector
                    dbc.Card([
                        dbc.CardHeader(html.Strong("Wrapper Script Inspector")),
                        dbc.CardBody([
                            dbc.Row([
                                dbc.Col([
                                    dbc.Label("Task Name:", html_for="wrapper-task-filter"),
                                    dbc.Input(
                                        id="wrapper-task-filter",
                                        type="text",
                                        placeholder="e.g., rest_preprocess (leave empty for latest)"
                                    )
                                ], width=6),
                                dbc.Col([
                                    dbc.Label("Job ID:", html_for="wrapper-job-id"),
                                    dbc.Input(
                                        id="wrapper-job-id",
                                        type="text",
                                        placeholder="e.g., 12345 (leave empty for latest)"
                                    )
                                ], width=4),
                                dbc.Col([
                                    dbc.Button(
                                        "Load Wrapper",
                                        id="load-wrapper-btn",
                                        color="primary",
                                        className="mt-4"
                                    )
                                ], width=2)
                            ]),
                            html.Div(id="wrapper-inspect-result", className="mt-3")
                        ])
                    ], className="mt-3 mb-3"),

                    # Query Configuration
                    dbc.Card([
                        dbc.CardHeader(html.Strong("Query Configuration")),
                        dbc.CardBody([
                            dbc.Row([
                                dbc.Col([
                                    dbc.Label("Query Type:", html_for="query-type"),
                                    dcc.Dropdown(
                                        id="query-type",
                                        options=[
                                            {"label": "Job Status",          "value": "job_status"},
                                            {"label": "Command Outputs",      "value": "command_outputs"},
                                            {"label": "Pipeline Executions",  "value": "pipeline_executions"},
                                            {"label": "Wrapper Scripts",      "value": "wrapper_scripts"},
                                        ],
                                        value="job_status",
                                        className="mb-3"
                                    )
                                ], width=4),
                                dbc.Col([
                                    dbc.Label("Date Range:", html_for="date-range"),
                                    dcc.DatePickerRange(
                                        id="date-range",
                                        start_date_placeholder_text="Start Date",
                                        end_date_placeholder_text="End Date",
                                        className="mb-3"
                                    )
                                ], width=8)
                            ]),
                            dbc.Row([
                                dbc.Col([
                                    dbc.Label("Subject:", html_for="subject-filter"),
                                    dbc.Input(id="subject-filter", type="text",
                                              placeholder="e.g., 001", className="mb-3")
                                ], width=3),
                                dbc.Col([
                                    dbc.Label("Session:", html_for="session-filter"),
                                    dbc.Input(id="session-filter", type="text",
                                              placeholder="e.g., 01", className="mb-3")
                                ], width=2),
                                dbc.Col([
                                    dbc.Label("Task:", html_for="task-filter"),
                                    dbc.Input(id="task-filter", type="text",
                                              placeholder="e.g., unzip", className="mb-3")
                                ], width=2),
                                dbc.Col([
                                    dbc.Label("Execution ID:", html_for="execution-id-filter"),
                                    dbc.Input(id="execution-id-filter", type="text",
                                              placeholder="e.g., 3", className="mb-3"),
                                    html.Small("Pipeline run ID — filter by this to isolate one run when a task was submitted multiple times.",
                                               className="text-muted")
                                ], width=2),
                                dbc.Col([
                                    dbc.Label("Status:", html_for="status-filter"),
                                    dcc.Dropdown(
                                        id="status-filter",
                                        options=[
                                            {"label": "All",       "value": "all"},
                                            {"label": "Success",   "value": "SUCCESS"},
                                            {"label": "Failed",    "value": "FAILED"},
                                            {"label": "Cancelled", "value": "CANCELLED"},
                                        ],
                                        value="all",
                                        className="mb-3"
                                    )
                                ], width=3),
                            ]),
                            dbc.Row([
                                dbc.Col([
                                    dbc.Button("Execute Query", id="execute-sql-query-btn",
                                               color="primary", className="me-2"),
                                    dbc.Button("Export CSV", id="export-csv-btn",
                                               color="secondary"),
                                    html.Div(id="export-status", className="mt-3")
                                ])
                            ])
                        ])
                    ], className="mb-3"),

                    # Visualizations
                    dbc.Card([
                        dbc.CardHeader(html.Strong("Visualizations")),
                        dbc.CardBody([html.Div(id="sql-query-charts")])
                    ], className="mb-3"),

                    # Results Table
                    dbc.Card([
                        dbc.CardHeader(html.Strong("Query Results")),
                        dbc.CardBody([html.Div(id="sql-query-results")])
                    ]),
                ])
            ]),

            # ── Tab 3: QA & Report ──────────────────────────────────────────
            dbc.Tab(label="QA & Report", tab_id="tab-qa", children=[
                html.Div([

                    # Output File Check
                    dbc.Card([
                        dbc.CardHeader(html.Strong("Output File Check")),
                        dbc.CardBody([
                            dbc.Row([
                                dbc.Col([
                                    dbc.Label("Output Data Directory:", html_for="check-output-dir"),
                                    dbc.Input(id="check-output-dir", type="text",
                                              placeholder="/data/processed/my_study",
                                              value=os.getcwd(), className="mb-1"),
                                    html.Small([
                                        "The folder that directly contains ",
                                        html.Code("BIDS/"),
                                        ", ",
                                        html.Code("AFNI_derivatives/"),
                                        ", etc. (your run's ",
                                        html.Code("--output"),
                                        " dir with the project name appended), not the log/database Work Directory above.",
                                    ], className="text-muted"),
                                ], width=12),
                            ], className="mb-3"),
                            dbc.Row([
                                dbc.Col([
                                    dbc.Label("Project Name:", html_for="check-project-name"),
                                    dbc.Input(id="check-project-name", type="text",
                                              placeholder="e.g., branch", className="mb-3")
                                ], width=3),
                                dbc.Col([
                                    dbc.Label("Subjects (comma-separated):", html_for="check-subjects"),
                                    dbc.Input(id="check-subjects", type="text",
                                              placeholder="001,002,003", className="mb-3")
                                ], width=4),
                                dbc.Col([
                                    dbc.Label("Task Filter (optional):", html_for="check-task-filter"),
                                    dbc.Input(id="check-task-filter", type="text",
                                              placeholder="e.g., rest_preprocess", className="mb-3")
                                ], width=3),
                                dbc.Col([
                                    dbc.Label("Session(s) (required):", html_for="check-session"),
                                    dbc.Input(id="check-session", type="text",
                                              placeholder="01 or 01,02", value="01", className="mb-3")
                                ], width=2),
                                dbc.Col([
                                    dbc.Label("Prefix:", html_for="check-prefix"),
                                    dbc.Input(id="check-prefix", type="text",
                                              placeholder="sub-", value="sub-", className="mb-3")
                                ], width=1),
                            ]),
                            dbc.Row([
                                dbc.Col([
                                    dbc.Button("Run Output Check", id="run-output-check-btn",
                                               color="primary", className="me-2"),
                                    dbc.Button("Export Check CSV", id="export-check-csv-btn",
                                               color="secondary"),
                                    html.Div(id="output-check-result", className="mt-3")
                                ])
                            ])
                        ])
                    ], className="mt-3 mb-3"),

                    # Generate Report
                    dbc.Card([
                        dbc.CardHeader(html.Strong("Generate Report")),
                        dbc.CardBody([
                            dbc.Row([
                                dbc.Col([
                                    dbc.Label("Project Name:", html_for="report-project"),
                                    dbc.Input(id="report-project", type="text",
                                              placeholder="e.g., GCDS", className="mb-3")
                                ], width=3),
                                dbc.Col([
                                    dbc.Label("Session (optional):", html_for="report-session"),
                                    dbc.Input(id="report-session", type="text",
                                              placeholder="e.g., 01,02", className="mb-3")
                                ], width=2),
                                dbc.Col([
                                    dbc.Label("Check Results CSV:", html_for="report-check-results"),
                                    dbc.Input(id="report-check-results", type="text",
                                              placeholder="e.g., /data/work/check_results_20260421.csv", className="mb-3")
                                ], width=4),
                                dbc.Col([
                                    dbc.Label("Output Path (optional):", html_for="report-output-path"),
                                    dbc.Input(id="report-output-path", type="text",
                                              placeholder="File, or a folder (auto-named). Default: next to database",
                                              className="mb-3")
                                ], width=3),
                            ]),
                            dbc.Row([
                                dbc.Col([
                                    dbc.Button("Generate Report", id="generate-report-btn",
                                               color="primary", className="me-2"),
                                    html.Small(
                                        "Generates a standalone HTML report. Uses the Database Path above.",
                                        className="text-muted ms-2"
                                    ),
                                    html.Div(id="generate-report-result", className="mt-3")
                                ])
                            ])
                        ])
                    ]),
                ])
            ]),

        ], id="job-monitor-tabs", active_tab="tab-db"),

    ], fluid=True)
