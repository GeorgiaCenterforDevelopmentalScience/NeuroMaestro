#!/usr/bin/env python3
"""HTML rendering for the pipeline report (CSS, section builders, render_html)."""

import html as html_module
from datetime import datetime
from itertools import groupby
from typing import Optional

import pandas as pd

from .config_utils import find_task_config_by_name


def _e(text) -> str:
    return html_module.escape(str(text) if text is not None else '')


CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 14px; color: #2c2c2c; background: #fff; line-height: 1.55;
}
.navbar {
    position: sticky; top: 0; z-index: 100;
    background: #fff; border-bottom: 2px solid #e4e4e4;
    display: flex; gap: 2px; align-items: center;
    padding: 8px 36px; margin: 0 -36px 24px;
    overflow-x: auto;
}
.navbar a {
    color: #555; text-decoration: none; font-size: 13px; font-weight: 500;
    padding: 5px 12px; border-radius: 4px; white-space: nowrap;
}
.navbar a:hover { background: #f0f0f0; color: #111; }
.navbar-sep { color: #ddd; padding: 0 2px; font-size: 16px; }
.container { max-width: 1150px; margin: 0 auto; padding: 28px 36px 60px; }
header { margin-bottom: 28px; }
h1 { font-size: 20px; font-weight: 600; margin-bottom: 4px; }
.subtitle { color: #666; font-size: 13px; margin-bottom: 14px; }
.meta-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 4px 32px;
    font-size: 13px;
}
.meta-item { display: flex; gap: 10px; }
.meta-label { color: #888; min-width: 72px; flex-shrink: 0; }
.meta-val { word-break: break-all; }
h2 {
    font-size: 15px; font-weight: 700;
    margin: 36px 0 14px;
    padding: 8px 12px;
    background: #f6f6f6; border-left: 3px solid #aaa;
    border-radius: 0 3px 3px 0;
    color: #222;
}
h3 {
    font-size: 13px; font-weight: 600;
    margin: 20px 0 8px;
    padding-bottom: 4px;
    border-bottom: 1px solid #e4e4e4;
    color: #444;
}
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th {
    background: #f6f6f6; font-weight: 600; padding: 7px 12px;
    text-align: left; border-bottom: 2px solid #ddd; white-space: nowrap;
}
td { padding: 6px 12px; border-bottom: 1px solid #f0f0f0; }
tr:last-child td { border-bottom: none; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.fail { color: #c0392b; font-weight: 500; }
.empty { color: #999; font-style: italic; font-size: 13px; padding: 6px 0; }
/* Status matrix (Subject × Task, text labels) */
.cell-ok     { background: #C5E0B3; text-align: center; font-size: 11px; color: #2d6a2d; }
.cell-fail   { background: #F8786E; text-align: center; font-size: 11px; color: #7a1a14; font-weight: 600; }
.cell-notrun { background: #ebebeb; text-align: center; font-size: 11px; color: #aaa; }
.matrix-wrap { overflow-x: auto; }
.matrix-wrap table { width: auto; }
.matrix-wrap th, .matrix-wrap td { padding: 4px 8px; white-space: nowrap; border: 1px solid #e8e8e8; }
.matrix-wrap th { background: #f6f6f6; font-size: 11px; }
/* Compact colour-block matrix (Output Validation) */
.dot-wrap { overflow-x: auto; margin-bottom: 6px; }
.dot-wrap table { width: auto; border-spacing: 2px; border-collapse: separate; }
.dot-wrap th {
    background: none; border: none; font-size: 10px; color: #888;
    font-weight: normal; padding: 0 3px; white-space: nowrap;
}
.dot-wrap td { border: none; padding: 0; }
.dot-row-label {
    font-size: 10px; color: #555; font-family: monospace;
    padding-right: 6px !important; white-space: nowrap; vertical-align: middle;
}
.dot { width: 10px; height: 10px; border-radius: 2px; display: block; }
.dot-ok     { background: #C5E0B3; }
.dot-fail   { background: #F8786E; }
.dot-notrun { background: #e8e8e8; }
.legend { display: flex; gap: 16px; font-size: 12px; color: #555; margin-bottom: 8px; }
.legend-dot { display: inline-block; width: 10px; height: 10px;
              border-radius: 2px; margin-right: 4px; vertical-align: middle; }
details { margin-bottom: 6px; }
details > summary {
    cursor: pointer; padding: 7px 12px;
    background: #f6f6f6; border: 1px solid #e4e4e4;
    border-radius: 3px; font-size: 13px;
    list-style: none; user-select: none;
}
details > summary::-webkit-details-marker { display: none; }
details > summary::before { content: '▶ '; font-size: 10px; color: #888; }
details[open] > summary::before { content: '▼ '; }
details > summary:hover { background: #ececec; }
details[open] > summary { margin-bottom: 8px; border-radius: 3px 3px 0 0; }
.details-body { padding: 10px 14px; border: 1px solid #e4e4e4;
                border-top: none; border-radius: 0 0 3px 3px; }
pre {
    font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', monospace;
    font-size: 11px; background: #f8f8f8; border: 1px solid #e8e8e8;
    padding: 10px 14px; overflow-x: auto; white-space: pre-wrap;
    word-break: break-all; line-height: 1.45; margin-top: 6px;
}
.appendix { margin-top: 40px; }
.appendix > summary { background: #f0f0f0; font-size: 12px; color: #666; font-style: italic; }
"""

_LEGEND = (
    '<div class="legend">'
    '<span><span class="legend-dot" style="background:#C5E0B3"></span>OK</span>'
    '<span><span class="legend-dot" style="background:#F8786E"></span>FAIL</span>'
    '<span><span class="legend-dot" style="background:#e8e8e8"></span>Not run</span>'
    '</div>'
)


def _subj_key(s: str) -> int:
    d = ''.join(filter(str.isdigit, s))
    return int(d) if d else 0


def _cell(status: str) -> str:
    s = (status or '').upper()
    if s == 'SUCCESS':
        return '<td class="cell-ok">OK</td>'
    if s == 'FAILED':
        return '<td class="cell-fail">FAIL</td>'
    return '<td class="cell-notrun">—</td>'


def _dot(status: str) -> str:
    s = (status or '').upper()
    if s == 'SUCCESS':
        return '<td><span class="dot dot-ok"></span></td>'
    if s == 'FAILED':
        return '<td><span class="dot dot-fail"></span></td>'
    return '<td><span class="dot dot-notrun"></span></td>'


def _section_task_summary(summary: list) -> str:
    if not summary:
        return '<p class="empty">No task data found.</p>'

    rows = []
    for r in summary:
        fail_cell = (f'<td class="num fail">{r["failed"]}</td>'
                     if r['failed'] > 0
                     else f'<td class="num">{r["failed"]}</td>')
        pct = f'{r["ok"] / r["total"] * 100:.0f}%' if r['total'] > 0 else '—'
        rows.append(
            f'<tr>'
            f'<td>{_e(r["task"])}</td>'
            f'<td class="num">{r["ok"]} / {r["total"]}</td>'
            f'<td class="num">{pct}</td>'
            f'{fail_cell}'
            f'<td class="num">{r["not_run"]}</td>'
            f'<td>{_e(r["dur"])}</td>'
            f'<td>{_e(r["last"])}</td>'
            f'</tr>'
        )
    return (
        '<table><thead><tr>'
        '<th>Task</th><th class="num">Completed</th><th class="num">%</th>'
        '<th class="num">Failed</th><th class="num">Not Run</th>'
        '<th>Avg Duration</th><th>Last Run</th>'
        '</tr></thead>'
        '<tbody>' + ''.join(rows) + '</tbody></table>'
    )


def _section_status_matrix(job_status: list, all_subjects: list, all_tasks: list) -> str:
    if not all_subjects or not all_tasks:
        return '<p class="empty">No data.</p>'

    sorted_subjects = sorted(all_subjects, key=_subj_key)
    status_map = {(j['subject'], j['task_name']): j.get('status', '') for j in job_status}

    # Group/aggregate tasks (no `array` flag) run as one job; broadcast that single
    # result across every subject cell instead of leaving one OK and the rest "not run".
    group_status = {}
    for j in job_status:
        task = j['task_name']
        if (find_task_config_by_name(task) or {}).get('array'):
            continue
        st = j.get('status', '')
        if group_status.get(task) != 'FAILED':
            group_status[task] = st

    header = '<tr><th>Task</th>' + ''.join(f'<th>{_e(s)}</th>' for s in sorted_subjects) + '</tr>'
    rows = []
    for task in all_tasks:
        if task in group_status:
            cells = ''.join(_cell(group_status[task]) for _ in sorted_subjects)
        else:
            cells = ''.join(_cell(status_map.get((subj, task), '')) for subj in sorted_subjects)
        rows.append(f'<tr><td>{_e(task)}</td>{cells}</tr>')

    return (
        _LEGEND +
        '<div class="matrix-wrap">'
        f'<table><thead>{header}</thead><tbody>{"".join(rows)}</tbody></table>'
        '</div>'
    )


def _section_history_table(all_runs: list, all_tasks: list) -> str:
    """Task × Run colour-block matrix, collapsed by default."""
    if not all_runs:
        return '<p class="empty">Only one run recorded.</p>'

    # Aggregate per (task, run): worst-case status
    # FAILED > NOT_RUN > SUCCESS
    run_labels = [r['label'] for r in all_runs]

    status_map: dict = {}
    for run in all_runs:
        label = run['label']
        tasks_seen: dict = {}
        for j in run['jobs']:
            task = j['task_name']
            st   = j.get('status', '')
            prev = tasks_seen.get(task, '')
            # worst-first: FAILED beats everything
            if prev == 'FAILED':
                pass
            elif st == 'FAILED':
                tasks_seen[task] = 'FAILED'
            elif st == 'SUCCESS' and prev != 'FAILED':
                tasks_seen[task] = 'SUCCESS'
        for task, st in tasks_seen.items():
            status_map[(task, label)] = st

    # Collect tasks present across all runs, preserve TASK_ORDER
    tasks_in_history = [t for t in all_tasks if any((t, lbl) in status_map for lbl in run_labels)]

    header = (
        '<tr><th>Task</th>' +
        ''.join(
            f'<th title="{_e(r.get("tasks",""))}">{_e(lbl)}</th>'
            for r, lbl in zip(all_runs, run_labels)
        ) +
        '</tr>'
    )

    rows = []
    for task in tasks_in_history:
        dots = ''.join(_dot(status_map.get((task, lbl), '')) for lbl in run_labels)
        rows.append(f'<tr><td class="dot-row-label">{_e(task)}</td>{dots}</tr>')

    matrix = (
        _LEGEND +
        '<div class="dot-wrap">'
        f'<table><thead>{header}</thead><tbody>{"".join(rows)}</tbody></table>'
        '</div>'
    )
    return (
        f'<details>'
        f'<summary>Run history ({len(all_runs)} runs)</summary>'
        f'<div class="details-body">{matrix}</div>'
        f'</details>'
    )


def _section_check_results(check_df: Optional[pd.DataFrame]) -> str:
    if check_df is None or check_df.empty:
        return '<p class="empty">No check-results data provided (use --check-results).</p>'

    df = check_df.copy()
    df['subject'] = df['subject'].astype(str)
    df['row_key'] = df['task'] + '/' + df['check_type'].str.split(':').str[-1]
    row_keys = list(dict.fromkeys(df['row_key'].tolist()))
    subjects = sorted(
        df['subject'].unique().tolist(),
        key=lambda s: int(''.join(filter(str.isdigit, s)) or '0'),
    )

    status_map = {}
    for _, row in df.iterrows():
        is_fail = str(row.get('status', '')).upper().startswith('FAIL')
        status_map[(row['row_key'], row['subject'])] = 'FAILED' if is_fail else 'SUCCESS'

    n_fail = sum(1 for _, r in df.iterrows()
                 if str(r.get('status', '')).upper().startswith('FAIL'))
    n_total = len(df)

    header = '<tr><th>Task</th><th>Check</th>' + ''.join(f'<th>{_e(s)}</th>' for s in subjects) + '</tr>'

    # Group row_keys by task, use rowspan to merge the task cell
    grouped = [(task, list(rks)) for task, rks in
               groupby(row_keys, key=lambda rk: rk.split('/')[0])]

    rows = []
    for task, task_rks in grouped:
        n = len(task_rks)
        for i, rk in enumerate(task_rks):
            check = rk.split('/', 1)[1] if '/' in rk else rk
            dots = ''.join(_dot(status_map.get((rk, subj), '')) for subj in subjects)
            if i == 0:
                task_cell = (
                    f'<td class="dot-row-label" rowspan="{n}" '
                    f'style="vertical-align:middle;border-right:1px solid #e8e8e8">'
                    f'{_e(task)}</td>'
                )
            else:
                task_cell = ''
            rows.append(f'<tr><td class="dot-row-label">{_e(check)}</td>{dots}</tr>'
                        if task_cell == '' else
                        f'<tr>{task_cell}<td class="dot-row-label">{_e(check)}</td>{dots}</tr>')

    summary_line = f'{n_total} checks &nbsp;·&nbsp; '
    if n_fail == 0:
        summary_line += '<span style="color:#2d6a2d">All passed</span>'
    else:
        summary_line += f'<span class="fail">{n_fail} failed</span>'

    dot_matrix = (
        f'<p style="font-size:12px;color:#555;margin-bottom:8px">{summary_line}</p>'
        + _LEGEND +
        '<div class="dot-wrap">'
        f'<table><thead>{header}</thead><tbody>{"".join(rows)}</tbody></table>'
        '</div>'
    )

    # Collapsed detail table — only failed rows
    failed_df = df[df['status'].str.upper().str.startswith('FAIL')]
    if not failed_df.empty:
        detail_rows = []
        for _, r in failed_df.iterrows():
            detail_rows.append(
                f'<tr>'
                f'<td>{_e(r.get("task",""))}</td>'
                f'<td>{_e(r.get("subject",""))}</td>'
                f'<td>{_e(r.get("session",""))}</td>'
                f'<td>{_e(r.get("check_type",""))}</td>'
                f'<td style="font-size:12px;font-family:monospace">{_e(r.get("pattern",""))}</td>'
                f'<td class="num">{_e(r.get("actual",""))}</td>'
                f'</tr>'
            )
        detail_table = (
            '<table><thead><tr>'
            '<th>Task</th><th>Subject</th><th>Session</th>'
            '<th>Check Type</th><th>Pattern</th><th class="num">Actual</th>'
            '</tr></thead><tbody>' + ''.join(detail_rows) + '</tbody></table>'
        )
        detail_section = (
            f'<details style="margin-top:10px">'
            f'<summary>Failed checks ({n_fail})</summary>'
            f'<div class="details-body">{detail_table}</div>'
            f'</details>'
        )
    else:
        detail_section = ''

    return dot_matrix + detail_section


def _section_failed_jobs(failed_jobs: list) -> str:
    if not failed_jobs:
        return '<p class="empty">No failed jobs.</p>'

    by_task: dict = {}
    for j in failed_jobs:
        by_task.setdefault(j['task_name'], []).append(j)

    parts = []
    for task, jobs in sorted(by_task.items()):
        rows = []
        for j in jobs:
            ts = str(j.get('start_time', '') or '')[:16]
            exit_code = j.get('exit_code')
            stdout_raw = j.get('stdout') or ''
            log_html = (
                f'<details><summary style="font-size:11px;color:#888">stdout</summary>'
                f'<pre>{_e(stdout_raw)}</pre></details>'
                if stdout_raw.strip() else '<span style="color:#bbb">—</span>'
            )
            rows.append(
                f'<tr>'
                f'<td>{_e(j["subject"])}</td>'
                f'<td class="num">{_e(exit_code) if exit_code is not None else "—"}</td>'
                f'<td>{_e(ts)}</td>'
                f'<td>{log_html}</td>'
                f'</tr>'
            )
        table = (
            '<table style="table-layout:fixed;width:100%"><thead><tr>'
            '<th style="width:80px">Subject</th>'
            '<th style="width:48px" class="num">Exit</th>'
            '<th style="width:120px">Started</th>'
            '<th>Stdout</th>'
            '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>'
        )
        parts.append(
            f'<details>'
            f'<summary>{_e(task)}: {len(jobs)} failed</summary>'
            f'<div class="details-body">{table}</div>'
            f'</details>'
        )
    return '\n'.join(parts)


def _section_suspicious(suspicious: list) -> str:
    """Jobs that exited 0 but whose output checks failed."""
    if not suspicious:
        return ('<p class="empty">None. Every job reported as SUCCESS also '
                'passed its output checks.</p>')

    rows = []
    for r in suspicious:
        rows.append(
            f'<tr>'
            f'<td>{_e(r["task"])}</td>'
            f'<td>{_e(r["subject"])}</td>'
            f'<td>{_e(r["check_type"])}</td>'
            f'<td style="font-size:12px;font-family:monospace">{_e(r["pattern"])}</td>'
            f'<td class="fail">{_e(r["reason"])}</td>'
            f'</tr>'
        )

    n_subj = len({r["subject"] for r in suspicious})
    return (
        f'<p style="font-size:12px;color:#555;margin-bottom:8px">'
        f'<span class="fail">{len(suspicious)} check(s) across {n_subj} subject(s)</span>'
        f' reported SUCCESS but failed output validation. '
        f'A job\'s status is its script exit code, which does not guarantee '
        f'the outputs were written.</p>'
        '<table><thead><tr>'
        '<th>Task</th><th>Subject</th><th>Check Type</th>'
        '<th>Pattern</th><th>Failure</th>'
        '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>'
    )


def _section_environment(wrapper_scripts: list) -> str:
    if not wrapper_scripts:
        return '<p class="empty">No wrapper script records found.</p>'

    parts = []
    for w in wrapper_scripts:
        fields = [
            ('SLURM command',    w.get('slurm_cmd')),
            ('Modules',          w.get('env_modules')),
            ('Global Python',    w.get('global_python')),
            ('Environment vars', w.get('global_env_vars')),
            ('Execute command',  w.get('execute_cmd')),
        ]
        inner = []
        for label, val in fields:
            if val and str(val).strip():
                inner.append(
                    f'<p style="font-size:12px;color:#666;margin:8px 0 2px">'
                    f'<strong>{_e(label)}</strong></p>'
                    f'<pre>{_e(val)}</pre>'
                )
        if not inner:
            continue
        ts = str(w.get('submission_time', '') or '')[:16]
        parts.append(
            f'<details>'
            f'<summary>{_e(w["task_name"])} &nbsp;'
            f'<span style="color:#aaa;font-size:11px">last submitted {_e(ts)}</span>'
            f'</summary>'
            f'<div class="details-body">{"".join(inner)}</div>'
            f'</details>'
        )
    return '\n'.join(parts) if parts else '<p class="empty">No environment data recorded.</p>'


def render_html(
    metadata: dict,
    sessions_data: list,
    project_name: str,
    session: Optional[str],
) -> str:
    generated = datetime.now().strftime('%Y-%m-%d %H:%M')
    last_exec = str(metadata.get('execution_time', '') or '')[:16]

    # Nav bar
    nav_links = ['<a href="#summary">Summary</a>', '<span class="navbar-sep">|</span>']
    for sd in sessions_data:
        sess = sd['session']
        label  = f'Session {sess}' if sess else 'Jobs'
        anchor = f'session-{sess}' if sess else 'session-all'
        nav_links.append(f'<a href="#{_e(anchor)}">{_e(label)}</a>')
    navbar = '<nav class="navbar">' + ''.join(nav_links) + '</nav>'

    subtitle_parts = [f'Project: <strong>{_e(project_name)}</strong>']
    if session:
        subtitle_parts.append(f'Session: <strong>{_e(session)}</strong>')
    subtitle_parts.append(f'Generated: {_e(generated)}')

    meta_items = []
    for label, key in [('Input', 'input_dir'), ('Output', 'output_dir'), ('Work', 'work_dir')]:
        val = metadata.get(key, '')
        if val:
            meta_items.append(
                f'<div class="meta-item">'
                f'<span class="meta-label">{label}</span>'
                f'<span class="meta-val">{_e(val)}</span>'
                f'</div>'
            )
    if last_exec:
        meta_items.append(
            f'<div class="meta-item">'
            f'<span class="meta-label">Last run</span>'
            f'<span class="meta-val">{_e(last_exec)}</span>'
            f'</div>'
        )
    cmd_line = metadata.get('command_line', '')
    if cmd_line:
        meta_items.append(
            f'<div class="meta-item" style="grid-column:1/-1">'
            f'<span class="meta-label">Command</span>'
            f'<span class="meta-val" style="font-family:monospace;font-size:12px">'
            f'{_e(cmd_line)}</span>'
            f'</div>'
        )

    # Per-session sections
    session_html_parts = []
    for sd in sessions_data:
        sess   = sd['session']
        anchor = f'session-{sess}' if sess else 'session-all'
        title  = f'Session {_e(sess)}' if sess else 'Job Status'

        history_html = ''
        if len(sd['all_runs']) > 1:
            history_html = (
                f'<h3>Run History</h3>'
                f'{_section_history_table(sd["all_runs"], sd["all_tasks"])}'
            )

        session_html_parts.append(f'''
  <section id="{_e(anchor)}">
    <h2>{title}</h2>
    <h3>Task Completion</h3>
    {_section_task_summary(sd["task_summary"])}
    <h3>Subject × Task Status</h3>
    {_section_status_matrix(sd["job_status"], sd["all_subjects"], sd["all_tasks"])}
    {history_html}
    <h3>Failed Jobs</h3>
    {_section_failed_jobs(sd["failed_jobs"])}
    <h3>Reported SUCCESS but Output Check Failed</h3>
    {_section_suspicious(sd.get("suspicious") or [])}
    <h3>Output Validation</h3>
    {_section_check_results(sd.get("check_df"))}
    <details style="margin-top:20px" class="appendix">
      <summary>Environment &amp; Reproducibility (per task)</summary>
      <div class="details-body">
        {_section_environment(sd.get("wrapper_scripts") or [])}
      </div>
    </details>
  </section>''')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pipeline Report · {_e(project_name)}</title>
<style>
{CSS}
</style>
</head>
<body>
<div class="container">
  {navbar}

  <header id="summary">
    <h1>Pipeline Report</h1>
    <p class="subtitle">{'  &nbsp;|&nbsp;  '.join(subtitle_parts)}</p>
    <div class="meta-grid">{''.join(meta_items)}</div>
  </header>

{''.join(session_html_parts)}

</div>
</body>
</html>"""
