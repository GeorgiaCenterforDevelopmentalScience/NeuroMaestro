"""
test_plot_utils.py

Unit tests for the four Plotly chart factory functions in
neuro_pipeline.interface.utils.plot_utils.

All functions follow the same contract:
  - Accept a DataFrame
  - Always return a plotly.graph_objects.Figure (never raise)
  - Return a Figure with an annotation when data is missing or invalid
"""

import pytest
import pandas as pd
from plotly.graph_objects import Figure


def _is_figure(obj):
    return isinstance(obj, Figure)


def _placeholder_text(fig):
    """The annotation a chart falls back to when it has nothing to plot."""
    return " ".join(a.text or "" for a in fig.layout.annotations)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def job_status_df():
    return pd.DataFrame([
        {"subject": "001", "task_name": "rest_prep",   "status": "SUCCESS", "start_time": "2025-01-06", "duration_hours": 2.5},
        {"subject": "002", "task_name": "rest_prep",   "status": "FAILED",  "start_time": "2025-01-07", "duration_hours": 0.3},
        {"subject": "003", "task_name": "volume", "status": "SUCCESS", "start_time": "2025-01-13", "duration_hours": 1.8},
        {"subject": "004", "task_name": "volume", "status": "RUNNING", "start_time": "2025-01-14", "duration_hours": 0.5},
    ])


@pytest.fixture
def command_outputs_df():
    return pd.DataFrame([
        {"subject": "001", "task_name": "rest_prep", "exit_code": 0},
        {"subject": "002", "task_name": "rest_prep", "exit_code": 1},
        {"subject": "003", "task_name": "rest_prep", "exit_code": 0},
        {"subject": "004", "task_name": "rest_prep", "exit_code": 2},
    ])


# ---------------------------------------------------------------------------
# create_timeline_chart
# ---------------------------------------------------------------------------

class TestCreateTimelineChart:

    def test_returns_figure_for_valid_data(self, job_status_df):
        from neuro_pipeline.interface.utils.plot_utils import create_timeline_chart
        fig = create_timeline_chart(job_status_df)
        assert _is_figure(fig)

    def test_returns_figure_for_empty_df(self):
        from neuro_pipeline.interface.utils.plot_utils import create_timeline_chart
        fig = create_timeline_chart(pd.DataFrame())
        assert _is_figure(fig)
        # a blank Figure with no trace and no message would also pass isinstance
        assert _placeholder_text(fig).strip()
        assert fig.data == ()

    def test_returns_figure_when_start_time_missing(self):
        from neuro_pipeline.interface.utils.plot_utils import create_timeline_chart
        df = pd.DataFrame([{"subject": "001", "status": "SUCCESS"}])
        fig = create_timeline_chart(df)
        assert _is_figure(fig)
        assert _placeholder_text(fig).strip()

    def test_returns_figure_for_invalid_dates(self):
        from neuro_pipeline.interface.utils.plot_utils import create_timeline_chart
        df = pd.DataFrame([{"start_time": "not-a-date"}, {"start_time": "also-bad"}])
        fig = create_timeline_chart(df)
        assert _is_figure(fig)
        assert _placeholder_text(fig).strip()

    def test_has_at_least_one_trace_for_valid_data(self, job_status_df):
        from neuro_pipeline.interface.utils.plot_utils import create_timeline_chart
        fig = create_timeline_chart(job_status_df)
        assert len(fig.data) >= 1

    def test_single_date_does_not_crash(self):
        from neuro_pipeline.interface.utils.plot_utils import create_timeline_chart
        df = pd.DataFrame([{"start_time": "2025-03-01", "status": "SUCCESS"}])
        fig = create_timeline_chart(df)
        assert _is_figure(fig)

    def test_weekly_counts_sum_to_the_row_count(self, job_status_df):
        from neuro_pipeline.interface.utils.plot_utils import create_timeline_chart
        fig = create_timeline_chart(job_status_df)
        assert sum(fig.data[0].y) == len(job_status_df)

    def test_weeks_with_no_jobs_are_plotted_as_zero(self):
        # Both dates are Mondays three weeks apart, so the two idle weeks
        # between them must appear rather than be joined by a straight line
        from neuro_pipeline.interface.utils.plot_utils import create_timeline_chart
        df = pd.DataFrame([{"start_time": "2025-01-06"}, {"start_time": "2025-01-27"}])
        fig = create_timeline_chart(df)
        assert list(fig.data[0].y) == [1, 0, 0, 1]

    def test_peak_marker_sits_on_the_busiest_week(self):
        from neuro_pipeline.interface.utils.plot_utils import create_timeline_chart
        df = pd.DataFrame([{"start_time": "2025-01-06"}] * 3
                          + [{"start_time": "2025-01-13"}])
        fig = create_timeline_chart(df)
        assert list(fig.data[1].y) == [3]

    def test_unparseable_timestamps_are_dropped_not_counted(self):
        from neuro_pipeline.interface.utils.plot_utils import create_timeline_chart
        df = pd.DataFrame([{"start_time": "2025-01-06"}, {"start_time": "not a date"}])
        fig = create_timeline_chart(df)
        assert sum(fig.data[0].y) == 1


