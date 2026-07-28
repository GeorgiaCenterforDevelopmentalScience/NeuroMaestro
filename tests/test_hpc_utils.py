"""
test_hpc_utils.py

Tests for pipeline/utils/hpc_utils.py

Covers:
1. get_hpc_resources        — profile merging, array param substitution, bad profile
2. get_environment_commands — environ as list / str / empty
3. get_script_with_validation — script found / not found
4. create_wrapper_script    — generated content correctness (the most important section)
5. submit_slurm_job (dry_run) — no real sbatch call needed
"""

import os
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from tests.conftest import MOCK_CONFIG, MOCK_HPC_CONFIG, MOCK_PROJECT_CONFIG


# config  = pipeline task/array config  (config.yaml)
# hpc_config = scheduler + resource profiles (hpc_config.yaml)
# hpc_utils reads the pipeline config through config_utils, so that is
# the single place to patch.
PIPELINE_CONFIG_PATH = "neuro_pipeline.pipeline.utils.config_utils.config"
HPC_CONFIG_PATH      = "neuro_pipeline.pipeline.utils.hpc_utils.hpc_config"
CONFIG_UTILS_PATH    = "neuro_pipeline.pipeline.utils.config_utils.config"

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def import_hpc():
    """Import hpc_utils with mock configs injected."""
    with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
        import importlib
        import neuro_pipeline.pipeline.utils.hpc_utils as mod
        importlib.reload(mod)
        return mod


# ===========================================================================
# 1. get_hpc_resources
# ===========================================================================

class TestGetHPCResources:

    def _get(self, task_config):
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            from neuro_pipeline.pipeline.utils.hpc_utils import get_hpc_resources
            return get_hpc_resources(task_config)

    def test_standard_profile_values(self):
        resources = self._get({"profile": "standard"})
        assert resources.memory == "32gb"
        assert resources.time == "20:00:00"
        assert resources.partition == "batch"   # from defaults
        assert resources.cpus_per_task == 16

    def test_heavy_long_profile(self):
        resources = self._get({"profile": "heavy_long"})
        assert resources.memory == "64gb"
        assert resources.time == "24:00:00"

    def test_data_manage_profile(self):
        resources = self._get({"profile": "data_manage"})
        assert resources.memory == "2gb"
        assert resources.time == "00:20:00"

    def test_array_param_substituted_correctly(self):
        """array: true + 5 subjects  →  pattern becomes '1-5%15'"""
        resources = self._get({"profile": "standard", "array": True})
        assert resources.array is not None
        # The raw pattern is stored; num substitution happens in submit_slurm_job
        assert "{num}" in resources.array

    def test_non_array_task_has_no_array_param(self):
        resources = self._get({"profile": "standard", "array": False})
        assert resources.array is None

    def test_unknown_profile_raises_value_error(self):
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            from neuro_pipeline.pipeline.utils.hpc_utils import get_hpc_resources
            with pytest.raises(ValueError, match="Profile 'ghost_profile' not found"):
                get_hpc_resources({"profile": "ghost_profile"})

    def test_defaults_are_applied_when_profile_does_not_specify(self):
        """Profile only specifies memory+time; nodes/cpus come from defaults."""
        resources = self._get({"profile": "standard_short"})
        assert resources.nodes == 1
        assert resources.ntasks == 1


# ===========================================================================
# 2. get_environment_commands
# ===========================================================================

