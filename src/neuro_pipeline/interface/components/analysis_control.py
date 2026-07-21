from dash import dcc, html
import dash_bootstrap_components as dbc
import dash_cytoscape as cyto
import os
from ...pipeline.utils.config_utils import get_bids_pipeline_names, get_staged_pipeline_names, get_intermed_task_names

def create_analysis_control_layout():
    """Create the analysis control layout with subject selection and pipeline options"""

    return dbc.Container([
        dbc.Row([
            dbc.Col([
                html.H3("Analysis Control", className="mb-4"),
                html.Hr()
            ])
        ]),

        # Pipeline Setup Section
        dbc.Row([
            dbc.Col([
                html.H4("Pipeline Setup", className="mb-3"),
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Config Directory:", html_for="config-dir-input"),
                                dbc.Input(
                                    id="config-dir-input",
                                    type="text",
                                    placeholder="/path/to/your/study/config",
                                    value=os.environ.get("CONFIG_DIR", ""),
                                    persistence=True,
                                    persistence_type="session",
                                )
                            ]),
                            dbc.Col([
                                dbc.Button("Apply", id="apply-config-dir-btn",
                                           color="primary", className="me-2"),
                                dbc.Button("Init", id="init-study-btn",
                                           color="dark")
                            ], width="auto", className="d-flex align-items-end")
                        ], className="align-items-end"),
                        html.Div(id="config-dir-status", className="mt-2")
                    ])
                ])
            ])
        ], className="mb-4"),

        # Subject Selection Section
        dbc.Row([
            dbc.Col([
                html.H4("Subject Selection", className="mb-3"),
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Subject Prefix:", html_for="subject-prefix"),
                                dbc.Input(
                                    id="subject-prefix",
                                    type="text",
                                    placeholder="e.g., sub-",
                                    value="sub-",
                                    className="mb-3",
                                    persistence=True,
                                    persistence_type="session",
                                )
                            ], width=2),
                            dbc.Col([
                                dbc.Label("Current Directory:", html_for="current-dir"),
                                dbc.Input(
                                    id="current-dir",
                                    type="text",
                                    value=os.getcwd(),
                                    className="mb-3",
                                    persistence=True,
                                    persistence_type="session",
                                )
                            ], width=7),
                            dbc.Col([
                                dbc.Button("Detect Subjects", id="detect-subjects-btn",
                                         color="primary", className="mt-4 me-2"),
                                dbc.Button("Clear", id="clear-subjects-btn",
                                         color="secondary", className="mt-4")
                            ], width=3)
                        ]),
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Or Enter Subject IDs (comma-separated):", html_for="manual-subjects"),
                                dbc.Input(
                                    id="manual-subjects",
                                    type="text",
                                    placeholder="e.g., 001,002,003 or sub-001,sub-002",
                                    className="mb-3",
                                    persistence=True,
                                    persistence_type="session",
                                )
                            ], width=12)
                        ]),
                        html.Div(id="subjects-detection-result", className="mb-3"),
                        html.Div(id="subjects-list-container")
                    ])
                ])
            ])
        ], className="mb-4"),

        # Pipeline Configuration Section
        dbc.Row([
            dbc.Col([
                html.H4("Pipeline Configuration", className="mb-3"),
                dbc.Card([
                    dbc.CardBody([
                        # Directory Settings
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Input Directory:", html_for="input-dir"),
                                dbc.Input(
                                    id="input-dir",
                                    type="text",
                                    placeholder="/path/to/input",
                                    className="mb-3",
                                    persistence=True,
                                    persistence_type="session",
                                )
                            ], width=4),
                            dbc.Col([
                                dbc.Label("Output Directory:", html_for="output-dir"),
                                dbc.Input(
                                    id="output-dir",
                                    type="text",
                                    placeholder="/path/to/output",
                                    className="mb-3",
                                    persistence=True,
                                    persistence_type="session",
                                )
                            ], width=4),
                            dbc.Col([
                                dbc.Label("Work Directory:", html_for="work-dir"),
                                dbc.Input(
                                    id="work-dir",
                                    type="text",
                                    placeholder="/path/to/work",
                                    className="mb-3",
                                    persistence=True,
                                    persistence_type="session",
                                )
                            ], width=4)
                        ]),

                        # Project Settings
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Project Name:", html_for="project-name"),
                                dbc.Input(
                                    id="project-name",
                                    type="text",
                                    placeholder="e.g., branch, study1",
                                    className="mb-3",
                                    persistence=True,
                                    persistence_type="session",
                                )
                            ], width=6),
                            dbc.Col([
                                dbc.Label("Session ID:", html_for="session-id"),
                                dbc.Input(
                                    id="session-id",
                                    type="text",
                                    value="01",
                                    className="mb-3",
                                    persistence=True,
                                    persistence_type="session",
                                )
                            ], width=6)
                        ]),

                        html.Hr(),

                        # Pipeline Modules
                        create_pipeline_modules_section()

                    ])
                ])
            ])
        ], className="mb-4"),

        # Execution Control
        dbc.Row([
            dbc.Col([
                html.H4("Execution Control", className="mb-3"),
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Checklist(
                                    id="dry-run-checkbox",
                                    options=[{"label": "Dry Run (Show commands without execution)", "value": "dry_run"}],
                                    value=["dry_run"],
                                    className="mb-2",
                                    persistence=True,
                                    persistence_type="session",
                                ),
                                dbc.Checklist(
                                    id="resume-checkbox",
                                    options=[{
                                        "label": [
                                            "Resume Mode ",
                                            dbc.Badge("skip completed subjects", color="secondary", className="ms-1")
                                        ],
                                        "value": "resume"
                                    }],
                                    value=[],
                                    className="mb-2",
                                    persistence=True,
                                    persistence_type="session",
                                ),
                                dbc.Checklist(
                                    id="skip-preflight-checkbox",
                                    options=[{"label": "Skip Preflight Checks", "value": "skip_preflight"}],
                                    value=[],
                                    className="mb-2",
                                    persistence=True,
                                    persistence_type="session",
                                ),
                                dbc.Checklist(
                                    id="skip-bids-validation-checkbox",
                                    options=[{"label": "Skip BIDS Validation", "value": "skip_bids_validation"}],
                                    value=[],
                                    className="mb-3",
                                    persistence=True,
                                    persistence_type="session",
                                )
                            ], width=4),
                            dbc.Col([
                                dbc.Button("Generate Command", id="generate-commands-btn",
                                         color="info", className="mb-3 me-2"),
                                dbc.Button("Execute Pipeline", id="execute-pipeline-btn",
                                         color="success", className="mb-3")
                            ], width=8)
                        ]),
                        dbc.Row([
                            dbc.Col([
                                html.Div(id="execution-status", className="mt-3")
                            ], width=12)
                        ])
                    ])
                ])
            ])
        ]),

        # Command Preview Section
        dbc.Row([
            dbc.Col([
                html.H4("Command Preview", className="mb-3 mt-4"),
                dbc.Card([
                    dbc.CardBody([
                        html.Pre(
                            id="command-preview",
                            style={
                                "backgroundColor": "#f5f5f5",
                                "padding": "15px",
                                "borderRadius": "5px",
                                "fontSize": "14px",
                                "fontFamily": "monospace",
                                "whiteSpace": "pre-wrap",
                                "wordWrap": "break-word"
                            }
                        )
                    ])
                ])
            ])
        ], className="mb-4"),

        # DAG Overview
        dbc.Row([
            dbc.Col([
                html.H4("Task Execution Order (DAG)", className="mb-1 mt-2"),
                html.P(
                    "This diagram shows how pipeline tasks are chained. "
                    "Each arrow means the downstream task waits for the upstream one to finish.",
                    className="text-muted small mb-3"
                ),
                dbc.Card([
                    dbc.CardBody([
                        create_dag_visualization()
                    ])
                ])
            ])
        ], className="mb-4")
    ], fluid=True)

