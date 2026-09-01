"""
generate_sample_report.py

Renders report_html.py with realistic mock data so you can visually inspect
the output in a browser. Not a pytest test — run directly:

    python tests/generate_sample_report.py
    python tests/generate_sample_report.py --out /tmp/my_report.html
    python tests/generate_sample_report.py --session 01
"""

import argparse
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from neuromaestro.pipeline.utils.report_html import render_html

# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

SUBJECTS = [f"{i:03d}" for i in range(1, 21)]
SESSIONS = ["01", "02"]
TASKS = ["recon", "volume", "rest_preprocess", "rest_post",
         "dwi_preprocess", "dwi_post", "cards_preprocess"]

METADATA = {
    "execution_id":    20260401120000,
    "execution_time":  "2026-04-01 12:00:00",
    "command_line":    "neuromaestro run --subjects subjects.txt --input /data/BIDS "
                       "--output /data/processed --work /data/work --project GCDS --session 01,02 "
                       "--bids-prep rest,dwi --staged-prep cards",
    "project_name":    "GCDS",
    "session":         None,
    "input_dir":       "/data/BIDS",
    "output_dir":      "/data/processed/GCDS",
    "work_dir":        "/data/work/GCDS",
    "status":          "COMPLETED",
    "total_jobs":      len(SUBJECTS) * len(TASKS) * len(SESSIONS),
}

# Session 02 runs a subset of tasks (no dwi)
_SESS_TASKS = {
    "01": TASKS,
    "02": ["recon", "volume", "rest_preprocess", "rest_post", "cards_preprocess"],
}

_SESS_DATE = {"01": "2026-04-01", "02": "2026-04-15"}


def _make_job_status(session_filter=None):
    import random
    random.seed(42)
    rows = []
    sessions = [session_filter] if session_filter else SESSIONS
    for sess in sessions:
        tasks = _SESS_TASKS[sess]
        date = _SESS_DATE[sess]
        for subj in SUBJECTS:
            for task in tasks:
                if task in ("dwi_preprocess", "dwi_post") and int(subj) > 17:
                    continue
                status = "FAILED" if (int(subj) % 7 == 0 and task == "rest_preprocess") else "SUCCESS"
                dur = round(random.uniform(0.5, 4.0), 2) if status == "SUCCESS" else None
                rows.append({
                    "subject":        subj,
                    "task_name":      task,
                    "session":        sess,
                    "status":         status,
                    "duration_hours": dur,
                    "start_time":     f"{date} 1{int(subj) % 10}:00:00",
                    "end_time":       f"{date} 1{int(subj) % 10}:30:00" if dur else None,
                    "error_msg":      "OOM: killed by SLURM" if status == "FAILED" else None,
                    "exit_code":      1 if status == "FAILED" else 0,
                    "node_name":      f"node{(int(subj) % 4) + 1:02d}",
                })
    return rows


def _make_task_summary(sess_jobs, sess_subjects):
    from neuromaestro.pipeline.utils.report_generator import compute_task_summary
    return compute_task_summary(sess_jobs, sess_subjects)


def _make_failed_jobs(job_status):
    return [
        {
            "subject":    j["subject"],
            "task_name":  j["task_name"],
            "session":    j["session"],
            "status":     j["status"],
            "start_time": j["start_time"],
            "exit_code":  j["exit_code"],
            "error_msg":  j["error_msg"],
            "stderr":     "ERROR: fmriprep crashed\n  File proc.py, line 42\n  MemoryError",
            "stdout":     "Running preprocessing...\nLoading data...\n[killed]",
        }
        for j in job_status if j["status"] == "FAILED"
    ]


def _make_all_runs(job_status):
    runs = []
    for sess in SESSIONS:
        date = _SESS_DATE[sess]
        sess_jobs = [j for j in job_status if j["session"] == sess]
        runs.append({
            "label": f"{date} 08:00 (ses-{sess})",
            "tasks": ",".join(_SESS_TASKS[sess]),
            "jobs":  sess_jobs[:20],
        })
    return runs


def _make_check_df(session_filter=None):
    rows = []
    check_types = [("file_count", "*.nii.gz", 1), ("file_exists", "*desc-brain_mask*", 1)]
    sessions = [session_filter] if session_filter else SESSIONS
    for sess in sessions:
        for subj in SUBJECTS:
            for task in ("rest_preprocess", "cards_preprocess"):
                for check_type, pattern, expected in check_types:
                    actual = expected if int(subj) % 7 != 0 else 0
                    rows.append({
                        "task":       task,
                        "subject":    subj,
                        "session":    sess,
                        "check_type": check_type,
                        "pattern":    pattern,
                        "expected":   expected,
                        "actual":     actual,
                        "status":     "PASS" if actual == expected else "FAIL",
                    })
    return pd.DataFrame(rows)


def _make_wrapper_scripts():
    return [
        {
            "task_name":       task,
            "submission_time": "2026-04-01 08:00:00",
            "slurm_cmd":       f"sbatch --job-name={task} --array=1-20%15 wrapper_{task}.sh",
            "env_modules":     "ml Python/3.11.3\nml AFNI/24.3.06",
            "global_python":   ". /home/user/venv/bin/activate",
            "global_env_vars": f"export TASK={task}",
            "execute_cmd":     f"bash scripts/{task}.sh $SUBJECT $SESSION",
        }
        for task in TASKS
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="sample_report.html",
                        help="Output HTML path (default: sample_report.html)")
    parser.add_argument("--session", default=None,
                        help="Filter to a single session (e.g. 01). Omit to show all sessions.")
    args = parser.parse_args()

    job_status      = _make_job_status(args.session)
    failed_jobs     = _make_failed_jobs(job_status)
    all_runs        = _make_all_runs(job_status)
    check_df        = _make_check_df(args.session)
    wrapper_scripts = _make_wrapper_scripts()

    # Build per-session data (mirrors report_generator._build_sessions_data)
    active_sessions = [args.session] if args.session else SESSIONS
    sessions_data = []
    for sess in active_sessions:
        sess_jobs   = [j for j in job_status   if j["session"] == sess]
        sess_failed = [j for j in failed_jobs  if j["session"] == sess]
        sess_runs   = [
            {**r, "jobs": [j for j in r["jobs"] if j.get("session") == sess]}
            for r in all_runs
        ]
        sess_runs = [r for r in sess_runs if r["jobs"]]
        subj_in_sess = sorted(set(j["subject"] for j in sess_jobs), key=lambda x: x.lower())
        sess_check_df = check_df[check_df["session"].astype(str) == str(sess)] if not check_df.empty else check_df
        sessions_data.append({
            "session":         sess,
            "task_summary":    _make_task_summary(sess_jobs, subj_in_sess),
            "job_status":      sess_jobs,
            "all_subjects":    subj_in_sess,
            "all_tasks":       [t for t in TASKS if any(j["task_name"] == t for j in sess_jobs)],
            "failed_jobs":     sess_failed,
            "all_runs":        sess_runs,
            "check_df":        sess_check_df,
            "wrapper_scripts": wrapper_scripts,
        })

    html = render_html(
        metadata=METADATA,
        sessions_data=sessions_data,
        project_name="GCDS",
        session=args.session,
    )

    out = Path(args.out)
    out.write_text(html, encoding="utf-8")
    print(f"Report written to: {out.resolve()}")


if __name__ == "__main__":
    main()
