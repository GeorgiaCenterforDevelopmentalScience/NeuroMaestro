import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

PLOT_COLORS = {
    'SUCCESS': '#10b981',
    'COMPLETED': '#10b981',   # pipeline_executions' name for SUCCESS
    'FAILED': '#ef4444',
    'RUNNING': '#3b82f6',
    'CANCELLED': '#f59e0b',
    'PENDING': '#f59e0b',
    'line': '#1f77b4',
    'fill': 'rgba(31, 119, 180, 0.3)',
    'peak': '#d62728'
}

def create_timeline_chart(df):
    if 'start_time' not in df.columns or df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No timestamp data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=14, color='gray')
        )
        return fig
    
    try:
        df = df.copy()
        df['start_time'] = pd.to_datetime(df['start_time'], format='mixed', errors='coerce')
        df = df.dropna(subset=['start_time'])
        
        if df.empty:
            raise ValueError("No valid dates found")
        
        df['week'] = df['start_time'].dt.to_period('W').dt.start_time
        weekly_counts = df.groupby('week').size().reset_index(name='count')
        
        if not weekly_counts.empty:
            date_range = pd.date_range(
                start=weekly_counts['week'].min(),
                end=weekly_counts['week'].max(),
                freq='W-MON'
            )
            full_range = pd.DataFrame({'week': date_range})
            weekly_counts = full_range.merge(weekly_counts, on='week', how='left').fillna(0)
        
        fig = go.Figure()
        
        fig.add_trace(go.Scatter(
            x=weekly_counts['week'],
            y=weekly_counts['count'],
            mode='lines',
            name='Jobs per Week',
            line=dict(color=PLOT_COLORS['line'], width=2),
            fill='tozeroy',
            fillcolor=PLOT_COLORS['fill'],
            hovertemplate='Week: %{x|%Y-%m-%d}<br>Jobs: %{y}<extra></extra>'
        ))
        
        if len(weekly_counts) > 0:
            max_count = weekly_counts['count'].max()
            if max_count > 0:
                peak_weeks = weekly_counts[weekly_counts['count'] == max_count]
                fig.add_trace(go.Scatter(
                    x=peak_weeks['week'],
                    y=peak_weeks['count'],
                    mode='markers',
                    marker=dict(
                        size=12,
                        color=PLOT_COLORS['peak'],
                        symbol='star',
                        line=dict(width=2, color='white')
                    ),
                    name='Peak Week',
                    hovertemplate='Peak: %{y} jobs<extra></extra>'
                ))
        
        fig.update_layout(
            title="Job Submission Timeline (Weekly)",
            xaxis_title="Week",
            yaxis_title="Number of Jobs",
            hovermode='x unified',
            height=400,
            xaxis=dict(
                showgrid=True,
                gridcolor='rgba(200, 200, 200, 0.3)',
                showline=True,
                linewidth=1,
                linecolor='lightgray',
                zeroline=False
            ),
            yaxis=dict(
                showgrid=True,
                gridcolor='rgba(200, 200, 200, 0.3)',
                showline=True,
                linewidth=1,
                linecolor='lightgray',
                zeroline=True,
                zerolinewidth=1,
                zerolinecolor='lightgray'
            ),
            paper_bgcolor='white',
            plot_bgcolor='rgba(245, 245, 250, 0.5)',
            font=dict(size=11),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )
        
        return fig
        
    except Exception as e:
        fig = go.Figure()
        fig.add_annotation(
            text=f"Error processing dates: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=14, color='red')
        )
        return fig


def create_status_donut(df):
    if 'status' not in df.columns or df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No status data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=14, color='gray')
        )
        return fig
    
    try:
        status_counts = df['status'].value_counts()
        total_jobs = len(df)
        
        colors = [PLOT_COLORS.get(status, '#6b7280') for status in status_counts.index]
        
        fig = go.Figure(data=[go.Pie(
            labels=status_counts.index,
            values=status_counts.values,
            hole=0.5,
            marker=dict(colors=colors, line=dict(color='white', width=2)),
            textinfo='label+percent',
            textposition='outside',
            hovertemplate='<b>%{label}</b><br>Count: %{value}<br>Percentage: %{percent}<extra></extra>'
        )])
        
        fig.add_annotation(
            text=f'<b>{total_jobs}</b><br>Total Jobs',
            x=0.5, y=0.5,
            font=dict(size=16, color='#374151'),
            showarrow=False
        )
        
        fig.update_layout(
            title="Job Status Distribution",
            height=400,
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=-0.2,
                xanchor="center",
                x=0.5
            ),
            paper_bgcolor='white',
            font=dict(size=11)
        )
        
        return fig
        
    except Exception as e:
        fig = go.Figure()
        fig.add_annotation(
            text=f"Error creating chart: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=14, color='red')
        )
        return fig