def create_pipeline_modules_section():
    """Create the pipeline modules configuration section"""
    intermed_options = []
    bids_options = []
    staged_options = []

    return dbc.Row([
        dbc.Col([
            # Preprocessing
            dbc.Card([
                dbc.CardHeader("Preprocessing"),
                dbc.CardBody([
                    dbc.RadioItems(
                        id="prep-options",
                        options=[
                            {"label": "None", "value": "none"},
                            {"label": "Unzip", "value": "unzip"},
                            {"label": "Recon", "value": "recon"},
                            {"label": "Unzip + Recon", "value": "unzip_recon"}
                        ],
                        value="none",
                        inline=True,
                        persistence=True,
                        persistence_type="session",
                    )
                ])
            ], className="mb-3"),

            # intermed
            dbc.Card([
                dbc.CardHeader("Intermed Processing (--intermed):"),
                dbc.CardBody([
                    dbc.Checklist(
                        id="intermed-checklist",
                        options=intermed_options,
                        value=[],
                        inline=True,
                        persistence=True,
                        persistence_type="session",
                    )
                ])
            ], className="mb-3"),

            # BIDS Pipelines
            dbc.Card([
                dbc.CardHeader("BIDS Pipelines"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            dbc.Label("Preprocessing (--bids-prep):"),
                            dbc.Checklist(
                                id="bids-prep-checklist",
                                options=bids_options,
                                value=[],
                                inline=True,
                                persistence=True,
                                persistence_type="session",
                            )
                        ], width=6),
                        dbc.Col([
                            dbc.Label("Postprocessing (--bids-post):"),
                            dbc.Checklist(
                                id="bids-post-checklist",
                                options=bids_options,
                                value=[],
                                inline=True,
                                persistence=True,
                                persistence_type="session",
                            )
                        ], width=6)
                    ])
                ])
            ], className="mb-3"),

            # Staged Pipelines
            dbc.Card([
                dbc.CardHeader("Staged Pipelines"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            dbc.Label("Preprocessing (--staged-prep):"),
                            dbc.Checklist(
                                id="staged-prep-checklist",
                                options=staged_options,
                                value=[],
                                inline=True,
                                persistence=True,
                                persistence_type="session",
                            )
                        ], width=6),
                        dbc.Col([
                            dbc.Label("Postprocessing (--staged-post):"),
                            dbc.Checklist(
                                id="staged-post-checklist",
                                options=staged_options,
                                value=[],
                                inline=True,
                                persistence=True,
                                persistence_type="session",
                            )
                        ], width=6)
                    ])
                ])
            ], className="mb-3"),

            # Quality Control
            dbc.Card([
                dbc.CardHeader("Quality Control (MRIQC)"),
                dbc.CardBody([
                    dbc.RadioItems(
                        id="mriqc-options",
                        options=[
                            {"label": "None", "value": "none"},
                            {"label": "Individual", "value": "individual"},
                            {"label": "Group", "value": "group"},
                            {"label": "All", "value": "all"}
                        ],
                        value="none",
                        inline=True,
                        persistence=True,
                        persistence_type="session",
                    )
                ])
            ])
        ])
    ])

