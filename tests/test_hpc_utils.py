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

import copy
import json
import os
import sys
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock
from tests.conftest import MOCK_CONFIG, MOCK_HPC_CONFIG, MOCK_PROJECT_CONFIG


# config  = pipeline task/array config  (config.yaml)
# hpc_config = scheduler + resource profiles (hpc_config.yaml)
# hpc_utils reads the pipeline config through config_utils, so that is
# the single place to patch.
PIPELINE_CONFIG_PATH = "neuromaestro.pipeline.utils.config_utils.config"
HPC_CONFIG_PATH      = "neuromaestro.pipeline.utils.hpc_utils.hpc_config"


# ===========================================================================
# 1. get_hpc_resources
# ===========================================================================

class TestGetHPCResources:

    def _get(self, task_config):
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            from neuromaestro.pipeline.utils.hpc_utils import get_hpc_resources
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

    def test_array_pattern_carries_the_profile_limit(self):
        # the raw pattern is stored here; {num} is substituted in submit_slurm_job
        resources = self._get({"profile": "standard", "array": True})
        assert resources.array == "1-{num}%15"

    def test_non_array_task_has_no_array_param(self):
        resources = self._get({"profile": "standard", "array": False})
        assert resources.array is None

    def test_unknown_profile_raises_value_error(self):
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            from neuromaestro.pipeline.utils.hpc_utils import get_hpc_resources
            with pytest.raises(ValueError, match="Profile 'ghost_profile' not found"):
                get_hpc_resources({"profile": "ghost_profile"})

    def test_defaults_are_applied_when_profile_does_not_specify(self):
        """Profile only specifies memory+time; nodes/cpus come from defaults."""
        resources = self._get({"profile": "standard_short"})
        assert resources.nodes == 1
        assert resources.ntasks == 1

    def test_profile_value_overrides_the_default(self):
        # the mock keeps defaults and profiles disjoint, so precedence needs its own profile
        hpc = {**MOCK_HPC_CONFIG, "resource_profiles": {
            **MOCK_HPC_CONFIG["resource_profiles"],
            "bigmem": {"memory": "256gb", "time": "48:00:00", "partition": "highmem"},
        }}
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, hpc):
            from neuromaestro.pipeline.utils.hpc_utils import get_hpc_resources
            resources = get_hpc_resources({"profile": "bigmem"})
        assert resources.partition == "highmem"
        assert resources.cpus_per_task == 16


# ===========================================================================
# 2. get_environment_commands
# ===========================================================================