class TestGetEnvironmentCommands:

    def _get_env(self, task_config, project_config=None):
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            from neuro_pipeline.pipeline.utils.hpc_utils import get_environment_commands
            return get_environment_commands(task_config, project_config)

    def test_environ_as_list_returns_correct_commands(self):
        task_config = {"environ": ["afni_24.3.06"]}
        cmds = self._get_env(task_config, MOCK_PROJECT_CONFIG)
        assert "ml AFNI/24.3.06-foss-2023a" in cmds

    def test_multiple_environ_concatenated(self):
        task_config = {"environ": ["data_manage_1", "afni_24.3.06"]}
        cmds = self._get_env(task_config, MOCK_PROJECT_CONFIG)
        assert "ml p7zip/17.05-GCCcore-13.3.0" in cmds
        assert "ml AFNI/24.3.06-foss-2023a" in cmds

    def test_environ_as_string_works(self):
        task_config = {"environ": "afni_24.3.06"}
        cmds = self._get_env(task_config, MOCK_PROJECT_CONFIG)
        assert any("AFNI" in c for c in cmds)

    def test_empty_environ_returns_empty_list(self):
        task_config = {"environ": []}
        cmds = self._get_env(task_config, MOCK_PROJECT_CONFIG)
        assert cmds == []

    def test_no_environ_key_returns_empty_list(self):
        task_config = {}
        cmds = self._get_env(task_config, MOCK_PROJECT_CONFIG)
        assert cmds == []

    def test_no_project_config_returns_empty_list(self):
        task_config = {"environ": ["afni_24.3.06"]}
        cmds = self._get_env(task_config, project_config=None)
        assert cmds == []

    def test_unknown_environ_name_returns_empty(self):
        task_config = {"environ": ["does_not_exist"]}
        cmds = self._get_env(task_config, MOCK_PROJECT_CONFIG)
        assert cmds == []


# ===========================================================================
# 3. get_script_with_validation  (script path resolution)
# ===========================================================================

class TestGetScriptWithValidation:
    # get_script_with_validation joins scripts_dir/script_name and checks existence;
    # it does not use __file__, so pass the real scripts_dir fixture directly.

    def test_returns_path_when_script_exists(self, scripts_dir):
        from neuro_pipeline.pipeline.utils.hpc_utils import get_script_with_validation
        result = get_script_with_validation("afni_cards_preprocessing.sh", str(scripts_dir))
        assert result is not None
        assert result.name == "afni_cards_preprocessing.sh"
        assert result.exists()

    def test_returns_none_when_script_missing(self, scripts_dir):
        from neuro_pipeline.pipeline.utils.hpc_utils import get_script_with_validation
        result = get_script_with_validation("nonexistent_script.sh", str(scripts_dir))
        assert result is None

    def test_returns_none_when_scripts_dir_missing(self, tmp_path):
        from neuro_pipeline.pipeline.utils.hpc_utils import get_script_with_validation
        result = get_script_with_validation("any.sh", str(tmp_path / "does_not_exist"))
        assert result is None


# ===========================================================================
# 4. create_wrapper_script  — content correctness
#    This is the most important section per requirements.
# ===========================================================================

