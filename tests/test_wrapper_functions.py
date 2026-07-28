"""
test_wrapper_functions.py — Tests for pipeline/utils/wrapper_functions.sh

Only the units that can run without a scheduler are covered:
  - execute_wrapper array-index guard (exits cleanly when the array range is
    wider than the subject list)
  - warn_if_failed (logging failures were masked by the tee pipeline)

Requires bash; skipped otherwise.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash")
WRAPPER = (Path(__file__).resolve().parent.parent
           / "src" / "neuro_pipeline" / "pipeline" / "utils" / "wrapper_functions.sh")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")


def run_bash(script: str, env: dict = None) -> subprocess.CompletedProcess:
    body = f'source "{WRAPPER.as_posix()}"\n{script}\n'
    return subprocess.run(
        [BASH, "-c", body],
        capture_output=True, text=True, env={**(env or {}), "PATH": "/usr/bin:/bin"},
    )


class TestArrayIndexGuard:

    def _run(self, num_subjects, array_task_id, extra_env=None):
        subjects = " ".join(f"{i:03d}" for i in range(1, num_subjects + 1))
        return run_bash(
            'execute_wrapper /nonexistent/script.sh\n'
            'echo "rc=$?"',
            env={"SUBJECTS": subjects, "SLURM_ARRAY_TASK_ID": str(array_task_id),
                 **(extra_env or {})},
        )

    def test_index_beyond_subject_count_exits_zero(self):
        result = self._run(num_subjects=2, array_task_id=5)
        assert "rc=0" in result.stdout

    def test_index_beyond_subject_count_reports_reason(self):
        result = self._run(num_subjects=2, array_task_id=5)
        assert "has no matching subject" in result.stdout

    def test_out_of_range_does_not_create_log_dirs(self, tmp_path):
        subjects = "001 002"
        log_dir = tmp_path / "log"
        run_bash(
            'execute_wrapper /nonexistent/script.sh',
            env={"SUBJECTS": subjects, "SLURM_ARRAY_TASK_ID": "9",
                 "LOG_DIR": str(log_dir), "TASK_NAME": "task1"},
        )
        assert not log_dir.exists()

    def test_boundary_index_equal_to_count_is_rejected(self):
        # 2 subjects -> valid task ids are 1 and 2; id 3 maps to index 2
        result = self._run(num_subjects=2, array_task_id=3)
        assert "has no matching subject" in result.stdout

    def test_last_valid_index_is_not_rejected(self, tmp_path):
        # Proceeds past the guard and stops at the missing script instead.
        result = self._run(num_subjects=2, array_task_id=2,
                           extra_env={"LOG_DIR": str(tmp_path / "log"),
                                      "TASK_NAME": "task1"})
        assert "has no matching subject" not in result.stdout
        assert "Script not found" in result.stdout


class TestWarnIfFailed:

    def test_nonzero_status_emits_warning(self):
        result = run_bash('LOG_PATH=/dev/null; warn_if_failed 1 "log job start"')
        assert "WARNING: Failed to log job start" in result.stdout

    def test_nonzero_status_includes_exit_code(self):
        result = run_bash('LOG_PATH=/dev/null; warn_if_failed 42 "log job end"')
        assert "exit 42" in result.stdout

    def test_zero_status_is_silent(self):
        result = run_bash('LOG_PATH=/dev/null; warn_if_failed 0 "log job start"')
        assert "WARNING" not in result.stdout

    def test_empty_status_treated_as_success(self):
        result = run_bash('LOG_PATH=/dev/null; warn_if_failed "" "log job start"')
        assert "WARNING" not in result.stdout

    def test_pipestatus_captures_command_not_tee(self):
        # The regression: `false | tee` leaves $? at 0, so the old
        # `... | tee || echo WARNING` form never fired.
        result = run_bash(
            'LOG_PATH=/dev/null\n'
            'false | tee -a /dev/null\n'
            'echo "dollar_question=$?"\n'
            'false | tee -a /dev/null\n'
            'warn_if_failed "${PIPESTATUS[0]}" "log job start"'
        )
        assert "dollar_question=0" in result.stdout
        assert "WARNING: Failed to log job start" in result.stdout