def build_dag_elements(prep_option, intermed_value, bids_prep, bids_post,
                       staged_prep, staged_post, mriqc_option):
    has_unzip = prep_option in ('unzip', 'unzip_recon')
    has_recon = prep_option in ('recon', 'unzip_recon')
    has_intermed = bool(intermed_value)
    has_mriqc_indiv = mriqc_option in ('individual', 'all')
    has_mriqc_group = mriqc_option in ('group', 'all')

    nodes, edges = [], []

    def node(nid, label, cls):
        nodes.append({'data': {'id': nid, 'label': label}, 'classes': cls})

    def edge(src, tgt, cls):
        edges.append({'data': {'source': src, 'target': tgt}, 'classes': cls})

    if has_unzip:
        node('unzip', 'Unzip', 'prep')
    if has_recon:
        node('recon', 'BIDS Conversion\n(recon)', 'prep')
    if has_unzip and has_recon:
        edge('unzip', 'recon', 'prep')
    if has_intermed:
        node('intermed', f'Intermed\n({", ".join(intermed_value)})', 'intermed')
        if has_recon:
            edge('recon', 'intermed', 'intermed')

    for p in (bids_prep or []):
        nid = f'bids_prep_{p}'
        node(nid, f'BIDS Prep\n({p})', 'bids')
        if has_recon:
            edge('recon', nid, 'bids')
    for p in (bids_post or []):
        nid_post = f'bids_post_{p}'
        node(nid_post, f'BIDS Post\n({p})', 'bids')
        nid_prep = f'bids_prep_{p}'
        if p in (bids_prep or []):
            edge(nid_prep, nid_post, 'bids')

    for p in (staged_prep or []):
        nid = f'staged_prep_{p}'
        node(nid, f'Staged Prep\n({p})', 'staged')
        if has_intermed:
            edge('intermed', nid, 'staged')
    for p in (staged_post or []):
        nid_post = f'staged_post_{p}'
        node(nid_post, f'Staged Post\n({p})', 'staged')
        if p in (staged_prep or []):
            edge(f'staged_prep_{p}', nid_post, 'staged')

    if has_mriqc_indiv:
        node('mriqc_indiv', 'MRIQC Individual', 'qc')
        if has_recon:
            edge('recon', 'mriqc_indiv', 'qc')
    if has_mriqc_group:
        node('mriqc_group', 'MRIQC Group', 'qc')
        if has_mriqc_indiv:
            edge('mriqc_indiv', 'mriqc_group', 'qc')
        elif has_recon:
            edge('recon', 'mriqc_group', 'qc')

    return nodes + edges