# ---------------------------------------------------------------------------
# create_status_donut
# ---------------------------------------------------------------------------

class TestCreateStatusDonut:

    def test_returns_figure_for_valid_data(self, job_status_df):
        from neuro_pipeline.interface.utils.plot_utils import create_status_donut
        fig = create_status_donut(job_status_df)
        assert _is_figure(fig)

    def test_returns_figure_for_empty_df(self):
        from neuro_pipeline.interface.utils.plot_utils import create_status_donut
        fig = create_status_donut(pd.DataFrame())
        assert _is_figure(fig)
        assert "No status data available" in _placeholder_text(fig)
        assert fig.data == ()

    def test_returns_figure_when_status_missing(self):
        from neuro_pipeline.interface.utils.plot_utils import create_status_donut
        df = pd.DataFrame([{"subject": "001"}])
        fig = create_status_donut(df)
        assert _is_figure(fig)
        assert "No status data available" in _placeholder_text(fig)

    def test_has_pie_trace_for_valid_data(self, job_status_df):
        from neuro_pipeline.interface.utils.plot_utils import create_status_donut
        fig = create_status_donut(job_status_df)
        assert len(fig.data) >= 1
        assert fig.data[0].type == "pie"

    def test_all_same_status(self):
        from neuro_pipeline.interface.utils.plot_utils import create_status_donut
        df = pd.DataFrame([{"status": "SUCCESS"}] * 5)
        fig = create_status_donut(df)
        assert _is_figure(fig)

    def test_slice_values_match_the_status_counts(self, job_status_df):
        from neuro_pipeline.interface.utils.plot_utils import create_status_donut
        pie = create_status_donut(job_status_df).data[0]
        assert dict(zip(pie.labels, pie.values)) == {
            "SUCCESS": 2, "FAILED": 1, "RUNNING": 1,
        }

    def test_centre_annotation_reports_the_row_count(self, job_status_df):
        from neuro_pipeline.interface.utils.plot_utils import create_status_donut
        fig = create_status_donut(job_status_df)
        assert str(len(job_status_df)) in fig.layout.annotations[0].text

    def test_known_statuses_keep_their_palette_colour(self, job_status_df):
        from neuro_pipeline.interface.utils.plot_utils import (
            create_status_donut, PLOT_COLORS,
        )
        pie = create_status_donut(job_status_df).data[0]
        colors = dict(zip(pie.labels, pie.marker.colors))
        assert colors["SUCCESS"] == PLOT_COLORS["SUCCESS"]
        assert colors["FAILED"] == PLOT_COLORS["FAILED"]

    def test_status_outside_the_palette_falls_back_to_grey(self):
        from neuro_pipeline.interface.utils.plot_utils import create_status_donut
        fig = create_status_donut(pd.DataFrame([{"status": "NOT_A_REAL_STATUS"}]))
        assert fig.data[0].marker.colors[0] == "#6b7280"

    def test_completed_is_the_same_green_as_success(self):
        # pipeline_executions records COMPLETED for what job_status calls
        # SUCCESS; it used to fall through to the grey default
        from neuro_pipeline.interface.utils.plot_utils import (
            create_status_donut, PLOT_COLORS,
        )
        fig = create_status_donut(pd.DataFrame([{"status": "COMPLETED"}]))
        assert fig.data[0].marker.colors[0] == PLOT_COLORS["SUCCESS"]

    def test_every_declared_status_has_a_colour(self):
        """No status the GUI can filter for may render as the unknown grey."""
        from neuro_pipeline.interface.utils.plot_utils import create_status_donut
        from neuro_pipeline.interface.callbacks.job_monitor_callbacks import _QUERY_SPECS

        checked = 0
        for spec in _QUERY_SPECS.values():
            for value in spec["status_values"]:
                fig = create_status_donut(pd.DataFrame([{"status": value}]))
                assert fig.data[0].marker.colors[0] != "#6b7280", value
                checked += 1
        # otherwise an emptied status_values would make this pass silently
        assert checked == 7


# ---------------------------------------------------------------------------
# create_duration_radar
# ---------------------------------------------------------------------------