class TestCreateWrapperScript:
    """
    We call create_wrapper_script with a real tmp_path so we can
    read back the generated .sh file and assert on its content.
    """

    TASK_CONFIG = {
        "name": "cards_preprocess",
        "profile": "standard",
        "array": True,
        "remove_TRs": 2,
        "template": "HaskinsPeds_NL_template1.0_SSW.nii",
        "blur_size": 4.0,
        "environ": ["afni_24.3.06"],
        "censor_motion": "0.3",
        "censor_outliers": "0.05",
        "scripts": ["afni_cards_preprocessing.sh"],
        "output_pattern": "{base_output}/AFNI_derivatives",
    }

    SLURM_ARGS = [
        "--partition=batch",
        "--nodes=1",
        "--ntasks=1",
        "--cpus-per-task=16",
        "--time=20:00:00",
        "--mem=32gb",
        "--array=1-3%15",
    ]

    def _create(self, tmp_path, scripts_dir, subjects=None, extra_task_config=None):
        subjects = subjects or ["001", "002", "003"]
        task_cfg = {**self.TASK_CONFIG, **(extra_task_config or {})}
        fake_script = scripts_dir / "afni_cards_preprocessing.sh"

        # Fake SCRIPTS_DIR import inside hpc_utils
        fake_scripts_pkg = MagicMock()
        fake_scripts_pkg.SCRIPTS_DIR = scripts_dir

        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG), \
             patch.dict("sys.modules", {"neuro_pipeline.scripts": fake_scripts_pkg}):
            from neuro_pipeline.pipeline.utils.hpc_utils import create_wrapper_script

            wrapper_path, _ = create_wrapper_script(
                script_path=fake_script,
                subjects_list=subjects,
                input_dir="/data/input",
                output_dir=str(tmp_path / "output"),
                work_dir=str(tmp_path / "work"),
                use_array=True,
                env_commands=["ml AFNI/24.3.06-foss-2023a"],
                project_config=MOCK_PROJECT_CONFIG,
                task_config=task_cfg,
                db_path=str(tmp_path / "work" / "pipeline_jobs.db"),
                option_env={"session": "01", "prefix": "sub-", "project": "TEST"},
                slurm_args=self.SLURM_ARGS,
            )
        return wrapper_path

    # ---- basic structure ---------------------------------------------------

    def test_wrapper_file_is_created(self, tmp_path, scripts_dir):
        wrapper = self._create(tmp_path, scripts_dir)
        assert wrapper.exists()
        assert wrapper.suffix == ".sh"

    def test_wrapper_is_executable(self, tmp_path, scripts_dir):
        wrapper = self._create(tmp_path, scripts_dir)
        assert os.access(wrapper, os.X_OK)

    def test_wrapper_has_shebang(self, tmp_path, scripts_dir):
        wrapper = self._create(tmp_path, scripts_dir)
        content = wrapper.read_text()
        assert content.startswith("#!/bin/bash")

    # ---- subjects exported correctly ---------------------------------------

    def test_subjects_exported(self, tmp_path, scripts_dir):
        wrapper = self._create(tmp_path, scripts_dir, subjects=["001", "002", "003"])
        content = wrapper.read_text()
        assert "export SUBJECTS='001 002 003'" in content

    def test_single_subject_exported(self, tmp_path, scripts_dir):
        wrapper = self._create(tmp_path, scripts_dir, subjects=["001"])
        content = wrapper.read_text()
        assert "export SUBJECTS='001'" in content

    # ---- core path variables -----------------------------------------------

    def test_input_dir_exported(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert "export INPUT_DIR=" in content

    def test_output_dir_exported(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert "export OUTPUT_DIR=" in content

    def test_work_dir_exported(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert "export WORK_DIR=" in content

    def test_task_name_exported(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert "export TASK_NAME='cards_preprocess'" in content

    def test_db_path_exported(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert "export DB_PATH=" in content

    # ---- environment module commands ---------------------------------------

    def test_env_commands_present(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert "ml AFNI/24.3.06-foss-2023a" in content

    def test_global_python_commands_present(self, tmp_path, scripts_dir):
        """global_python from project config must appear in wrapper."""
        content = self._create(tmp_path, scripts_dir).read_text()
        assert "ml Python/3.11.3-GCCcore-12.3.0" in content

    # ---- task-specific parameters ------------------------------------------

    def test_remove_trs_exported(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert "REMOVE_TRS='2'" in content

    def test_blur_size_exported(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert "BLUR_SIZE='4.0'" in content

    def test_censor_motion_exported(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert "CENSOR_MOTION='0.3'" in content

    def test_censor_outliers_exported(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert "CENSOR_OUTLIERS='0.05'" in content

    def test_template_exported(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert "HaskinsPeds_NL_template1.0_SSW.nii" in content

    # ---- excluded task config keys do NOT appear as exports ----------------

    def test_profile_key_not_exported(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert "export PROFILE=" not in content

    def test_scripts_key_not_exported(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert "export SCRIPTS=" not in content

    # ---- SLURM submission command comment ----------------------------------

    def test_slurm_submission_comment_present(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert "Submission Command" in content
        assert "--partition=batch" in content

    # ---- wrapper template sourced and executed -----------------------------

    def test_sources_wrapper_functions(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert "source" in content
        assert "wrapper_functions.sh" in content

    def test_execute_wrapper_called(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert "execute_wrapper" in content

    # ---- subject count in filename -----------------------------------------

    def test_wrapper_filename_contains_script_stem(self, tmp_path, scripts_dir):
        wrapper = self._create(tmp_path, scripts_dir)
        assert "afni_cards_preprocessing" in wrapper.name


# ===========================================================================
# 5. submit_slurm_job — dry_run branch (no real sbatch)
# ===========================================================================

class TestSubmitSlurmJobDryRun:

    BASE_KWARGS = dict(
        subjects="001,002,003",
        input_dir="/data/input",
        output_dir="/data/output",
        container_dir="/work/containers",
        wait_jobs=None,
        dry_run=True,
        option_env={"session": "01", "prefix": "sub-"},
        requested_tasks=["cards_preprocess"],
        original_work_dir="/work",
    )

    def test_dry_run_returns_string_job_id(self, tmp_path, scripts_dir):
        fake_scripts_pkg = MagicMock()
        fake_scripts_pkg.SCRIPTS_DIR = scripts_dir

        task_config = {
            "name": "cards_preprocess",
            "profile": "standard",
            "array": True,
            "scripts": ["afni_cards_preprocessing.sh"],
            "output_pattern": "{base_output}/AFNI_derivatives",
        }

        kwargs = {
            **self.BASE_KWARGS,
            "input_dir": str(tmp_path / "input"),
            "output_dir": str(tmp_path / "output"),
        }

        project_config = {**MOCK_PROJECT_CONFIG, "scripts_dir": str(scripts_dir)}
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG), \
             patch.dict("sys.modules", {"neuro_pipeline.scripts": fake_scripts_pkg}):
            from neuro_pipeline.pipeline.utils.hpc_utils import submit_slurm_job

            job_id = submit_slurm_job(
                script_name="afni_cards_preprocessing.sh",
                work_dir=str(tmp_path / "work"),
                task_config=task_config,
                project_config=project_config,
                db_path=str(tmp_path / "work" / "pipeline_jobs.db"),
                **kwargs,
            )

        assert job_id is not None
        assert "dry_run" in job_id

    def test_dry_run_does_not_call_sbatch(self, tmp_path, scripts_dir):
        fake_scripts_pkg = MagicMock()
        fake_scripts_pkg.SCRIPTS_DIR = scripts_dir

        task_config = {
            "name": "cards_preprocess",
            "profile": "standard",
            "array": True,
            "scripts": ["afni_cards_preprocessing.sh"],
            "output_pattern": "{base_output}/AFNI_derivatives",
        }

        kwargs = {
            **self.BASE_KWARGS,
            "input_dir": str(tmp_path / "input"),
            "output_dir": str(tmp_path / "output"),
        }

        project_config = {**MOCK_PROJECT_CONFIG, "scripts_dir": str(scripts_dir)}
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG), \
             patch.dict("sys.modules", {"neuro_pipeline.scripts": fake_scripts_pkg}), \
             patch("subprocess.run") as mock_run:

            from neuro_pipeline.pipeline.utils.hpc_utils import submit_slurm_job

            submit_slurm_job(
                script_name="afni_cards_preprocessing.sh",
                work_dir=str(tmp_path / "work"),
                task_config=task_config,
                project_config=project_config,
                db_path=str(tmp_path / "work" / "pipeline_jobs.db"),
                **kwargs,
            )

        mock_run.assert_not_called()

    def test_missing_script_raises(self, tmp_path, scripts_dir):
        fake_scripts_pkg = MagicMock()
        fake_scripts_pkg.SCRIPTS_DIR = scripts_dir

        task_config = {
            "name": "ghost_task",
            "profile": "standard",
            "array": False,
            "scripts": ["ghost_script.sh"],
        }

        project_config = {**MOCK_PROJECT_CONFIG, "scripts_dir": str(scripts_dir)}
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG), \
             patch.dict("sys.modules", {"neuro_pipeline.scripts": fake_scripts_pkg}):
            from neuro_pipeline.pipeline.utils.hpc_utils import submit_slurm_job

            with pytest.raises(FileNotFoundError, match="ghost_script.sh"):
                submit_slurm_job(
                    script_name="ghost_script.sh",
                    work_dir=str(tmp_path / "work"),
                    task_config=task_config,
                    project_config=project_config,
                    db_path=str(tmp_path / "work" / "pipeline_jobs.db"),
                    **self.BASE_KWARGS,
                )

    def test_wait_jobs_produces_dependency_in_slurm_args(self, tmp_path, scripts_dir):
        """When wait_jobs is set, --dependency=afterany:... should appear in the wrapper."""
        fake_scripts_pkg = MagicMock()
        fake_scripts_pkg.SCRIPTS_DIR = scripts_dir

        task_config = {
            "name": "cards_preprocess",
            "profile": "standard",
            "array": True,
            "scripts": ["afni_cards_preprocessing.sh"],
            "output_pattern": "{base_output}/AFNI_derivatives",
        }

        kwargs = {
            **self.BASE_KWARGS,
            "input_dir": str(tmp_path / "input"),
            "output_dir": str(tmp_path / "output"),
            "wait_jobs": ["12345", "67890"],
            "dry_run": True,
        }

        project_config = {**MOCK_PROJECT_CONFIG, "scripts_dir": str(scripts_dir)}
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG), \
             patch.dict("sys.modules", {"neuro_pipeline.scripts": fake_scripts_pkg}):
            from neuro_pipeline.pipeline.utils.hpc_utils import submit_slurm_job

            submit_slurm_job(
                script_name="afni_cards_preprocessing.sh",
                work_dir=str(tmp_path / "work"),
                task_config=task_config,
                project_config=project_config,
                db_path=str(tmp_path / "work" / "pipeline_jobs.db"),
                **kwargs,
            )

        # Read generated wrapper and verify --dependency appears
        wrapper_dir = tmp_path / "work" / "log" / "wrapper"
        wrappers = list(wrapper_dir.glob("*.sh"))
        assert wrappers, "Wrapper script should have been created"
        content = wrappers[0].read_text()
        assert "--dependency=afterany:12345:67890" in content


# ===========================================================================
# 6. SLURMBackend.submit_job — mock subprocess
# ===========================================================================

class TestSLURMBackendSubmitJob:

    def _backend(self):
        from neuro_pipeline.pipeline.utils.hpc_utils import SLURMBackend
        return SLURMBackend(MOCK_HPC_CONFIG["slurm"])

    def test_successful_submission_returns_job_id(self, tmp_path):
        backend = self._backend()
        fake_script = tmp_path / "wrapper.sh"
        fake_script.write_text("#!/bin/bash\n")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="Submitted batch job 12345\n")
            job_id = backend.submit_job(["--partition=batch"], fake_script)
        assert job_id == "12345"

    def test_failed_submission_returns_none(self, tmp_path):
        import subprocess
        backend = self._backend()
        fake_script = tmp_path / "wrapper.sh"
        fake_script.write_text("#!/bin/bash\n")
        err = subprocess.CalledProcessError(1, "sbatch", stderr="permission denied")
        with patch("subprocess.run", side_effect=err):
            job_id = backend.submit_job(["--partition=batch"], fake_script)
        assert job_id is None

    def test_first_word_parse_strategy(self, tmp_path):
        from neuro_pipeline.pipeline.utils.hpc_utils import SLURMBackend
        cfg = {**MOCK_HPC_CONFIG["slurm"], "job_id_parse": "first_word"}
        backend = SLURMBackend(cfg)
        fake_script = tmp_path / "wrapper.sh"
        fake_script.write_text("#!/bin/bash\n")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="99999 extra words\n")
            job_id = backend.submit_job(["--partition=batch"], fake_script)
        assert job_id == "99999"


# ===========================================================================
# 7. SLURMBackend.wait_for_jobs — mock subprocess
# ===========================================================================

class TestSLURMBackendWaitForJobs:

    def _backend(self):
        from neuro_pipeline.pipeline.utils.hpc_utils import SLURMBackend
        return SLURMBackend(MOCK_HPC_CONFIG["slurm"])

    def test_empty_job_list_skips_subprocess(self):
        backend = self._backend()
        with patch("subprocess.run") as mock_run:
            backend.wait_for_jobs([])
        mock_run.assert_not_called()

    def test_empty_queue_breaks_immediately(self):
        backend = self._backend()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="")
            backend.wait_for_jobs(["12345"], polling_interval=0)
        assert mock_run.call_count == 1

    def test_job_not_in_queue_breaks(self):
        import subprocess
        backend = self._backend()
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "squeue")):
            backend.wait_for_jobs(["12345"], polling_interval=0)

    def test_running_then_done(self):
        import time
        backend = self._backend()
        responses = [
            MagicMock(stdout="12345 RUNNING\n"),
            MagicMock(stdout=""),
        ]
        with patch("subprocess.run", side_effect=responses), patch("time.sleep"):
            backend.wait_for_jobs(["12345"], polling_interval=1)


# ===========================================================================
# 8. get_hpc_backend — unknown scheduler
# ===========================================================================

class TestGetHPCBackendUnknown:

    def test_unknown_scheduler_raises_not_implemented(self):
        cfg = {**MOCK_HPC_CONFIG, "scheduler": "lsf", "lsf": {"submit_cmd": "bsub"}}
        with patch(HPC_CONFIG_PATH, cfg):
            from neuro_pipeline.pipeline.utils.hpc_utils import get_hpc_backend
            with pytest.raises(NotImplementedError, match="lsf"):
                get_hpc_backend()

    def test_missing_scheduler_config_block_raises_value_error(self):
        cfg = {**MOCK_HPC_CONFIG, "scheduler": "lsf"}  # no "lsf" key
        with patch(HPC_CONFIG_PATH, cfg):
            from neuro_pipeline.pipeline.utils.hpc_utils import get_hpc_backend
            with pytest.raises(ValueError, match="lsf"):
                get_hpc_backend()


# ===========================================================================
# 9. submit_slurm_job — extra branches
# ===========================================================================

class TestSubmitSlurmJobExtras:

    BASE_KWARGS = dict(
        input_dir="/data/input",
        output_dir="/data/output",
        container_dir="/work/containers",
        wait_jobs=None,
        dry_run=True,
        option_env={"session": "01", "prefix": "sub-"},
        requested_tasks=["cards_preprocess"],
        original_work_dir="/work",
    )

    def _invoke(self, tmp_path, scripts_dir, task_config, extra_kwargs=None):
        fake_scripts_pkg = MagicMock()
        fake_scripts_pkg.SCRIPTS_DIR = scripts_dir
        kwargs = {**self.BASE_KWARGS, "output_dir": str(tmp_path / "output"), **(extra_kwargs or {})}
        project_config = {**MOCK_PROJECT_CONFIG, "scripts_dir": str(scripts_dir)}
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG), \
             patch.dict("sys.modules", {"neuro_pipeline.scripts": fake_scripts_pkg}):
            from neuro_pipeline.pipeline.utils.hpc_utils import submit_slurm_job
            return submit_slurm_job(
                script_name="afni_cards_preprocessing.sh",
                work_dir=str(tmp_path / "work"),
                task_config=task_config,
                project_config=project_config,
                db_path=str(tmp_path / "work" / "pipeline_jobs.db"),
                **kwargs,
            )

    def test_subjects_read_from_file(self, tmp_path, scripts_dir):
        subjects_file = tmp_path / "subjects.txt"
        subjects_file.write_text("001\n002\n003\n")
        task_config = {"name": "cards_preprocess", "profile": "standard",
                       "array": True, "scripts": ["afni_cards_preprocessing.sh"]}
        job_id = self._invoke(tmp_path, scripts_dir, task_config,
                              {"subjects": str(subjects_file)})
        assert job_id is not None and "dry_run" in job_id

    def test_subjects_file_contents_land_in_wrapper(self, tmp_path, scripts_dir):
        subjects_file = tmp_path / "subjects.txt"
        subjects_file.write_text("001\n002\n003\n")
        task_config = {"name": "cards_preprocess", "profile": "standard",
                       "array": True, "scripts": ["afni_cards_preprocessing.sh"]}
        self._invoke(tmp_path, scripts_dir, task_config,
                     {"subjects": str(subjects_file)})
        wrapper = list((tmp_path / "work" / "log" / "wrapper").glob("*.sh"))[0]
        assert "export SUBJECTS='001 002 003'" in wrapper.read_text()

    def test_long_subject_list_does_not_raise(self, tmp_path, scripts_dir):
        # Guards a latent crash, not an active one. Callers always expand
        # --subjects (including a txt file) into a comma-joined string, so past
        # 64 three-digit IDs it exceeds NAME_MAX as a single path component.
        # Path().is_file() propagates ENAMETOOLONG there on Python < 3.13;
        # os.path.isfile() swallows it. Typical runs stay well under the limit.
        subjects = ",".join(f"{i:03d}" for i in range(1, 400))
        assert len(subjects) > 255
        task_config = {"name": "cards_preprocess", "profile": "standard",
                       "array": True, "scripts": ["afni_cards_preprocessing.sh"]}
        job_id = self._invoke(tmp_path, scripts_dir, task_config,
                              {"subjects": subjects})
        assert job_id is not None and "dry_run" in job_id

    def test_long_subject_list_parsed_as_list_not_path(self, tmp_path, scripts_dir):
        subjects = ",".join(f"{i:03d}" for i in range(1, 400))
        task_config = {"name": "cards_preprocess", "profile": "standard",
                       "array": True, "scripts": ["afni_cards_preprocessing.sh"]}
        self._invoke(tmp_path, scripts_dir, task_config, {"subjects": subjects})
        wrapper = list((tmp_path / "work" / "log" / "wrapper").glob("*.sh"))[0]
        content = wrapper.read_text()
        assert "# Number of subjects: 399" in content
        assert "--array=1-399%15" in content

    def test_output_pattern_applied_in_wrapper(self, tmp_path, scripts_dir):
        task_config = {"name": "cards_preprocess", "profile": "standard", "array": False,
                       "scripts": ["afni_cards_preprocessing.sh"],
                       "output_pattern": "{base_output}/AFNI_derivatives"}
        self._invoke(tmp_path, scripts_dir, task_config,
                     {"subjects": "001", "output_dir": str(tmp_path / "output")})
        wrapper_dir = tmp_path / "work" / "log" / "wrapper"
        content = list(wrapper_dir.glob("*.sh"))[0].read_text()
        assert "AFNI_derivatives" in content

    def test_non_dry_run_calls_backend_submit(self, tmp_path, scripts_dir):
        fake_scripts_pkg = MagicMock()
        fake_scripts_pkg.SCRIPTS_DIR = scripts_dir
        task_config = {"name": "cards_preprocess", "profile": "standard", "array": False,
                       "scripts": ["afni_cards_preprocessing.sh"]}
        project_config = {**MOCK_PROJECT_CONFIG, "scripts_dir": str(scripts_dir)}
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG), \
             patch.dict("sys.modules", {"neuro_pipeline.scripts": fake_scripts_pkg}), \
             patch("neuro_pipeline.pipeline.utils.hpc_utils.SLURMBackend.submit_job",
                   return_value="99999") as mock_submit:
            from neuro_pipeline.pipeline.utils.hpc_utils import submit_slurm_job
            job_id = submit_slurm_job(
                script_name="afni_cards_preprocessing.sh",
                subjects="001",
                work_dir=str(tmp_path / "work"),
                task_config=task_config,
                project_config=project_config,
                db_path=str(tmp_path / "work" / "pipeline_jobs.db"),
                dry_run=False,
                input_dir="/data/input",
                output_dir=str(tmp_path / "output"),
                container_dir="/containers",
                wait_jobs=None,
                option_env={"session": "01"},
                requested_tasks=None,
                original_work_dir=None,
            )
        assert job_id == "99999"
        mock_submit.assert_called_once()

# ===========================================================================
# 10. Shell quoting and reserved variable names
# ===========================================================================

BACKSLASH = chr(92)


class TestShellQuoting:
    """Config values used to be interpolated straight into double quotes, so a
    value containing $, a backtick or a quote was expanded or broke the script.
    """

    @staticmethod
    def _export(name, value):
        from neuro_pipeline.pipeline.utils.hpc_utils import _export_line
        return _export_line(name, value)

    def test_plain_value_is_single_quoted(self):
        assert self._export("TEMPLATE", "MNI152") == "export TEMPLATE='MNI152'"

    def test_dollar_sign_is_not_expandable(self):
        line = self._export("LICENSE", "$HOME/license.txt")
        assert line == "export LICENSE='$HOME/license.txt'"

    def test_backtick_is_not_command_substitution(self):
        line = self._export("NOTE", "run `date` first")
        assert line == "export NOTE='run `date` first'"

    def test_double_quote_does_not_break_out(self):
        line = self._export("TEMPLATE", 'MNI"152')
        assert line == "export TEMPLATE='MNI\"152'"

    def test_single_quote_is_escaped(self):
        line = self._export("NOTE", "it's here")
        # closes the quote, emits an escaped quote, reopens: 'it'\''s here'
        assert line.startswith("export NOTE='") and line.endswith("'")
        assert BACKSLASH + "''" in line
        assert '"' not in line

    def test_values_survive_a_real_bash_round_trip(self):
        import subprocess
        script = "\n".join([
            self._export("A", "$HOME/x"),
            self._export("B", "run `date`"),
            self._export("C", "it's"),
            'printf "%s|%s|%s" "$A" "$B" "$C"',
        ])
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout
        assert out == "$HOME/x|run `date`|it's"


class TestReservedEnvNames:
    """key.upper() means a config key named "path" would overwrite $PATH and
    leave the job unable to find any command.
    """

    def _build(self, tmp_path, scripts_dir, task_config):
        from neuro_pipeline.pipeline.utils.hpc_utils import create_wrapper_script
        return create_wrapper_script(
            script_path=scripts_dir / "afni_cards_preprocessing.sh",
            subjects_list=["001"],
            input_dir="/in", output_dir="/out", work_dir=str(tmp_path / "work"),
            container_dir="/containers",
            task_config=task_config,
            project_config=MOCK_PROJECT_CONFIG,
        )

    def test_task_param_named_path_is_rejected(self, tmp_path, scripts_dir):
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            with pytest.raises(ValueError, match=r"\$PATH"):
                self._build(tmp_path, scripts_dir,
                            {"name": "t", "profile": "standard", "path": "/opt/tool"})

    def test_task_param_named_ifs_is_rejected(self, tmp_path, scripts_dir):
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            with pytest.raises(ValueError, match="IFS"):
                self._build(tmp_path, scripts_dir,
                            {"name": "t", "profile": "standard", "ifs": ","})

    def test_locale_params_are_allowed(self, tmp_path, scripts_dir):
        # LC_ALL=C is a normal thing to want for reproducible tool output
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            _wrapper, sections = self._build(
                tmp_path, scripts_dir,
                {"name": "t", "profile": "standard", "lc_all": "C"})
        assert "export LC_ALL='C'" in sections["task_params"]

    def test_pythonpath_param_is_allowed(self, tmp_path, scripts_dir):
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            _wrapper, sections = self._build(
                tmp_path, scripts_dir,
                {"name": "t", "profile": "standard", "pythonpath": "/opt/lib"})
        assert "export PYTHONPATH='/opt/lib'" in sections["task_params"]

    def test_ordinary_task_param_still_allowed(self, tmp_path, scripts_dir):
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            wrapper, sections = self._build(
                tmp_path, scripts_dir,
                {"name": "t", "profile": "standard", "template": "MNI152"})
        assert "export TEMPLATE='MNI152'" in sections["task_params"]


class TestArrayConfigFollowsCurrentConfig:
    """hpc_utils used to cache its own copy of config.yaml at module level.
    A long-running GUI switching config-dir would keep the first project's
    array pattern for the rest of the process lifetime.
    """

    @staticmethod
    def _array_for(cfg):
        with patch(PIPELINE_CONFIG_PATH, cfg), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            from neuro_pipeline.pipeline.utils.hpc_utils import get_hpc_resources
            return get_hpc_resources({"profile": "standard", "array": True}).array

    def test_pattern_read_from_current_config(self):
        cfg = {**MOCK_CONFIG, "array_config": {"pattern": "1-{num}%15"}}
        assert self._array_for(cfg) == "1-{num}%15"

    def test_switching_config_changes_the_pattern(self):
        project_a = {**MOCK_CONFIG, "array_config": {"pattern": "1-{num}%15"}}
        project_b = {**MOCK_CONFIG, "array_config": {"pattern": "1-{num}%30"}}
        assert self._array_for(project_a) == "1-{num}%15"
        assert self._array_for(project_b) == "1-{num}%30"

    def test_no_stale_module_level_cache(self):
        import neuro_pipeline.pipeline.utils.hpc_utils as mod
        assert not hasattr(mod, "config"), "hpc_utils must not keep its own config copy"
