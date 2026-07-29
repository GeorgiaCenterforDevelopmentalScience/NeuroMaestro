import dash
from dash import dcc, html, Input, Output
import dash_bootstrap_components as dbc
import dash_cytoscape as cyto

cyto.load_extra_layouts()

# Import custom modules
from .components.analysis_control import create_analysis_control_layout
from .components.job_monitor import create_job_monitor_layout
from .components.project_config import create_project_config_page

app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.COSMO, # BOOTSTRAP COSMO
        "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css"
    ],
    suppress_callback_exceptions=True,
)

app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''

app.title = "GCDS Neuro Pipeline"

def create_sidebar():
    """Create the sidebar navigation"""
    return html.Div([
        html.Div([
            html.H2("GCDS Neuro Pipeline", className="text-white mb-4"),
            html.Hr(className="text-white"),
            dbc.Nav([
                dbc.NavLink([
                    html.I(className="fas fa-cogs me-2"),
                    "Analysis Control"
                ], href="/analysis-control", active="exact", className="text-white"),
                dbc.NavLink([
                    html.I(className="fas fa-cog me-2"),
                    "Project Config"
                ], href="/project-config", active="exact", className="text-white"),
                dbc.NavLink([
                    html.I(className="fas fa-chart-line me-2"),
                    "Job Monitor"
                ], href="/job-monitor", active="exact", className="text-white"),
            ], vertical=True, pills=True, className="mb-4"),
        ], className="p-3")
    ], className="bg-dark", style={"height": "100vh", "width": "250px"})

_SHOW = {"display": "block"}
_HIDE = {"display": "none"}

def create_main_layout():
    """Create the main layout with collapsible sidebar"""
    return html.Div([
        dcc.Location(id="url", refresh=False),
        dcc.Store(id="subjects-store"),
        dcc.Store(id="pipeline-commands-store"),
        dcc.Store(id="job-status-store"),
        dcc.Store(id="page-rendered-store"),

        # Sidebar toggle button
        html.Button([
            html.I(className="fas fa-bars")
        ], id="sidebar-toggle", className="sidebar-toggle", n_clicks=0),

        # Sidebar
        html.Div([
            create_sidebar()
        ], id="sidebar", className="sidebar sidebar-transition", style={"width": "250px"}),

        # Main content area
        html.Div([
            html.Div(create_analysis_control_layout(),
                     id="page-analysis-control", style=_SHOW),
            html.Div(create_project_config_page(),
                     id="page-project-config",   style=_HIDE),
            html.Div(create_job_monitor_layout(),
                     id="page-job-monitor",       style=_HIDE),
        ], id="main-content", className="main-content")
    ], id="app-container", className="theme-dark")


app.layout = create_main_layout()

# Import and register callbacks
from .callbacks import register_callbacks
register_callbacks(app)

# Page routing callback — toggles CSS display only; components stay in DOM
@app.callback(
    [Output("page-analysis-control", "style"),
     Output("page-project-config",   "style"),
     Output("page-job-monitor",      "style"),
     Output("page-rendered-store",   "data")],
    Input("url", "pathname")
)
def display_page(pathname):
    is_ac  = pathname in ("/", "/home", "/analysis-control") or pathname not in ("/project-config", "/job-monitor")
    is_pc  = pathname == "/project-config"
    is_jm  = pathname == "/job-monitor"
    return (
        _SHOW if is_ac else _HIDE,
        _SHOW if is_pc else _HIDE,
        _SHOW if is_jm else _HIDE,
        pathname,
    )


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8050)