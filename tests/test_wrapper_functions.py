"""
test_wrapper_functions.py — Tests for pipeline/utils/wrapper_functions.sh

Only the units that can run without a scheduler are covered:
  - execute_wrapper array-index guard (exits cleanly when the array range is
    wider than the subject list)
  - warn_if_failed (logging failures were masked by the tee pipeline)
  - resolve_scheduler_ids (array index and job id under SLURM, PBS Pro and Torque)
  - execute_script_with_logging (exit code and end status of the task script)
  - create_env_file (Python isolation after module loads)
"""

import subprocess
from pathlib import Path

WRAPPER = (Path(__file__).resolve().parent.parent
           / "src" / "neuromaestro" / "pipeline" / "utils" / "wrapper_functions.sh")


def run_bash(script: str, env: dict = None) -> subprocess.CompletedProcess:
    body = f'source "{WRAPPER.as_posix()}"\n{script}\n'
    return subprocess.run(
        ["bash", "-c", body],
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
        # without the :-0 default the test builtin errors here, which is also silent on stdout
        assert result.stderr == ""

    def test_pipestatus_captures_command_not_tee(self, tmp_path):
        # The regression: `false | tee` leaves $? at 0, so the old
        # `... | tee || echo WARNING` form never fired.
        script = tmp_path / "task.sh"
        script.write_text("exit 0\n")
        result = run_bash(
            # every job_db.py call in the wrapper goes through python3
            'python3() { return 3; }\n'
            f'LOG_PATH="{(tmp_path / "job.log").as_posix()}"\n'
            f'execute_script_with_logging "{script.as_posix()}" 001 recon'
        )
        for what in ("log job start", "log command output", "log job end"):
            assert f"WARNING: Failed to {what} (exit 3)" in result.stdout


class TestScriptExecution:

    def _run(self, tmp_path, exit_code):
        script = tmp_path / "task.sh"
        script.write_text(f"exit {exit_code}\n")
        calls = tmp_path / "calls.txt"
        result = run_bash(
            # record each job_db.py call instead of running it
            f'python3() {{ printf "%s\\n" "$*" >> "{calls.as_posix()}"; }}\n'
            f'LOG_PATH="{(tmp_path / "job.log").as_posix()}"\n'
            f'execute_script_with_logging "{script.as_posix()}" 001 recon\n'
            'echo "rc=$?"'
        )
        log_end = [c for c in calls.read_text().splitlines() if " log_end " in c]
        assert len(log_end) == 1, log_end
        return result, log_end[0]

    def test_script_exit_code_is_returned(self, tmp_path):
        result, _ = self._run(tmp_path, 7)
        assert "rc=7" in result.stdout

    def test_success_is_logged_as_success(self, tmp_path):
        _, log_end = self._run(tmp_path, 0)
        assert " log_end 001 recon SUCCESS --exit-code 0 " in log_end

    def test_failure_is_logged_as_failed(self, tmp_path):
        _, log_end = self._run(tmp_path, 7)
        assert (" log_end 001 recon FAILED --error-msg Script failed with exit code 7"
                " --exit-code 7 ") in log_end


class TestSchedulerIds:

    def _run(self, tmp_path, **env):
        result = run_bash(
            'execute_wrapper /nonexistent/script.sh >/dev/null\n'
            'echo "subject=$SUBJECT_ID log=$LOG_PATH"',
            env={"SUBJECTS": "001 002 003", "LOG_DIR": (tmp_path / "log").as_posix(),
                 "TASK_NAME": "recon", **env},
        )
        return result.stdout

    def test_pbs_pro_array_index_selects_the_subject(self, tmp_path):
        assert "subject=003" in self._run(tmp_path, PBS_ARRAY_INDEX="3", PBS_JOBID="1234[3].pbs")

    def test_torque_array_id_selects_the_subject(self, tmp_path):
        assert "subject=002" in self._run(tmp_path, PBS_ARRAYID="2", PBS_JOBID="1234-2.pbs")

    def test_slurm_index_takes_precedence(self, tmp_path):
        out = self._run(tmp_path, SLURM_ARRAY_TASK_ID="1", SLURM_JOB_ID="77", PBS_ARRAY_INDEX="3")
        assert "subject=001" in out

    def test_pbs_array_task_logs_into_its_subject_dir(self, tmp_path):
        out = self._run(tmp_path, PBS_ARRAY_INDEX="3", PBS_JOBID="1234[3].pbs")
        assert f"log={(tmp_path / 'log').as_posix()}/recon/sub-003/recon_1234[3].pbs_3_" in out

    def test_pbs_index_beyond_subject_count_is_rejected(self, tmp_path):
        result = run_bash('execute_wrapper /nonexistent/script.sh',
                          env={"SUBJECTS": "001 002", "PBS_ARRAY_INDEX": "9"})
        assert "has no matching subject" in result.stdout


class TestJobDbArguments:

    def _calls(self, tmp_path, **env):
        script = tmp_path / "task.sh"
        script.write_text("exit 0\n")
        calls = tmp_path / "calls.txt"
        # one line per call: --stdout carries the multi-line log tail
        stub = 'python3() { printf "%s\\n" "${*//$\'\\n\'/ }" >> "' + calls.as_posix() + '"; }\n'
        run_bash(
            stub
            + f'LOG_PATH="{(tmp_path / "job.log").as_posix()}"\n'
            + f'execute_script_with_logging "{script.as_posix()}" 001 recon',
            env=env,
        )
        lines = calls.read_text().splitlines()
        assert len(lines) == 3, lines   # log_start, log_command_output, log_end
        return lines

    def test_empty_execution_id_is_left_out(self, tmp_path):
        # job_db.py rejects --execution-id "" and then logs nothing for the job
        assert all("--execution-id" not in c for c in self._calls(tmp_path, EXECUTION_ID=""))

    def test_execution_id_is_passed_when_set(self, tmp_path):
        start, output, _end = self._calls(tmp_path, EXECUTION_ID="17")
        assert "--execution-id 17 " in start
        assert "--execution-id 17 " in output

    def test_pbs_job_id_is_recorded(self, tmp_path):
        calls = self._calls(tmp_path, PBS_JOBID="1234[3].pbs", PBS_ARRAY_INDEX="3")
        assert all("--job-id 1234[3].pbs " in c for c in calls)


class TestEnvFile:

    def test_env_file_is_removed_after_sourcing(self, tmp_path):
        result = run_bash(
            'execute_wrapper /nonexistent/script.sh >/dev/null\n'
            '[ -e "$ENV_FILE" ] && echo "env_file=kept" || echo "env_file=removed"',
            env={"SUBJECTS": "001", "LOG_DIR": (tmp_path / "log").as_posix(), "TASK_NAME": "recon"},
        )
        assert "env_file=removed" in result.stdout

    def test_python_isolation_is_reapplied_after_module_loads(self):
        # a module load that sets PYTHONPATH must not leak into the task's Python
        result = run_bash(
            "ENV_COMMANDS='export PYTHONPATH=/opt/module/lib'\n"
            "TASK_NAME=t SLURM_JOB_ID=1 subject=001\n"
            "create_env_file\n"
            'source "$ENV_FILE"; rm -f "$ENV_FILE"\n'
            'echo "pythonpath=${PYTHONPATH-unset} nousersite=$PYTHONNOUSERSITE"'
        )
        assert "pythonpath=unset nousersite=1" in result.stdout
