"""
Smoke tests for PBSBackend.
Verifies basic build_job_args behaviour without running qsub.
"""

import pytest
from unittest.mock import patch

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

    def test_build_job_args_returns_list(self):
        backend = make_backend()
        resources = make_resources()
        args = backend.build_job_args(
            resources=resources,
            array_param=None,
            wait_jobs=None,
            job_name="test_job",
            log_output="/log/out.log",
            log_error="/log/err.log",
        )
        assert isinstance(args, list)
        assert len(args) > 0

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

    def test_empty_flags_skipped(self):
        """ntasks and mem_per_cpu have empty templates — should not appear in args."""
        backend = make_backend()
        args = backend.build_job_args(
            resources=make_resources(),
            array_param=None, wait_jobs=None,
            job_name="j", log_output="/o", log_error="/e",
        )
        assert "" not in args
        assert None not in args