def _dag_stylesheet():
    colours = {
        'prep':       '#E67E22',
        'intermed': '#27AE60',
        'bids':       '#2980B9',
        'staged':     '#16A085',
        'qc':         '#8E44AD',
    }

    base = [
        {
            'selector': 'node',
            'style': {
                'content': 'data(label)',
                'text-valign': 'center',
                'text-halign': 'center',
                'text-wrap': 'wrap',
                'shape': 'round-rectangle',
                'width': '150px',
                'height': '50px',
                'font-size': '12px',
                'font-family': 'sans-serif',
                'background-opacity': 0,   # transparent fill
                'border-width': 2,
                'color': '#374151',        # dark-grey text for all nodes
                'font-weight': 'bold',
            }
        },
        {
            'selector': 'edge',
            'style': {
                'curve-style': 'bezier',
                'width': 1.5,
                'target-arrow-shape': 'triangle',
                'arrow-scale': 0.9,
            }
        },
    ]

    # Per-class overrides: only border / line / arrow colour changes
    for cls, colour in colours.items():
        base.append({
            'selector': f'.{cls}',
            'style': {
                'border-color': colour,
                'line-color': colour,
                'target-arrow-color': colour,
            }
        })

    return base


def _dag_legend():
    items = [
        ('#E67E22', 'Preprocessing'),
        ('#27AE60', 'Intermed'),
        ('#2980B9', 'BIDS pipelines'),
        ('#16A085', 'Staged pipelines'),
        ('#8E44AD', 'Quality Control'),
    ]
    badges = []
    for colour, label in items:
        badges.append(
            html.Span(
                label,
                style={
                    'display': 'inline-block',
                    'marginRight': '12px',
                    'padding': '2px 8px',
                    'borderRadius': '4px',
                    'border': f'2px solid {colour}',
                    'color': '#374151',
                    'fontSize': '12px',
                    'fontWeight': 'bold',
                }
            )
        )
    return html.Div(badges, className="mb-2")


def create_dag_visualization():
    return html.Div([
        html.Div([
            _dag_legend(),
            dbc.Button("Download PNG", id="dag-download-btn", color="outline-secondary",
                       size="sm", className="mb-2 float-end ms-2"),
            dbc.Button("Reset View", id="dag-reset-btn", color="outline-secondary",
                       size="sm", className="mb-2 float-end"),
        ], style={'overflow': 'hidden'}),
        cyto.Cytoscape(
            id='dag-overview',
            elements=[],
            stylesheet=_dag_stylesheet(),
            style={'width': '100%', 'height': '280px', 'backgroundColor': '#FAFAFA'},
            layout={
                'name': 'dagre',
                'rankDir': 'LR',
                'nodeSep': 40,
                'rankSep': 90,
                'spacingFactor': 1.0,
            },
            userZoomingEnabled=True,
            userPanningEnabled=True,
            autoungrabify=True,
        ),
        html.P(
            "Tip: BIDS and QC tasks wait for recon. Staged tasks wait for intermed (if selected), otherwise run in parallel with recon.",
            className="text-muted small mt-2"
        )
    ])