class TestGetEnvironmentCommands:

    def _get_env(self, task_config, project_config=None):
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            from neuromaestro.pipeline.utils.hpc_utils import get_environment_commands
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
        from neuromaestro.pipeline.utils.hpc_utils import get_script_with_validation
        result = get_script_with_validation("afni_cards_preprocessing.sh", str(scripts_dir))
        assert result is not None
        assert result.name == "afni_cards_preprocessing.sh"
        assert result.exists()

    def test_returns_none_when_script_missing(self, scripts_dir):
        from neuromaestro.pipeline.utils.hpc_utils import get_script_with_validation
        result = get_script_with_validation("nonexistent_script.sh", str(scripts_dir))
        assert result is None

    def test_returns_none_when_scripts_dir_missing(self, tmp_path, capsys):
        from neuromaestro.pipeline.utils.hpc_utils import get_script_with_validation
        result = get_script_with_validation("any.sh", str(tmp_path / "does_not_exist"))
        assert result is None
        assert capsys.readouterr().err.splitlines() == [
            f"[ERROR] Script 'any.sh' not found. Scripts directory {tmp_path / 'does_not_exist'} does not exist."]

    def test_missing_script_lists_the_ones_that_are_there(self, tmp_path, capsys):
        from neuromaestro.pipeline.utils.hpc_utils import get_script_with_validation
        for name in ("b.sh", "a.sh"):
            (tmp_path / name).write_text("#!/bin/bash\n")
        (tmp_path / "subdir").mkdir()
        assert get_script_with_validation("typo.sh", str(tmp_path)) is None
        assert capsys.readouterr().err.splitlines() == [
            f"[ERROR] Script 'typo.sh' not found in {tmp_path}. Available: a.sh, b.sh"]


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

    def _create(self, tmp_path, scripts_dir, subjects=None, extra_task_config=None,
                return_sections=False):
        subjects = subjects or ["001", "002", "003"]
        task_cfg = {**self.TASK_CONFIG, **(extra_task_config or {})}
        fake_script = scripts_dir / "afni_cards_preprocessing.sh"

        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            from neuromaestro.pipeline.utils.hpc_utils import create_wrapper_script

            wrapper_path, sections = create_wrapper_script(
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
        return (wrapper_path, sections) if return_sections else wrapper_path

    # ---- basic structure ---------------------------------------------------

    def test_wrapper_file_is_created(self, tmp_path, scripts_dir):
        wrapper = self._create(tmp_path, scripts_dir)
        assert wrapper.exists()
        assert wrapper.suffix == ".sh"

    @pytest.mark.skipif(sys.platform == "win32", reason="Windows has no executable bit; os.access is always true there")
    def test_wrapper_is_executable(self, tmp_path, scripts_dir):
        wrapper = self._create(tmp_path, scripts_dir)
        assert wrapper.stat().st_mode & 0o111 == 0o111

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

    @staticmethod
    def _exported(content, name):
        """The value of `export NAME='...'`, or None when the line is absent."""
        prefix = f"export {name}="
        line = next((l for l in content.splitlines() if l.startswith(prefix)), None)
        return None if line is None else line[len(prefix):].strip().strip("'")

    # create_wrapper_script passes these through verbatim; output_pattern is
    # applied upstream in submit_slurm_job, not here.

    def test_input_dir_exported(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert self._exported(content, "INPUT_DIR") == "/data/input"

    def test_output_dir_exported(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert self._exported(content, "OUTPUT_DIR") == str(tmp_path / "output")

    def test_work_dir_exported(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert self._exported(content, "WORK_DIR") == str(tmp_path / "work")

    def test_task_name_exported(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert "export TASK_NAME='cards_preprocess'" in content

    def test_db_path_exported(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        assert self._exported(content, "DB_PATH") == str(
            tmp_path / "work" / "pipeline_jobs.db"
        )

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
        assert 'source "$SCRIPT_DIR/utils/wrapper_functions.sh"' in content

    def test_execute_wrapper_called(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        script = (scripts_dir / "afni_cards_preprocessing.sh").resolve()
        assert content.splitlines()[-1] == f'execute_wrapper "{script}"'

    def test_script_dir_holds_the_sourced_functions(self, tmp_path, scripts_dir):
        content = self._create(tmp_path, scripts_dir).read_text()
        script_dir = Path(self._exported(content, "SCRIPT_DIR"))
        assert (script_dir / "utils" / "wrapper_functions.sh").is_file()

    # ---- the generated file is valid bash ----------------------------------
    # fed through stdin: on Windows the file itself is written with CRLF

    def test_wrapper_is_valid_bash(self, tmp_path, scripts_dir):
        import subprocess
        content = self._create(tmp_path, scripts_dir).read_text()
        result = subprocess.run(["bash", "-n"], input=content, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    def test_command_sections_reach_the_job_verbatim(self, tmp_path, scripts_dir):
        import subprocess
        wrapper, sections = self._create(tmp_path, scripts_dir, return_sections=True)
        # run every export but stop before the job itself is sourced
        exports = wrapper.read_text().split("# Source wrapper template and execute")[0]
        names = ("GLOBAL_PYTHON_COMMANDS", "ENV_COMMANDS", "GLOBAL_ENV_VARS", "TASK_PARAMS")
        script = exports + "printf '%s\\n--\\n' " + " ".join(f'"${n}"' for n in names) + "\n"
        out = subprocess.run(["bash"], input=script, capture_output=True, text=True).stdout
        keys = ("global_python", "env_modules", "global_env_vars", "task_params")
        assert out == "".join(f"{sections[k]}\n--\n" for k in keys)

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
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            from neuromaestro.pipeline.utils.hpc_utils import submit_slurm_job

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
             patch("subprocess.run") as mock_run:

            from neuromaestro.pipeline.utils.hpc_utils import submit_slurm_job

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
        task_config = {
            "name": "ghost_task",
            "profile": "standard",
            "array": False,
            "scripts": ["ghost_script.sh"],
        }

        project_config = {**MOCK_PROJECT_CONFIG, "scripts_dir": str(scripts_dir)}
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            from neuromaestro.pipeline.utils.hpc_utils import submit_slurm_job

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
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            from neuromaestro.pipeline.utils.hpc_utils import submit_slurm_job

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
        from neuromaestro.pipeline.utils.hpc_utils import SLURMBackend
        return SLURMBackend(MOCK_HPC_CONFIG["slurm"])

    def test_successful_submission_returns_job_id(self, tmp_path, capsys):
        backend = self._backend()
        fake_script = tmp_path / "wrapper.sh"
        fake_script.write_text("#!/bin/bash\n")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="Submitted batch job 12345\n")
            job_id = backend.submit_job(["--partition=batch"], fake_script)
        assert job_id == "12345"
        assert capsys.readouterr().out.splitlines() == ["Job submitted: 12345"]

    def test_failed_submission_returns_none(self, tmp_path, capsys):
        import subprocess
        backend = self._backend()
        fake_script = tmp_path / "wrapper.sh"
        fake_script.write_text("#!/bin/bash\n")
        err = subprocess.CalledProcessError(1, "sbatch", output="partial", stderr="permission denied")
        with patch("subprocess.run", side_effect=err):
            job_id = backend.submit_job(["--partition=batch"], fake_script)
        assert job_id is None
        # what sbatch said is the only clue the user gets
        assert capsys.readouterr().err.splitlines() == [
            f"Job submission failed: {err}", "STDOUT: partial", "STDERR: permission denied"]

    def test_first_word_parse_strategy(self, tmp_path):
        from neuromaestro.pipeline.utils.hpc_utils import SLURMBackend
        cfg = {**MOCK_HPC_CONFIG["slurm"], "job_id_parse": "first_word"}
        backend = SLURMBackend(cfg)
        fake_script = tmp_path / "wrapper.sh"
        fake_script.write_text("#!/bin/bash\n")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="99999 extra words\n")
            job_id = backend.submit_job(["--partition=batch"], fake_script)
        assert job_id == "99999"

    def test_raw_parse_strategy_keeps_the_whole_line(self, tmp_path):
        from neuromaestro.pipeline.utils.hpc_utils import SLURMBackend
        cfg = {**MOCK_HPC_CONFIG["slurm"], "job_id_parse": "whole_output"}
        backend = SLURMBackend(cfg)
        fake_script = tmp_path / "wrapper.sh"
        fake_script.write_text("#!/bin/bash\n")
        with patch("subprocess.run") as mock_run:
            # several tokens, so the raw line differs from its first and last word
            mock_run.return_value = MagicMock(stdout="  12345 on cluster  \n")
            job_id = backend.submit_job(["--partition=batch"], fake_script)
        assert job_id == "12345 on cluster"

    def test_submit_command_is_built_from_config(self, tmp_path):
        backend = self._backend()
        fake_script = tmp_path / "wrapper.sh"
        fake_script.write_text("#!/bin/bash\n")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="Submitted batch job 1\n")
            backend.submit_job(["--partition=batch", "--mem=32gb"], fake_script)
        cmd = mock_run.call_args.args[0]
        assert cmd == ["sbatch", "--partition=batch", "--mem=32gb", str(fake_script)]
        # the mock returns str stdout regardless, so the decoding flags are pinned here
        assert mock_run.call_args.kwargs == {"capture_output": True, "text": True, "check": True}

    def test_exit_zero_with_no_parsable_id_returns_none(self, tmp_path, capsys):
        """sbatch can exit 0 and print nothing usable (a warning-only run).

        Only CalledProcessError is caught, so an unparsable stdout must not be
        allowed to escape as an IndexError from split()[-1].
        """
        backend = self._backend()
        fake_script = tmp_path / "wrapper.sh"
        fake_script.write_text("#!/bin/bash\n")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="   \n", stderr="sbatch: warning: no partition")
            job_id = backend.submit_job(["--partition=batch"], fake_script)
        assert job_id is None
        assert capsys.readouterr().err.splitlines() == [
            "Job submission returned no job id (exit 0). STDOUT: '   \\n' STDERR: 'sbatch: warning: no partition'"]


# ===========================================================================
# 7. SLURMBackend.wait_for_jobs — mock subprocess
# ===========================================================================

class TestSLURMBackendWaitForJobs:

    def _backend(self):
        from neuromaestro.pipeline.utils.hpc_utils import SLURMBackend
        return SLURMBackend(MOCK_HPC_CONFIG["slurm"])

    # Every test here must bound the poll loop: a missing `break` in the
    # implementation would otherwise hang pytest instead of failing it.
    # pytest.mark.timeout is not available, so each case asserts call_count.

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
        err = subprocess.CalledProcessError(1, "squeue")
        with patch("subprocess.run", side_effect=err) as mock_run, \
             patch("time.sleep") as mock_sleep:
            backend.wait_for_jobs(["12345"], polling_interval=1)
        assert mock_run.call_count == 1
        mock_sleep.assert_not_called()

    def test_running_then_done(self):
        backend = self._backend()
        responses = [
            MagicMock(stdout="12345 RUNNING\n"),
            MagicMock(stdout=""),
        ]
        with patch("subprocess.run", side_effect=responses) as mock_run, \
             patch("time.sleep") as mock_sleep:
            backend.wait_for_jobs(["12345"], polling_interval=7)
        assert mock_run.call_count == 2
        mock_sleep.assert_called_once_with(7)

    def test_inactive_state_ends_the_wait_without_sleeping(self):
        # squeue still lists the job, but COMPLETING is not in active_states
        backend = self._backend()
        with patch("subprocess.run") as mock_run, patch("time.sleep") as mock_sleep:
            mock_run.return_value = MagicMock(stdout="12345 COMPLETING\n")
            backend.wait_for_jobs(["12345"], polling_interval=1)
        assert mock_run.call_count == 1
        mock_sleep.assert_not_called()

    def test_one_active_job_keeps_the_others_waiting(self):
        backend = self._backend()
        responses = [
            MagicMock(stdout="12345 COMPLETING\n12346 PENDING\n"),
            MagicMock(stdout="12345 COMPLETING\n12346 COMPLETING\n"),
        ]
        with patch("subprocess.run", side_effect=responses) as mock_run, \
             patch("time.sleep") as mock_sleep:
            backend.wait_for_jobs(["12345", "12346"], polling_interval=1)
        assert mock_run.call_count == 2
        assert mock_sleep.call_count == 1

    def test_malformed_status_line_is_ignored_not_treated_as_active(self):
        # a single-column line has no state to compare against active_states
        backend = self._backend()
        with patch("subprocess.run") as mock_run, patch("time.sleep") as mock_sleep:
            mock_run.return_value = MagicMock(stdout="12345\n")
            backend.wait_for_jobs(["12345"], polling_interval=1)
        assert mock_run.call_count == 1
        mock_sleep.assert_not_called()

    def test_status_command_comes_from_the_config(self):
        backend = self._backend()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="")
            backend.wait_for_jobs(["12345", "12346"], polling_interval=0)
        # without --format squeue prints PARTITION second, which the parser reads as the state
        assert mock_run.call_args.args[0] == [
            "squeue", "--job", "12345,12346", "--noheader", "--format=%i %T",
        ]
        assert mock_run.call_args.kwargs == {"capture_output": True, "text": True, "check": True}


# ===========================================================================
# 8. get_hpc_backend — unknown scheduler
# ===========================================================================

class TestGetHPCBackendUnknown:

    def test_unknown_scheduler_raises_not_implemented(self):
        cfg = {**MOCK_HPC_CONFIG, "scheduler": "lsf", "lsf": {"submit_cmd": "bsub"}}
        with patch(HPC_CONFIG_PATH, cfg):
            from neuromaestro.pipeline.utils.hpc_utils import get_hpc_backend
            with pytest.raises(NotImplementedError, match="lsf"):
                get_hpc_backend()

    def test_missing_scheduler_config_block_raises_value_error(self):
        cfg = {**MOCK_HPC_CONFIG, "scheduler": "lsf"}  # no "lsf" key
        with patch(HPC_CONFIG_PATH, cfg):
            from neuromaestro.pipeline.utils.hpc_utils import get_hpc_backend
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
        kwargs = {**self.BASE_KWARGS, "output_dir": str(tmp_path / "output"), **(extra_kwargs or {})}
        project_config = {**MOCK_PROJECT_CONFIG, "scripts_dir": str(scripts_dir)}
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            from neuromaestro.pipeline.utils.hpc_utils import submit_slurm_job
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

    def test_output_pattern_directory_is_created(self, tmp_path, scripts_dir):
        """The job writes to the pattern subdirectory, so that is the level that
        has to exist. Its parents arrive via parents=True, so only this one is
        worth asserting.
        """
        task_config = {"name": "cards_preprocess", "profile": "standard", "array": False,
                       "scripts": ["afni_cards_preprocessing.sh"],
                       "output_pattern": "{base_output}/AFNI_derivatives"}
        self._invoke(tmp_path, scripts_dir, task_config, {"subjects": "001"})
        assert (tmp_path / "output" / "AFNI_derivatives").is_dir()

    def test_output_dir_is_created_when_no_pattern_is_configured(self, tmp_path, scripts_dir):
        task_config = {"name": "cards_preprocess", "profile": "standard", "array": False,
                       "scripts": ["afni_cards_preprocessing.sh"]}
        self._invoke(tmp_path, scripts_dir, task_config, {"subjects": "001"})
        assert (tmp_path / "output").is_dir()

    def _submit_for_real(self, tmp_path, scripts_dir, task_config, subjects, wait_jobs=None):
        """Returns the argument list the backend was asked to submit."""
        project_config = {**MOCK_PROJECT_CONFIG, "scripts_dir": str(scripts_dir)}
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG), \
             patch("neuromaestro.pipeline.utils.hpc_utils.SLURMBackend.submit_job",
                   return_value="99999") as mock_submit:
            from neuromaestro.pipeline.utils.hpc_utils import submit_slurm_job
            job_id = submit_slurm_job(
                script_name="afni_cards_preprocessing.sh",
                subjects=subjects,
                work_dir=str(tmp_path / "work"),
                task_config=task_config,
                project_config=project_config,
                db_path=str(tmp_path / "work" / "pipeline_jobs.db"),
                dry_run=False,
                input_dir="/data/input",
                output_dir=str(tmp_path / "output"),
                container_dir="/containers",
                wait_jobs=wait_jobs,
                option_env={"session": "01"},
                requested_tasks=None,
                original_work_dir=None,
            )
        assert job_id == "99999"
        mock_submit.assert_called_once()
        args, wrapper = mock_submit.call_args.args
        assert list((tmp_path / "work" / "log" / "wrapper").glob("*_wrapper.sh")) == [wrapper]
        return args

    def test_non_dry_run_calls_backend_submit(self, tmp_path, scripts_dir):
        task_config = {"name": "cards_preprocess", "profile": "standard", "array": False,
                       "scripts": ["afni_cards_preprocessing.sh"]}
        args = self._submit_for_real(tmp_path, scripts_dir, task_config, subjects="001")
        log = tmp_path / "work" / "log" / "cards_preprocess"
        # what sbatch receives, not the copy echoed into the wrapper's comment
        assert args == [
            "--partition=batch", "--nodes=1", "--ntasks=1", "--cpus-per-task=16",
            "--time=20:00:00", "--job-name=afni_cards_preprocessing",
            f"--output={log}/cards_preprocess_%A.out",
            f"--error={log}/cards_preprocess_%A.err",
            "--mem=32gb",
        ]

    def test_array_job_submits_array_and_dependency_flags(self, tmp_path, scripts_dir):
        task_config = {"name": "cards_preprocess", "profile": "standard", "array": True,
                       "scripts": ["afni_cards_preprocessing.sh"]}
        args = self._submit_for_real(tmp_path, scripts_dir, task_config,
                                     subjects="001,002,003", wait_jobs=["111", "222"])
        log = tmp_path / "work" / "log" / "cards_preprocess"
        assert f"--output={log}/cards_preprocess_%A-%a.out" in args
        assert f"--error={log}/cards_preprocess_%A-%a.err" in args
        assert args[-2:] == ["--array=1-3%15", "--dependency=afterany:111:222"]

    def test_resubmitting_into_existing_directories_works(self, tmp_path, scripts_dir):
        # every --resume run submits into the directories the first run created
        task_config = {"name": "cards_preprocess", "profile": "standard", "array": True,
                       "scripts": ["afni_cards_preprocessing.sh"],
                       "output_pattern": "{base_output}/AFNI_derivatives"}
        for _ in range(2):
            job_id = self._invoke(tmp_path, scripts_dir, task_config, {"subjects": "001,002"})
            assert job_id == "dry_run_afni_cards_preprocessing"


class TestSubmissionSideEffects:
    """What a submission leaves behind besides the scheduler call."""

    TASK = {"name": "cards_preprocess", "profile": "standard", "scripts": ["afni_cards_preprocessing.sh"]}

    def _submit(self, tmp_path, scripts_dir, array, job_id="99999", dry_run=False, execution_id=None):
        project_config = {**MOCK_PROJECT_CONFIG, "scripts_dir": str(scripts_dir)}
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG), \
             patch("neuromaestro.pipeline.utils.hpc_utils.SLURMBackend.submit_job",
                   return_value=job_id) as mock_submit:
            from neuromaestro.pipeline.utils.hpc_utils import submit_slurm_job
            returned = submit_slurm_job(
                script_name="afni_cards_preprocessing.sh", subjects="001,002",
                work_dir=str(tmp_path / "work"), task_config={**self.TASK, "array": array},
                project_config=project_config, db_path=str(tmp_path / "db" / "pipeline_jobs.db"),
                dry_run=dry_run, input_dir="/data/input", output_dir=str(tmp_path / "output"),
                container_dir="/containers", wait_jobs=None, option_env={"session": "01"},
                requested_tasks=None, original_work_dir=None, execution_id=execution_id,
            )
        return returned, mock_submit

    @staticmethod
    def _wrapper_records(tmp_path):
        files = sorted((tmp_path / "db" / "json" / "_pipeline").glob("wrapper_*.jsonl"))
        return [json.loads(line) for f in files for line in f.read_text(encoding="utf-8").splitlines()]

    def test_array_job_gets_a_log_dir_per_subject(self, tmp_path, scripts_dir):
        self._submit(tmp_path, scripts_dir, array=True)
        log = tmp_path / "work" / "log" / "cards_preprocess"
        assert sorted(p.name for p in log.iterdir()) == ["sub-001", "sub-002"]

    def test_single_job_gets_only_the_task_log_dir(self, tmp_path, scripts_dir):
        # --output points here, and the scheduler does not create missing directories
        self._submit(tmp_path, scripts_dir, array=False)
        log = tmp_path / "work" / "log" / "cards_preprocess"
        assert log.is_dir()
        assert list(log.iterdir()) == []

    def test_submitted_wrapper_is_recorded_for_the_report(self, tmp_path, scripts_dir):
        job_id, mock_submit = self._submit(tmp_path, scripts_dir, array=True, execution_id=42)
        assert job_id == "99999"
        args, wrapper = mock_submit.call_args.args
        (record,) = self._wrapper_records(tmp_path)
        assert (record["event"], record["task_name"], record["job_id"], record["execution_id"]) == (
            "wrapper_script", "cards_preprocess", "99999", 42)
        assert record["wrapper_path"] == str(wrapper)
        assert record["slurm_cmd"] == f"sbatch {' '.join(args)} {wrapper}"
        assert record["full_content"] == Path(wrapper).read_text()

    def test_failed_submission_records_no_wrapper(self, tmp_path, scripts_dir):
        job_id, _ = self._submit(tmp_path, scripts_dir, array=True, job_id=None)
        assert job_id is None
        assert self._wrapper_records(tmp_path) == []

    def test_dry_run_records_no_wrapper(self, tmp_path, scripts_dir):
        job_id, mock_submit = self._submit(tmp_path, scripts_dir, array=True, dry_run=True)
        assert job_id == "dry_run_afni_cards_preprocessing"
        mock_submit.assert_not_called()
        assert self._wrapper_records(tmp_path) == []

    def test_logging_failure_does_not_block_submission(self, tmp_path, scripts_dir):
        with patch("neuromaestro.pipeline.utils.job_db.log_wrapper_script", side_effect=OSError("disk full")):
            job_id, _ = self._submit(tmp_path, scripts_dir, array=True)
        assert job_id == "99999"


class TestOptionalResourceFlags:

    @staticmethod
    def _resources(**extra):
        from neuromaestro.pipeline.utils.hpc_utils import HPCResources
        return HPCResources(partition="batch", nodes=1, ntasks=1, cpus_per_task=4,
                            memory="8gb", time="01:00:00", **extra)

    def _slurm_args(self, **extra):
        from neuromaestro.pipeline.utils.hpc_utils import SLURMBackend
        cfg = copy.deepcopy(MOCK_HPC_CONFIG["slurm"])
        cfg["resource_flags"]["gres"] = "--gres={value}"
        return SLURMBackend(cfg).build_job_args(resources=self._resources(**extra), array_param=None,
                                                wait_jobs=["7"], job_name="j", log_output="o", log_error="e")

    def test_slurm_gpu_request(self):
        assert self._slurm_args(gres="gpu:1")[-2:] == ["--gres=gpu:1", "--dependency=afterany:7"]

    def test_slurm_no_gpu_request_without_gres(self):
        assert not any(a.startswith("--gres") for a in self._slurm_args())

    def test_slurm_additional_args_come_before_the_dependency(self):
        args = self._slurm_args(additional_args=["--account=lab", "--qos=high"])
        assert args[-3:] == ["--account=lab", "--qos=high", "--dependency=afterany:7"]

    @pytest.mark.parametrize("gres, expected", [("1", ["-l ngpus=1"]), (None, [])])
    def test_pbs_gpu_request(self, gres, expected):
        from neuromaestro.pipeline.utils.hpc_utils import PBSBackend
        from tests.test_pbs_backend import PBS_CONFIG
        cfg = copy.deepcopy(PBS_CONFIG)
        cfg["resource_flags"]["gres"] = "-l ngpus={value}"
        args = PBSBackend(cfg).build_job_args(resources=self._resources(gres=gres), array_param=None,
                                              wait_jobs=None, job_name="j", log_output="o", log_error="e")
        assert [a for a in args if "ngpus" in a] == expected

    def test_profile_gres_and_additional_args_reach_the_resources(self):
        hpc = copy.deepcopy(MOCK_HPC_CONFIG)
        hpc["resource_profiles"]["gpu"] = {"memory": "8gb", "time": "01:00:00", "gres": "gpu:2",
                                           "additional_args": ["--account=lab"]}
        with patch(HPC_CONFIG_PATH, hpc):
            from neuromaestro.pipeline.utils.hpc_utils import get_hpc_resources
            resources = get_hpc_resources({"name": "t", "profile": "gpu"})
        assert (resources.gres, resources.additional_args) == ("gpu:2", ["--account=lab"])

    def test_task_without_array_flag_is_not_an_array(self):
        with patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            from neuromaestro.pipeline.utils.hpc_utils import get_hpc_resources
            assert get_hpc_resources({"name": "t", "profile": "standard"}).array is None

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
        from neuromaestro.pipeline.utils.hpc_utils import _export_line
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

    def _build(self, tmp_path, scripts_dir, task_config, project_config=None):
        from neuromaestro.pipeline.utils.hpc_utils import create_wrapper_script
        return create_wrapper_script(
            script_path=scripts_dir / "afni_cards_preprocessing.sh",
            subjects_list=["001"],
            input_dir="/in", output_dir="/out", work_dir=str(tmp_path / "work"),
            container_dir="/containers",
            task_config=task_config,
            project_config=project_config or MOCK_PROJECT_CONFIG,
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

    # ---- shadowing the wrapper's own path variables ------------------------
    # create_env_file writes GLOBAL_ENV_VARS and TASK_PARAMS after the wrapper's
    # own exports, so these would win silently and send the job's writes to a
    # directory the pipeline never created.

    def _envir_dir_with(self, **extra):
        return {
            **MOCK_PROJECT_CONFIG,
            "envir_dir": {**MOCK_PROJECT_CONFIG["envir_dir"], **extra},
        }

    def test_envir_dir_key_shadowing_output_dir_is_rejected(self, tmp_path, scripts_dir):
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            with pytest.raises(ValueError, match=r"\$OUTPUT_DIR"):
                self._build(tmp_path, scripts_dir,
                            {"name": "t", "profile": "standard"},
                            project_config=self._envir_dir_with(output_dir="/elsewhere"))

    def test_envir_dir_key_shadowing_db_path_is_rejected(self, tmp_path, scripts_dir):
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            with pytest.raises(ValueError, match=r"\$DB_PATH"):
                self._build(tmp_path, scripts_dir,
                            {"name": "t", "profile": "standard"},
                            project_config=self._envir_dir_with(db_path="/elsewhere/jobs.db"))

    def test_task_param_shadowing_work_dir_is_rejected(self, tmp_path, scripts_dir):
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            with pytest.raises(ValueError, match=r"\$WORK_DIR"):
                self._build(tmp_path, scripts_dir,
                            {"name": "t", "profile": "standard", "work_dir": "/elsewhere"})

    def test_container_dir_from_envir_dir_is_still_allowed(self, tmp_path, scripts_dir):
        """CONTAINER_DIR's legitimate source is envir_dir, which re-exports the
        same value the wrapper already holds. Adding it to the name list would
        reject every real project config.
        """
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            _wrapper, sections = self._build(
                tmp_path, scripts_dir, {"name": "t", "profile": "standard"})
        assert "export CONTAINER_DIR=" in sections["global_env_vars"]

    def test_ordinary_envir_dir_keys_are_still_allowed(self, tmp_path, scripts_dir):
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            _wrapper, sections = self._build(
                tmp_path, scripts_dir, {"name": "t", "profile": "standard"})
        for var in ("ATLAS_DIR", "TEMPLATE_DIR", "FREESURFER_DIR", "STIMULUS_DIR"):
            assert f"export {var}=" in sections["global_env_vars"], var


class TestArrayLimitComesFromTheProfile:
    """Array throttling used to be one global pattern in config.yaml. It now
    rides on the resource profile, so a 64gb task and a 16gb one can differ.
    """

    @staticmethod
    def _array_for(profile):
        with patch(PIPELINE_CONFIG_PATH, MOCK_CONFIG), patch(HPC_CONFIG_PATH, MOCK_HPC_CONFIG):
            from neuromaestro.pipeline.utils.hpc_utils import get_hpc_resources
            return get_hpc_resources({"profile": profile, "array": True}).array

    def test_limit_read_from_profile(self):
        assert self._array_for("standard") == "1-{num}%15"

    def test_profiles_can_carry_different_limits(self):
        assert self._array_for("heavy_long") == "1-{num}%8"

    def test_profile_without_a_limit_is_unthrottled(self):
        assert self._array_for("light_short") == "1-{num}"

    def test_no_stale_module_level_cache(self):
        import neuromaestro.pipeline.utils.hpc_utils as mod
        assert not hasattr(mod, "config"), "hpc_utils must not keep its own config copy"


class TestSwitchingConfigDirReloadsHpcConfig:
    """hpc_config.yaml is cached in a module global. A long-lived process (the
    Dash app) switching projects kept the first project's profiles for the rest
    of its lifetime; set_config_dir now drops that cache.
    """

    @staticmethod
    def _make_config_dir(root, array_limit):
        root.mkdir(parents=True, exist_ok=True)
        (root / "config.yaml").write_text(yaml.safe_dump({
            "prep": [{"name": "recon", "profile": "standard", "array": True}],
        }), encoding="utf-8")
        (root / "hpc_config.yaml").write_text(yaml.safe_dump({
            "scheduler": "slurm",
            "defaults": {"partition": "batch", "nodes": 1, "ntasks": 1, "cpus_per_task": 1},
            "resource_profiles": {
                "standard": {"memory": "1gb", "time": "01:00:00", "array_limit": array_limit},
            },
            "slurm": {"submit_cmd": "sbatch"},
        }), encoding="utf-8")
        return root

    def test_switching_dir_picks_up_the_new_profiles(self, tmp_path):
        from neuromaestro.pipeline.utils import config_utils, hpc_utils

        # these are module globals; leaking them breaks unrelated tests
        saved = (config_utils._config_dir, config_utils.config, hpc_utils.hpc_config)
        try:
            project_a = self._make_config_dir(tmp_path / "a", 15)
            project_b = self._make_config_dir(tmp_path / "b", 40)
            task = {"profile": "standard", "array": True}

            config_utils.set_config_dir(project_a)
            assert hpc_utils.get_hpc_resources(task).array == "1-{num}%15"

            config_utils.set_config_dir(project_b)
            assert hpc_utils.get_hpc_resources(task).array == "1-{num}%40"
        finally:
            config_utils._config_dir, config_utils.config, hpc_utils.hpc_config = saved
