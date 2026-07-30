"""
conftest.py — Shared fixtures for all test modules

Assumed package layout:
    neuro_pipeline/
        config/
            config.yaml
            hpc_config.yaml
            project_config/
            results_check/
        scripts/
            template/
            ...
        pipeline/
            core.py
            dag.py
            utils/
                config_utils.py
                hpc_utils.py
                detect_subjects.py
                job_db.py
    tests/
        conftest.py
        test_config_utils.py
        test_dag.py
        test_hpc_utils.py
"""

import copy
import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Minimal in-memory config that mirrors config.yaml structure
# ---------------------------------------------------------------------------

MOCK_HPC_CONFIG = {
    "scheduler": "slurm",
    # Unlike the shipped config, these stay in defaults to cover the fallback merge
    "defaults": {
        "partition": "batch",
        "nodes": 1,
        "ntasks": 1,
        "cpus_per_task": 16,
    },
    "resource_profiles": {
        "data_manage":    {"memory": "2gb",  "time": "00:20:00"},
        "light_short":    {"memory": "16gb", "time": "04:00:00"},
        "standard":       {"memory": "32gb", "time": "20:00:00"},
        "standard_short": {"memory": "32gb", "time": "08:00:00"},
        "heavy_long":     {"memory": "64gb", "time": "24:00:00"},
    },
    "slurm": {
        "submit_cmd": "sbatch",
        "job_id_parse": "last_word",
        "dependency_flag": "--dependency=afterany:{jobs}",
        "array_flag": "--array={array}",
        "resource_flags": {
            "partition": "--partition={value}",
            "nodes": "--nodes={value}",
            "ntasks": "--ntasks={value}",
            "cpus_per_task": "--cpus-per-task={value}",
            "time": "--time={value}",
            "mem": "--mem={value}",
            "job_name": "--job-name={value}",
            "output": "--output={value}",
            "error": "--error={value}",
        },
        "status_cmd": "squeue",
        "status_args": ["--noheader", "--format=%i %T"],
        "active_states": ["PENDING", "RUNNING"],
        "cancel_cmd": "scancel",
    },
}

MOCK_CONFIG = {
    "prep": [
        {
            "name": "unzip",
            "profile": "standard",
            "scripts": ["unzip_rename.sh"],
            "output_pattern": "{base_output}/raw",
        },
        {
            "name": "recon",
            "profile": "light_short",
            "array": True,
            "scripts": ["dcm2bids_convert_BIDS.sh"],
            "input_from": "unzip",
            "output_pattern": "{base_output}/BIDS",
        },
    ],
    "intermed": [
        {
            "name": "volume",
            "profile": "standard_short",
            "array": True,
            "input_from": "recon",
            "scripts": ["sswarp_scratch.sh"],
            "output_pattern": "{base_output}/AFNI_derivatives",
        },
        {
            "name": "bfc",
            "profile": "standard_short",
            "array": True,
            "input_from": "recon",
            "scripts": ["sdcflows.sh"],
            "output_pattern": "{base_output}/BIDS_derivatives/sdcflows",
        },
    ],
    "rest": [
        {
            "name": "rest_preprocess",
            "stage": "prep",
            "profile": "heavy_long",
            "array": True,
            "input_from": "recon",
            "scripts": ["fmriprep_rs.sh"],
            "output_pattern": "{base_output}/BIDS_derivatives/fmriprep",
        },
        {
            "name": "rest_post",
            "stage": "post",
            "profile": "standard_short",
            "array": True,
            "input_from": "rest_preprocess",
            "scripts": ["xcpd_rs.sh"],
            "output_pattern": "{base_output}/BIDS_derivatives/xcpd",
        },
    ],
    "dwi": [
        {
            "name": "dwi_preprocess",
            "stage": "prep",
            "profile": "standard",
            "array": True,
            "input_from": "recon",
            "scripts": ["qsiprep.sh"],
            "output_pattern": "{base_output}/BIDS_derivatives/qsiprep",
        },
        {
            "name": "dwi_post",
            "stage": "post",
            "profile": "standard",
            "array": True,
            "input_from": "dwi_preprocess",
            "scripts": ["qsirecon.sh"],
            "output_pattern": "{base_output}/BIDS_derivatives/qsirecon",
        },
    ],
    "cards": [
        {
            "name": "cards_preprocess",
            "stage": "prep",
            "multi_stage": True,
            "profile": "standard",
            "array": True,
            "input_from": "recon",
            "scripts": ["afni_cards_preprocessing.sh"],
            "output_pattern": "{base_output}/AFNI_derivatives",
        },
    ],
    "kidvid": [
        {
            "name": "kidvid_preprocess",
            "stage": "prep",
            "multi_stage": True,
            "profile": "standard",
            "array": True,
            "input_from": "recon",
            "scripts": ["afni_kidvid_preprocess.sh"],
            "output_pattern": "{base_output}/AFNI_derivatives",
        },
    ],
    "qc": [
        {
            "name": "mriqc_preprocess",
            "stage": "prep",
            "profile": "heavy_long",
            "array": True,
            "input_from": "recon",
            "scripts": ["mriqc_individual.sh"],
            "output_pattern": "{base_output}/quality_control/mriqc",
        },
        {
            "name": "mriqc_post",
            "stage": "post",
            "profile": "light_short",
            "input_from": "recon",
            "scripts": ["mriqc_group.sh"],
            "output_pattern": "{base_output}/quality_control/mriqc",
        },
    ],
    "array_config": {
        "pattern": "1-{num}%15",
    },
}