def create_duration_radar(df):
    def hex_to_rgb(hex_color):
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    if 'task_name' not in df.columns or 'duration_hours' not in df.columns or df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No duration data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=14, color='gray')
        )
        return fig
    
    try:
        df_valid = df[df['duration_hours'].notna() & (df['duration_hours'] > 0)].copy()
        
        if df_valid.empty:
            raise ValueError("No valid duration data")
        
        tasks = sorted(df_valid['task_name'].unique())
        n_tasks = len(tasks)
        
        if n_tasks == 0:
            raise ValueError("No tasks found")
        
        fig = make_subplots(
            rows=1, cols=1,
            specs=[[{'type': 'polar'}]]
        )
        
        avg_durations = []
        for task in tasks:
            task_data = df_valid[df_valid['task_name'] == task]['duration_hours']
            avg_durations.append(task_data.mean())
        
        color = PLOT_COLORS['line']
        r, g, b = hex_to_rgb(color)
        fill_color_rgba = f'rgba({r}, {g}, {b}, 0.3)'
        
        fig.add_trace(
            go.Scatterpolar(
                r=avg_durations,
                theta=tasks,
                fill='toself',
                name='Avg Duration',
                line=dict(color=color, width=2),
                fillcolor=fill_color_rgba,
                showlegend=False,
                hovertemplate='%{theta}<br>Avg: %{r:.2f}h<extra></extra>'
            )
        )
        
        fig.update_polars(
            radialaxis=dict(
                visible=True,
                range=[0, max(avg_durations) * 1.2] if avg_durations and max(avg_durations) > 0 else [0, 1],
                showline=True,
                linewidth=1,
                gridcolor='rgba(150, 150, 150, 0.5)'
            ),
            angularaxis=dict(
                linewidth=1,
                showline=True,
                gridcolor='rgba(150, 150, 150, 0.5)'
            ),
            bgcolor='rgba(0, 0, 0, 0)'
        )
        
        fig.update_layout(
            title="Average Duration by Task",
            height=400,
            showlegend=False,
            paper_bgcolor='white',
            plot_bgcolor='rgba(240, 240, 240, 0.5)',
            font=dict(size=11),
            hoverlabel=dict(
                bgcolor='rgba(50, 50, 50, 0.9)',
                font_size=12,
                font_family="Arial",
                font_color='white'
            )
        )
        
        return fig
        
    except Exception as e:
        fig = go.Figure()
        fig.add_annotation(
            text=f"Error creating chart: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=14, color='red')
        )
        return fig


def create_exit_code_bar(df):
    if 'exit_code' not in df.columns or df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No exit code data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=14, color='gray')
        )
        return fig
    
    try:
        exit_counts = df['exit_code'].value_counts().sort_index()
        
        colors = [PLOT_COLORS['SUCCESS'] if code == 0 else PLOT_COLORS['FAILED'] 
                  for code in exit_counts.index]
        
        fig = go.Figure(data=[go.Bar(
            y=exit_counts.index.astype(str),
            x=exit_counts.values,
            orientation='h',
            marker=dict(color=colors),
            text=exit_counts.values,
            textposition='outside',
            hovertemplate='Exit Code: %{y}<br>Count: %{x}<extra></extra>'
        )])
        
        fig.update_layout(
            title="Command Exit Code Distribution",
            xaxis_title="Count",
            yaxis_title="Exit Code",
            height=max(300, len(exit_counts) * 40),
            xaxis=dict(showgrid=True, gridcolor='rgba(200, 200, 200, 0.3)'),
            yaxis=dict(showgrid=False),
            paper_bgcolor='white',
            plot_bgcolor='rgba(245, 245, 250, 0.5)',
            font=dict(size=11)
        )
        
        return fig
        
    except Exception as e:
        fig = go.Figure()
        fig.add_annotation(
            text=f"Error creating chart: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=14, color='red')
        )
        return fig