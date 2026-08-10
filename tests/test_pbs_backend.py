"""
Tests for PBSBackend: build_job_args, submit_job and wait_for_jobs.
qsub and qstat are always mocked.
"""

import subprocess
from unittest.mock import patch, MagicMock

PBS_CONFIG = {
    "submit_cmd": "qsub",
    "job_id_parse": "first_word",
    "dependency_flag": "-W depend=afterany:{jobs}",
    "array_flag": "-J {array}",
    "resource_flags": {
        "partition":     "-q {value}",
        "nodes":         "-l nodes={value}",
        "ntasks":        "",
        "cpus_per_task": "-l ncpus={value}",
        "time":          "-l walltime={value}",
        "mem":           "-l mem={value}",
        "mem_per_cpu":   "",
        "job_name":      "-N {value}",
        "output":        "-o {value}",
        "error":         "-e {value}",
    },
    "status_cmd": "qstat",
    "active_states": ["Q", "R", "H"],
    "cancel_cmd": "qdel",
}

MOCK_RESOURCES_KWARGS = dict(
    partition="batch",
    nodes=1,
    ntasks=1,
    cpus_per_task=16,
    memory="32gb",
    time="20:00:00",
    memory_per_cpu=None,
    additional_args=[],
)


def make_backend():
    from neuro_pipeline.pipeline.utils.hpc_utils import PBSBackend
    return PBSBackend(PBS_CONFIG)


def make_resources(**overrides):
    from neuro_pipeline.pipeline.utils.hpc_utils import HPCResources
    kwargs = {**MOCK_RESOURCES_KWARGS, **overrides}
    return HPCResources(**kwargs)


class TestPBSBackendSmoke:

    def test_build_job_args_exact_output(self):
        backend = make_backend()
        args = backend.build_job_args(
            resources=make_resources(),
            array_param=None,
            wait_jobs=None,
            job_name="test_job",
            log_output="/log/out.log",
            log_error="/log/err.log",
        )
        # ntasks and mem_per_cpu have empty templates and must be dropped entirely
        assert args == [
            "-q batch",
            "-l nodes=1",
            "-l ncpus=16",
            "-l walltime=20:00:00",
            "-N test_job",
            "-o /log/out.log",
            "-e /log/err.log",
            "-l mem=32gb",
        ]

    def test_queue_flag_present(self):
        backend = make_backend()
        args = backend.build_job_args(
            resources=make_resources(partition="bigmem"),
            array_param=None, wait_jobs=None,
            job_name="j", log_output="/o", log_error="/e",
        )
        assert any("-q" in a for a in args)
        assert any("bigmem" in a for a in args)

    def test_no_slurm_flags_present(self):
        backend = make_backend()
        args = backend.build_job_args(
            resources=make_resources(),
            array_param=None, wait_jobs=None,
            job_name="j", log_output="/o", log_error="/e",
        )
        joined = " ".join(args)
        assert "--partition" not in joined
        assert "--ntasks" not in joined

    def test_walltime_flag_present(self):
        backend = make_backend()
        args = backend.build_job_args(
            resources=make_resources(time="08:00:00"),
            array_param=None, wait_jobs=None,
            job_name="j", log_output="/o", log_error="/e",
        )
        assert any("walltime=08:00:00" in a for a in args)

    def test_array_flag_added_when_provided(self):
        backend = make_backend()
        args = backend.build_job_args(
            resources=make_resources(),
            array_param="1-5%15",
            wait_jobs=None,
            job_name="j", log_output="/o", log_error="/e",
        )
        # array_param is already a full range, so the template must not re-prefix it
        assert "-J 1-5%15" in args

    def test_dependency_flag_added_when_wait_jobs_given(self):
        backend = make_backend()
        args = backend.build_job_args(
            resources=make_resources(),
            array_param=None,
            wait_jobs=["111", "222"],
            job_name="j", log_output="/o", log_error="/e",
        )
        assert any("afterany" in a and "111" in a and "222" in a for a in args)

    def test_mem_per_cpu_wins_over_mem_when_set(self):
        # mem_per_cpu has an empty template here, so neither flag may be emitted
        backend = make_backend()
        args = backend.build_job_args(
            resources=make_resources(memory_per_cpu="4gb"),
            array_param=None, wait_jobs=None,
            job_name="j", log_output="/o", log_error="/e",
        )
        assert not any(a.startswith("-l mem") for a in args)

    def test_additional_args_appended(self):
        backend = make_backend()
        args = backend.build_job_args(
            resources=make_resources(additional_args=["-l place=scatter"]),
            array_param=None, wait_jobs=None,
            job_name="j", log_output="/o", log_error="/e",
        )
        assert "-l place=scatter" in args


