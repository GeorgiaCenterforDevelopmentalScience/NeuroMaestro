#!/usr/bin/env python3
"""Generate a standalone HTML pipeline report from the job database."""

import os
import sqlite3
from datetime import datetime
from typing import Optional

import pandas as pd

from .report_html import render_html
from .config_utils import get_all_task_names


def _rows(conn: sqlite3.Connection, sql: str, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_report_data(db_path: str, project_name: str, session: Optional[str]) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Support comma-separated sessions (e.g. "01,02")
    sessions = [s.strip() for s in session.split(',') if s.strip()] if session else []
    if sessions:
        sess_ph = ','.join('?' * len(sessions))
        sess_filter_eq    = f" AND session IN ({sess_ph})"
        sess_filter_subq  = f"AND session IN ({sess_ph})"
        sess_filter_alias = f"AND js.session IN ({sess_ph})"
    else:
        sess_filter_eq = sess_filter_subq = sess_filter_alias = ""
    sess_params = sessions  # list of values to bind for one session placeholder group

    meta_sql = ("SELECT * FROM pipeline_executions WHERE project_name = ?"
                + sess_filter_eq
                + " ORDER BY execution_time DESC LIMIT 1")
    meta_params = [project_name] + sess_params
    meta_row = conn.execute(meta_sql, meta_params).fetchone()
    metadata = dict(meta_row) if meta_row else {}

    subj_sql = ("SELECT subjects FROM pipeline_executions WHERE project_name = ?"
                + sess_filter_eq)
    subj_rows = conn.execute(subj_sql, [project_name] + sess_params).fetchall()
    all_subjects: set = set()
    for row in subj_rows:
        if row[0]:
            all_subjects.update(s.strip() for s in row[0].split(',') if s.strip())

    if all_subjects:
        ph = ','.join('?' * len(all_subjects))
        latest_sql = f"""
            SELECT js.subject, js.task_name, js.session, js.status,
                   js.duration_hours, js.start_time, js.end_time,
                   js.error_msg, js.exit_code, js.node_name
            FROM job_status js
            INNER JOIN (
                SELECT subject, task_name, session, MAX(start_time) AS max_start
                FROM job_status
                WHERE subject IN ({ph})
                {sess_filter_subq}
                GROUP BY subject, task_name, session
            ) latest
              ON  js.subject   = latest.subject
              AND js.task_name = latest.task_name
              AND (js.session = latest.session
                   OR (js.session IS NULL AND latest.session IS NULL))
              AND js.start_time = latest.max_start
        """
        latest_params = list(all_subjects) + sess_params
        job_status = _rows(conn, latest_sql, latest_params)

        failed_sql = f"""
            SELECT js.subject, js.task_name, js.session, js.status,
                   js.start_time, js.exit_code, js.error_msg,
                   co.stderr, co.stdout
            FROM job_status js
            LEFT JOIN command_outputs co
              ON co.id = (
                    SELECT id FROM command_outputs
                    WHERE subject   = js.subject
                      AND task_name = js.task_name
                      AND (session  = js.session
                           OR (session IS NULL AND js.session IS NULL))
                    ORDER BY execution_time DESC LIMIT 1
                  )
            WHERE js.status = 'FAILED'
              AND js.subject IN ({ph})
              {sess_filter_alias}
            ORDER BY js.task_name, js.subject
        """
        failed_jobs = _rows(conn, failed_sql, latest_params)
    else:
        job_status = []
        failed_jobs = []

    exec_sql = ("SELECT execution_time, requested_tasks FROM pipeline_executions "
                "WHERE project_name = ?"
                + sess_filter_eq
                + " ORDER BY execution_time ASC")
    executions = _rows(conn, exec_sql, meta_params)

    if all_subjects:
        all_jobs_sql = f"""
            SELECT subject, task_name, session, status, start_time
            FROM job_status
            WHERE subject IN ({ph})
            {sess_filter_subq}
            ORDER BY start_time ASC
        """
        all_jobs = _rows(conn, all_jobs_sql, list(all_subjects) + sess_params)

        all_runs = []
        for i, ex in enumerate(executions):
            t0 = ex['execution_time']
            t1 = executions[i + 1]['execution_time'] if i + 1 < len(executions) else None
            run_jobs = [j for j in all_jobs
                        if j['start_time'] >= t0 and (t1 is None or j['start_time'] < t1)]
            if run_jobs:
                all_runs.append({
                    'label': t0[:16],
                    'tasks': ex.get('requested_tasks', ''),
                    'jobs':  run_jobs,
                })
    else:
        all_runs = []

    wrapper_sql = """
        SELECT ws.task_name, ws.submission_time, ws.slurm_cmd,
               ws.env_modules, ws.global_python, ws.global_env_vars,
               ws.execute_cmd
        FROM wrapper_scripts ws
        WHERE ws.submission_time = (
            SELECT MAX(submission_time) FROM wrapper_scripts
            WHERE task_name = ws.task_name
        )
        ORDER BY ws.task_name
    """
    wrapper_scripts = _rows(conn, wrapper_sql)

    conn.close()
    return {
        'metadata':        metadata,
        'all_subjects':    sorted(all_subjects, key=lambda x: x.lower()),
        'job_status':      job_status,
        'failed_jobs':     failed_jobs,
        'wrapper_scripts': wrapper_scripts,
        'all_runs':        all_runs,
    }


def compute_task_summary(job_status: list, all_subjects: list) -> list:
    df = (pd.DataFrame(job_status)
          if job_status
          else pd.DataFrame(columns=['subject', 'task_name', 'status', 'duration_hours', 'start_time']))

    # Resolved per call: config is only populated after set_config_dir()
    task_order = get_all_task_names()

    data_tasks = set(df['task_name'].unique()) if not df.empty else set()
    ordered = [t for t in task_order if t in data_tasks]
    extras  = sorted(data_tasks - set(ordered))
    all_tasks = ordered + extras

    total = len(all_subjects)
    rows = []
    for task in all_tasks:
        tdf = df[df['task_name'] == task] if not df.empty else df
        n_ok   = int((tdf['status'] == 'SUCCESS').sum())
        n_fail = int((tdf['status'] == 'FAILED').sum())
        n_none = total - len(tdf)

        durs = tdf[tdf['status'] == 'SUCCESS']['duration_hours'].dropna()
        if len(durs) >= 2:
            dur_str = f"{durs.mean():.1f}h ± {durs.std():.1f}h"
        elif len(durs) == 1:
            dur_str = f"{durs.iloc[0]:.1f}h"
        else:
            dur_str = "—"

        last_run = "—"
        if not tdf.empty and 'start_time' in tdf.columns:
            ts = tdf['start_time'].dropna().max()
            if ts:
                try:
                    last_run = datetime.fromisoformat(ts).strftime('%Y-%m-%d')
                except ValueError:
                    last_run = str(ts)[:10]

        rows.append({
            'task':    task,
            'total':   total,
            'ok':      n_ok,
            'failed':  n_fail,
            'not_run': n_none,
            'dur':     dur_str,
            'last':    last_run,
        })
    return rows


def ordered_tasks_from_summary(summary: list) -> list:
    return [r['task'] for r in summary]


def compute_suspicious_jobs(job_status: list, check_df=None) -> list:
    """Jobs recorded as SUCCESS whose output checks nevertheless failed.

    A job's status comes from the script's exit code, which is only the exit
    code of its last command: none of the analysis scripts set -e, so a
    mid-script failure still exits 0. Cross-referencing against the
    filesystem checks is what catches those.
    """
    if check_df is None or getattr(check_df, "empty", True):
        return []
    if not {"task", "subject", "status"} <= set(check_df.columns):
        return []

    succeeded = {
        (str(j.get("subject")), str(j.get("task_name")))
        for j in job_status
        if str(j.get("status") or "").upper() == "SUCCESS"
    }
    if not succeeded:
        return []

    failed = check_df[
        check_df["status"].astype(str).str.upper().str.startswith("FAIL")
    ]

    rows = []
    for _, r in failed.iterrows():
        key = (str(r["subject"]), str(r["task"]))
        if key in succeeded:
            rows.append({
                "subject":    str(r["subject"]),
                "task":       str(r["task"]),
                "check_type": str(r.get("check_type", "")),
                "pattern":    str(r.get("pattern", "")),
                "reason":     str(r.get("status", "")),
            })
    return sorted(rows, key=lambda x: (x["task"], x["subject"]))


def _build_sessions_data(
    job_status: list,
    failed_jobs: list,
    all_runs: list,
    check_df=None,
    wrapper_scripts: Optional[list] = None,
) -> list:
    raw_sessions = sorted(set(j['session'] for j in job_status if j.get('session')))
    if not raw_sessions:
        raw_sessions = [None]

    sessions_data = []
    for sess in raw_sessions:
        if sess is not None:
            sess_jobs   = [j for j in job_status  if j.get('session') == sess]
            sess_failed = [j for j in failed_jobs if j.get('session') == sess]
            sess_runs   = [
                {**r, 'jobs': [j for j in r['jobs'] if j.get('session') == sess]}
                for r in all_runs
            ]
            sess_runs = [r for r in sess_runs if r['jobs']]
            if (check_df is not None and not check_df.empty
                    and 'session' in check_df.columns):
                # '*' rows come from check-outputs run without --session; they
                # were globbed across sessions, so they apply to every session.
                sess_col = check_df['session'].astype(str)
                sess_check_df = check_df[(sess_col == str(sess)) | (sess_col == '*')]
            else:
                sess_check_df = check_df
        else:
            sess_jobs     = job_status
            sess_failed   = failed_jobs
            sess_runs     = all_runs
            sess_check_df = check_df

        subj_in_sess = sorted(
            set(j['subject'] for j in sess_jobs if j.get('subject')),
            key=lambda x: x.lower(),
        )
        task_summary = compute_task_summary(sess_jobs, subj_in_sess)
        sessions_data.append({
            'session':        sess,
            'task_summary':   task_summary,
            'job_status':     sess_jobs,
            'all_subjects':   subj_in_sess,
            'all_tasks':      ordered_tasks_from_summary(task_summary),
            'failed_jobs':    sess_failed,
            'all_runs':       sess_runs,
            'check_df':       sess_check_df,
            'suspicious':     compute_suspicious_jobs(sess_jobs, sess_check_df),
            'wrapper_scripts': wrapper_scripts or [],
        })
    return sessions_data


def generate_report(
    db_path: str,
    project_name: str,
    check_results_path: str,
    output_path: Optional[str] = None,
    session: Optional[str] = None,
) -> str:
    """Generate the HTML report and write it to disk. Returns the output path."""

    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    print(f"Reading database: {db_path}")
    data = get_report_data(db_path, project_name, session)

    if not data['all_subjects']:
        raise ValueError(
            f"No records found for project '{project_name}'"
            + (f", session '{session}'" if session else "")
            + ". Check --project / --session."
        )
    print(f"  {len(data['all_subjects'])} subject(s), "
          f"{len(data['job_status'])} job records")

    if not os.path.isfile(check_results_path):
        raise FileNotFoundError(f"check-results file not found: {check_results_path}")
    # dtype: subject/session must stay strings, otherwise "001" is parsed as
    # int 1 and no longer matches the job_status rows or renders correctly.
    check_df: Optional[pd.DataFrame] = pd.read_csv(
        check_results_path, dtype={"subject": str, "session": str}
    )
    print(f"  Loaded check-results: {len(check_df)} rows")

    sessions_data = _build_sessions_data(
        data['job_status'], data['failed_jobs'], data['all_runs'],
        check_df=check_df, wrapper_scripts=data['wrapper_scripts'],
    )

    html_content = render_html(
        metadata=data['metadata'],
        sessions_data=sessions_data,
        project_name=project_name,
        session=session,
    )

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    default_name = f"pipeline_report_{project_name}_{ts}.html"
    if not output_path:
        output_path = os.path.join(os.path.dirname(os.path.abspath(db_path)), default_name)
    elif os.path.isdir(output_path):
        output_path = os.path.join(output_path, default_name)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"Report saved: {output_path}")
    return output_path