# Minimal project config (mirrors test_config.yaml).
#
# IMPORTANT: envir_dir paths must point to LOCAL directories only.
# Never use NFS/network mounts here (e.g. /work/cglab/...) — Path.exists()
# on a slow or unavailable NFS mount blocks indefinitely and will hang
# pytest and any --dry-run invocation that runs preflight checks.
#
# Use /tmp-based paths: they resolve instantly even when they don't exist.
# Tests that need the directories to actually exist should use the
# `preflight_project_config` fixture below, which creates them under tmp_path.
MOCK_PROJECT_CONFIG = {
    "prefix": "sub-",
    "scripts_dir": "scripts/test",
    "database": {
        "db_path": "$WORK_DIR/database/pipeline_jobs.db",
    },
    "envir_dir": {
        # /tmp paths — local filesystem, .exists() returns instantly
        "container_dir": "/tmp/mock_cglab/containers",
        "virtual_envir": "/tmp/mock_cglab/conda_env",
        "template_dir": "/tmp/mock_cglab/projects/BRANCH/all_data/for_AFNI",
        "atlas_dir": "/tmp/mock_cglab/projects/BRANCH/all_data/for_AFNI",
        "freesurfer_dir": "/tmp/mock_cglab/containers/.licenses/freesurfer",
        "config_dir": "/tmp/mock_cglab/conda_env/config_for_BIDS",
        "stimulus_dir": "/tmp/mock_cglab/projects/BRANCH/all_data/for_AFNI/processing_scripts",
    },
    "global_python": [
        "ml Python/3.11.3-GCCcore-12.3.0",
        ". /home/$USER/virtual_environ/neuro_pipeline/bin/activate",
    ],
    "modules": {
        "afni_24.3.06": [
            "ml Flask/2.3.3-GCCcore-12.3.0",
            "ml netpbm/10.73.43-GCC-12.3.0",
            "ml AFNI/24.3.06-foss-2023a",
        ],
        "fsl_6.0.7.14": [
            "ml FSL/6.0.7.14-foss-2023a",
            '[ -n "$FSLDIR" ] && source ${FSLDIR}/etc/fslconf/fsl.sh',
        ],
        "data_manage_1": [
            "ml p7zip/17.05-GCCcore-13.3.0",
            "ml parallel/20240722-GCCcore-13.3.0",
        ],
    },
    "tasks": {
        "unzip":            {"environ": ["data_manage_1", "afni_24.3.06"]},
        "recon":       {"container": "dcm2bids_3.2.0.sif", "config": "branch_config.json"},
        "volume":           {"environ": ["afni_24.3.06"], "template": "HaskinsPeds_NL_template1.0_SSW.nii"},
        "bfc":              {"environ": ["afni_24.3.06"]},
        "rest_preprocess":  {"remove_TRs": 6, "template": "MNI152NLin2009cAsym", "container": "fmriprep_25.1.3.sif", "license": "license.txt"},
        "rest_post":        {"remove_TRs": 6, "template": "MNI152NLin2009cAsym", "container": "xcp_d-0.11.0rc1.sif", "rest_mode": "abcd", "nuisance_regressors": "36P", "license": "license.txt"},
        "cards_preprocess": {"remove_TRs": 2, "template": "HaskinsPeds_NL_template1.0_SSW.nii", "blur_size": 4.0, "environ": ["afni_24.3.06"], "censor_motion": "0.3", "censor_outliers": "0.05"},
        "kidvid_preprocess":{"remove_TRs": 22, "template": "HaskinsPeds_NL_template1.0_SSW.nii", "blur_size": 4.0, "environ": ["afni_24.3.06"], "censor_motion": "0.3", "censor_outliers": "0.05"},
        "dwi_preprocess":   {"container": "qsiprep_0.23.0.sif"},
        "dwi_post":         {"container": "qsirecon_0.23.0.sif"},
        "mriqc_preprocess": {"container": "mriqc_24.0.2.sif"},
        "mriqc_post":       {"container": "mriqc_24.0.2.sif"},
    },
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_config():
    """Return a copy of the in-memory global config."""
    # deep, not shallow: the nested task dicts are shared across every test
    return copy.deepcopy(MOCK_CONFIG)


@pytest.fixture
def mock_project_config():
    """Return a copy of the in-memory project config."""
    return copy.deepcopy(MOCK_PROJECT_CONFIG)



@pytest.fixture
def config_yaml_file(tmp_path):
    """Write MOCK_CONFIG to a real YAML file and return its Path."""
    cfg_file = tmp_path / "config.yaml"
    with open(cfg_file, "w") as f:
        yaml.dump(MOCK_CONFIG, f)
    return cfg_file


def mock_script_names():
    """Every script MOCK_CONFIG references."""
    names = []
    for tasks in MOCK_CONFIG.values():
        if isinstance(tasks, list):
            for t in tasks:
                names.extend(t.get("scripts", []))
    return sorted(set(names))


@pytest.fixture
def scripts_dir(tmp_path):
    """
    Create a fake scripts directory pre-populated with the shell scripts
    referenced in MOCK_CONFIG so path-resolution tests can pass without
    touching the real filesystem.
    """
    s_dir = tmp_path / "scripts" / "test"
    s_dir.mkdir(parents=True)
    # derived, not hand-listed: a hand-listed copy silently fell behind MOCK_CONFIG
    for name in mock_script_names():
        (s_dir / name).write_text("#!/bin/bash\necho mock script\n")
    return s_dir


@pytest.fixture
def work_dir(tmp_path):
    """Return a temporary work directory."""
    d = tmp_path / "work"
    d.mkdir()
    return d


@pytest.fixture
def output_dir(tmp_path):
    """Return a temporary output directory."""
    d = tmp_path / "output"
    d.mkdir()
    return d


@pytest.fixture
def input_dir(tmp_path):
    """Return a temporary input directory with some fake subject folders."""
    d = tmp_path / "input"
    d.mkdir()
    for sub in ["sub-001", "sub-002", "sub-003"]:
        (d / sub).mkdir()
    (d / "not_a_subject.txt").write_text("ignore me")
    return d