from .analysis_callbacks import register_analysis_callbacks
from .config_callbacks import register_config_callbacks


def register_callbacks(app):
    from .job_monitor_callbacks import register_job_monitor_callbacks
    register_job_monitor_callbacks(app)
    register_analysis_callbacks(app)
    register_config_callbacks(app)