class TestPBSSubmitJob:

    def _script(self, tmp_path):
        p = tmp_path / "wrapper.sh"
        p.write_text("#!/bin/bash\n")
        return p

    def test_successful_submission_parses_first_word(self, tmp_path):
        backend = make_backend()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="4242.pbsserver\n")
            job_id = backend.submit_job(["-q batch"], self._script(tmp_path))
        assert job_id == "4242.pbsserver"

    def test_command_is_qsub_plus_args_plus_script(self, tmp_path):
        backend = make_backend()
        script = self._script(tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="1.pbs\n")
            backend.submit_job(["-q batch"], script)
        assert mock_run.call_args.args[0] == ["qsub", "-q batch", str(script)]

    def test_failed_submission_returns_none(self, tmp_path):
        backend = make_backend()
        err = subprocess.CalledProcessError(1, "qsub", stderr="queue closed")
        with patch("subprocess.run", side_effect=err):
            job_id = backend.submit_job(["-q batch"], self._script(tmp_path))
        assert job_id is None

    def test_exit_zero_with_no_parsable_id_returns_none(self, tmp_path):
        backend = make_backend()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="\n")
            job_id = backend.submit_job(["-q batch"], self._script(tmp_path))
        assert job_id is None


class TestPBSWaitForJobs:
    # qstat output: job_id name user time state queue
    RUNNING = "4242.pbs  job  me  00:01  R  batch\n"
    DONE    = "4242.pbs  job  me  00:01  F  batch\n"

    def test_empty_job_list_skips_subprocess(self):
        backend = make_backend()
        with patch("subprocess.run") as mock_run:
            backend.wait_for_jobs([])
        mock_run.assert_not_called()

    def test_inactive_state_ends_the_wait(self):
        backend = make_backend()
        with patch("subprocess.run") as mock_run, patch("time.sleep") as mock_sleep:
            mock_run.return_value = MagicMock(stdout=self.DONE)
            backend.wait_for_jobs(["4242.pbs"], polling_interval=1)
        assert mock_run.call_count == 1
        mock_sleep.assert_not_called()

    def test_running_then_done(self):
        backend = make_backend()
        responses = [MagicMock(stdout=self.RUNNING), MagicMock(stdout=self.DONE)]
        with patch("subprocess.run", side_effect=responses) as mock_run, \
             patch("time.sleep") as mock_sleep:
            backend.wait_for_jobs(["4242.pbs"], polling_interval=5)
        assert mock_run.call_count == 2
        mock_sleep.assert_called_once_with(5)

    def test_job_gone_from_queue_ends_the_wait(self):
        backend = make_backend()
        err = subprocess.CalledProcessError(1, "qstat")
        with patch("subprocess.run", side_effect=err) as mock_run, \
             patch("time.sleep") as mock_sleep:
            backend.wait_for_jobs(["4242.pbs"], polling_interval=1)
        assert mock_run.call_count == 1
        mock_sleep.assert_not_called()

    def test_each_job_is_polled_separately(self):
        backend = make_backend()
        with patch("subprocess.run") as mock_run, patch("time.sleep"):
            mock_run.return_value = MagicMock(stdout=self.DONE)
            backend.wait_for_jobs(["4242.pbs", "4243.pbs"], polling_interval=1)
        assert mock_run.call_count == 2
        assert mock_run.call_args_list[0].args[0] == ["qstat", "4242.pbs"]
        assert mock_run.call_args_list[1].args[0] == ["qstat", "4243.pbs"]
