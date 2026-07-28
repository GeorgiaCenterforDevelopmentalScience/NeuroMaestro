"""
test_input_dir_resolution.py

Tests for the actual_input_dir resolution logic in submit_slurm_job.
The logic redirects INPUT_DIR to the upstream task's output_pattern when that
upstream task is also part of the current run.
"""

import pytest
from unittest.mock import patch, MagicMock
from tests.conftest import MOCK_CONFIG, MOCK_HPC_CONFIG, MOCK_PROJECT_CONFIG

# hpc_utils reads the pipeline config through config_utils, so that is
# the single place to patch.
PIPELINE_CONFIG_PATH = "neuro_pipeline.pipeline.utils.config_utils.config"
HPC_CONFIG_PATH      = "neuro_pipeline.pipeline.utils.hpc_utils.hpc_config"
CONFIG_UTILS_PATH    = "neuro_pipeline.pipeline.utils.config_utils.config"


def _run_submit(tmp_path, scripts_dir, task_config, requested_tasks,
                input_dir=None, output_dir=None):
    # Use tmp_path-based defaults so mkdir never touches a system path
    if input_dir is None:
        input_dir = str(tmp_path / "raw")
    if output_dir is None:
        output_dir = str(tmp_path / "output")

    fake_scripts_pkg = MagicMock()
    fake_scripts_pkg.SCRIPTS_DIR = scripts_dir

    project_config = {**MOCK_PROJECT_CONFIG, "scripts_dir": str(scripts_dir)}
    with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), \
         patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG), \
         patch(CONFIG_UTILS_PATH, MOCK_CONFIG), \
         patch.dict("sys.modules", {"neuro_pipeline.scripts": fake_scripts_pkg}):
        from neuro_pipeline.pipeline.utils.hpc_utils import submit_slurm_job
        submit_slurm_job(
            script_name=task_config["scripts"][0],
            subjects="001,002",
            input_dir=input_dir,
            output_dir=output_dir,
            work_dir=str(tmp_path / "work"),
            container_dir="/containers",
            task_config=task_config,
            project_config=project_config,
            requested_tasks=requested_tasks,
            dry_run=True,
            db_path=str(tmp_path / "work" / "pipeline_jobs.db"),
        )

    wrapper_dir = tmp_path / "work" / "log" / "wrapper"
    wrappers = list(wrapper_dir.glob("*.sh"))
    assert wrappers, "Wrapper script should have been created"
    # Return both content and the resolved output_dir for use in assertions
    return wrappers[0].read_text(), output_dir


class TestActualInputDirResolution:

    recon_TASK = {
        "name": "recon",
        "profile": "light_short",
        "array": True,
        "scripts": ["dcm2bids_convert_BIDS.sh"],
        "input_from": "unzip",
        "output_pattern": "{base_output}/BIDS",
    }

    REST_TASK = {
        "name": "rest_preprocess",
        "stage": "prep",
        "profile": "heavy_long",
        "array": True,
        "scripts": ["fmriprep_rs.sh"],
        "input_from": "recon",
        "output_pattern": "{base_output}/BIDS_derivatives/fmriprep",
    }

    def test_input_redirected_when_upstream_in_requested_tasks(self, tmp_path, scripts_dir):
        """unzip in requested_tasks → INPUT_DIR becomes unzip's output (output_dir/raw)"""
        output_dir = str(tmp_path / "output")
        content, _ = _run_submit(
            tmp_path, scripts_dir,
            task_config=self.recon_TASK,
            requested_tasks=["unzip", "recon"],
            output_dir=output_dir,
        )
        assert f"export INPUT_DIR='{output_dir}/raw'" in content

    def test_input_not_redirected_when_upstream_absent(self, tmp_path, scripts_dir):
        """recon alone (no unzip) → INPUT_DIR stays as provided"""
        input_dir = str(tmp_path / "raw")
        output_dir = str(tmp_path / "output")
        content, _ = _run_submit(
            tmp_path, scripts_dir,
            task_config=self.recon_TASK,
            requested_tasks=["recon"],
            input_dir=input_dir,
            output_dir=output_dir,
        )
        assert f"export INPUT_DIR='{input_dir}'" in content

    def test_nested_upstream_resolution(self, tmp_path, scripts_dir):
        """rest_preprocess with recon in run → INPUT_DIR = output_dir/BIDS"""
        output_dir = str(tmp_path / "output")
        content, _ = _run_submit(
            tmp_path, scripts_dir,
            task_config=self.REST_TASK,
            requested_tasks=["recon", "rest_preprocess"],
            output_dir=output_dir,
        )
        assert f"export INPUT_DIR='{output_dir}/BIDS'" in content

    def test_input_kept_when_running_single_step(self, tmp_path, scripts_dir):
        """rest_preprocess alone (recon already done) → INPUT_DIR kept as-is"""
        input_dir = str(tmp_path / "bids")
        output_dir = str(tmp_path / "output")
        content, _ = _run_submit(
            tmp_path, scripts_dir,
            task_config=self.REST_TASK,
            requested_tasks=["rest_preprocess"],
            input_dir=input_dir,
            output_dir=output_dir,
        )
        assert f"export INPUT_DIR='{input_dir}'" in content