class TestCreateDurationRadar:

    def test_returns_figure_for_valid_data(self, job_status_df):
        from neuro_pipeline.interface.utils.plot_utils import create_duration_radar
        fig = create_duration_radar(job_status_df)
        assert _is_figure(fig)

    def test_returns_figure_for_empty_df(self):
        from neuro_pipeline.interface.utils.plot_utils import create_duration_radar
        fig = create_duration_radar(pd.DataFrame())
        assert _is_figure(fig)
        assert "No duration data available" in _placeholder_text(fig)
        assert fig.data == ()

    def test_returns_figure_when_columns_missing(self):
        from neuro_pipeline.interface.utils.plot_utils import create_duration_radar
        df = pd.DataFrame([{"subject": "001", "status": "SUCCESS"}])
        fig = create_duration_radar(df)
        assert _is_figure(fig)
        assert "No duration data available" in _placeholder_text(fig)

    def test_returns_figure_when_all_durations_zero(self):
        from neuro_pipeline.interface.utils.plot_utils import create_duration_radar
        df = pd.DataFrame([
            {"task_name": "task_a", "duration_hours": 0},
            {"task_name": "task_b", "duration_hours": 0},
        ])
        fig = create_duration_radar(df)
        assert _is_figure(fig)
        # every row is filtered out, so the chart must say so rather than
        # render an empty radar
        assert "No valid duration data" in _placeholder_text(fig)
        assert fig.data == ()

    def test_single_task_does_not_crash(self):
        from neuro_pipeline.interface.utils.plot_utils import create_duration_radar
        df = pd.DataFrame([{"task_name": "only_task", "duration_hours": 3.0}])
        fig = create_duration_radar(df)
        assert _is_figure(fig)

    def test_radius_is_the_mean_duration_per_task(self, job_status_df):
        from neuro_pipeline.interface.utils.plot_utils import create_duration_radar
        trace = create_duration_radar(job_status_df).data[0]
        means = dict(zip(trace.theta, trace.r))
        assert means["rest_prep"] == pytest.approx(1.4)
        assert means["volume"] == pytest.approx(1.15)

    def test_axes_are_ordered_by_task_name(self, job_status_df):
        from neuro_pipeline.interface.utils.plot_utils import create_duration_radar
        trace = create_duration_radar(job_status_df).data[0]
        assert list(trace.theta) == sorted(set(job_status_df["task_name"]))

    def test_non_positive_durations_are_excluded(self):
        # A job killed before it logged an end time records 0, which would drag
        # the task average down if it were counted
        from neuro_pipeline.interface.utils.plot_utils import create_duration_radar
        df = pd.DataFrame([
            {"task_name": "a", "duration_hours": 2.0},
            {"task_name": "a", "duration_hours": 0.0},
            {"task_name": "b", "duration_hours": -1.0},
        ])
        trace = create_duration_radar(df).data[0]
        assert list(trace.theta) == ["a"]
        assert list(trace.r) == [2.0]


# ---------------------------------------------------------------------------
# create_exit_code_bar
# ---------------------------------------------------------------------------

class TestCreateExitCodeBar:

    def test_returns_figure_for_valid_data(self, command_outputs_df):
        from neuro_pipeline.interface.utils.plot_utils import create_exit_code_bar
        fig = create_exit_code_bar(command_outputs_df)
        assert _is_figure(fig)

    def test_returns_figure_for_empty_df(self):
        from neuro_pipeline.interface.utils.plot_utils import create_exit_code_bar
        fig = create_exit_code_bar(pd.DataFrame())
        assert _is_figure(fig)
        assert "No exit code data available" in _placeholder_text(fig)
        assert fig.data == ()

    def test_returns_figure_when_exit_code_missing(self):
        from neuro_pipeline.interface.utils.plot_utils import create_exit_code_bar
        df = pd.DataFrame([{"subject": "001"}])
        fig = create_exit_code_bar(df)
        assert _is_figure(fig)
        assert "No exit code data available" in _placeholder_text(fig)

    def test_has_bar_trace_for_valid_data(self, command_outputs_df):
        from neuro_pipeline.interface.utils.plot_utils import create_exit_code_bar
        fig = create_exit_code_bar(command_outputs_df)
        assert len(fig.data) >= 1
        assert fig.data[0].type == "bar"

    def test_all_success_codes(self):
        from neuro_pipeline.interface.utils.plot_utils import create_exit_code_bar
        df = pd.DataFrame([{"exit_code": 0}] * 10)
        fig = create_exit_code_bar(df)
        assert _is_figure(fig)

    def test_axis_is_ordered_by_exit_code_not_by_frequency(self):
        # The regression: sorting by count made the code axis jump around
        from neuro_pipeline.interface.utils.plot_utils import create_exit_code_bar
        df = pd.DataFrame(
            [{"exit_code": 0}] * 2 + [{"exit_code": 1}] * 5 + [{"exit_code": 2}] * 1
        )
        fig = create_exit_code_bar(df)
        assert list(fig.data[0].y) == ["0", "1", "2"]

    def test_zero_exit_code_keeps_the_success_colour_after_sorting(self):
        from neuro_pipeline.interface.utils.plot_utils import (
            create_exit_code_bar, PLOT_COLORS,
        )
        df = pd.DataFrame([{"exit_code": 0}] * 2 + [{"exit_code": 1}] * 5)
        fig = create_exit_code_bar(df)
        colors = list(fig.data[0].marker.color)
        assert colors[0] == PLOT_COLORS["SUCCESS"]
        assert colors[1] == PLOT_COLORS["FAILED"]
