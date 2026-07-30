"""
test_config_contract.py

Almost every other test in this suite runs against conftest.MOCK_CONFIG and
MOCK_HPC_CONFIG, which are hand-written parallel copies of the shipped
config/*.yaml. Nothing forces the two to stay aligned, so a rename or a new
required field in the real config leaves the whole suite green while it
verifies a structure that no longer ships. These tests are that missing link.

They deliberately assert structure, not values: the mocks are meant to be a
minimal subset, so a mock may cover fewer sections and use different numbers,
but it may not use a section, field, profile or script that does not exist.
"""

import yaml
import pytest
from pathlib import Path
from unittest.mock import patch

from tests.conftest import (
    MOCK_CONFIG,
    MOCK_HPC_CONFIG,
    MOCK_PROJECT_CONFIG,
    mock_script_names,
)

_PKG = Path(__file__).resolve().parent.parent / "src" / "neuro_pipeline"


def _load_yaml(name):
    with open(_PKG / "config" / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def real_config():
    return _load_yaml("config.yaml")


@pytest.fixture(scope="module")
def real_hpc_config():
    return _load_yaml("hpc_config.yaml")


def _tasks(cfg):
    """Flatten every task section into {task_name: task_dict}."""
    out = {}
    for tasks in cfg.values():
        if isinstance(tasks, list):
            for t in tasks:
                if isinstance(t, dict) and "name" in t:
                    out[t["name"]] = t
    return out


# ---------------------------------------------------------------------------
# MOCK_CONFIG vs config.yaml
# ---------------------------------------------------------------------------

class TestMockConfigTracksTheRealConfig:

    def test_mock_is_not_empty(self, real_config):
        # everything below is a subset check, which an empty mock would pass
        assert len(_tasks(MOCK_CONFIG)) >= 10
        assert len(_tasks(real_config)) >= 10

    def test_every_mock_section_still_exists(self, real_config):
        assert set(MOCK_CONFIG) <= set(real_config)

    def test_every_mock_task_still_exists(self, real_config):
        assert set(_tasks(MOCK_CONFIG)) <= set(_tasks(real_config))

    def test_mock_tasks_declare_the_same_fields(self, real_config):
        """A field added to or renamed in the real config must reach the mock."""
        real = _tasks(real_config)
        for name, mock_task in _tasks(MOCK_CONFIG).items():
            assert set(mock_task) == set(real[name]), name

    def test_mock_input_from_targets_exist(self):
        names = set(_tasks(MOCK_CONFIG))
        for name, task in _tasks(MOCK_CONFIG).items():
            upstream = task.get("input_from")
            if upstream:
                assert upstream in names, f"{name} -> {upstream}"

    def test_mock_scripts_exist_in_the_package(self):
        """The regression: bfc pointed at bfc_scratch.sh long after the rename."""
        available = {p.name for p in (_PKG / "scripts").rglob("*.sh")}
        assert available
        referenced = mock_script_names()
        assert referenced
        for script in referenced:
            assert script in available, script

    def test_array_config_shape_matches(self, real_config):
        assert set(MOCK_CONFIG["array_config"]) == set(real_config["array_config"])


# ---------------------------------------------------------------------------
# MOCK_HPC_CONFIG vs hpc_config.yaml
# ---------------------------------------------------------------------------

class TestMockHpcConfigTracksTheRealConfig:

    def test_same_scheduler(self, real_hpc_config):
        assert MOCK_HPC_CONFIG["scheduler"] == real_hpc_config["scheduler"]

    def test_profile_names_match_exactly(self, real_hpc_config):
        # a profile the mock invents would let a task reference something the
        # real cluster config cannot resolve
        assert set(MOCK_HPC_CONFIG["resource_profiles"]) == set(
            real_hpc_config["resource_profiles"]
        )

    def test_every_mock_task_profile_is_a_real_profile(self, real_hpc_config):
        profiles = set(real_hpc_config["resource_profiles"])
        used = {t["profile"] for t in _tasks(MOCK_CONFIG).values() if "profile" in t}
        assert used
        assert used <= profiles

    def test_scheduler_block_fields_still_exist(self, real_hpc_config):
        scheduler = MOCK_HPC_CONFIG["scheduler"]
        assert set(MOCK_HPC_CONFIG[scheduler]) <= set(real_hpc_config[scheduler])

    def test_resource_flags_still_exist(self, real_hpc_config):
        scheduler = MOCK_HPC_CONFIG["scheduler"]
        mock_flags = set(MOCK_HPC_CONFIG[scheduler]["resource_flags"])
        real_flags = set(real_hpc_config[scheduler]["resource_flags"])
        assert mock_flags
        assert mock_flags <= real_flags


# ---------------------------------------------------------------------------
# The shipped hpc_config.yaml, run through the real resolver
#
# MOCK_HPC_CONFIG deliberately leaves nodes/ntasks/cpus_per_task in `defaults`
# so that the fallback merge in get_hpc_resources stays covered. The shipped
# config takes the opposite shape — every profile carries its own copy — and
# nothing executed that shape, so a profile missing a required key would only
# surface as a KeyError on the cluster.
# ---------------------------------------------------------------------------

class TestTheShippedHpcConfigResolves:

    def test_every_profile_yields_complete_resources(self, real_hpc_config):
        from neuro_pipeline.pipeline.utils import hpc_utils

        profiles = list(real_hpc_config["resource_profiles"])
        assert profiles
        with patch.object(hpc_utils, "hpc_config", real_hpc_config):
            for profile in profiles:
                res = hpc_utils.get_hpc_resources({"profile": profile})
                for field in ("partition", "nodes", "ntasks", "cpus_per_task",
                              "memory", "time"):
                    assert getattr(res, field), f"{profile}.{field}"

    def test_unknown_profile_is_rejected(self, real_hpc_config):
        from neuro_pipeline.pipeline.utils import hpc_utils

        with patch.object(hpc_utils, "hpc_config", real_hpc_config):
            with pytest.raises(ValueError):
                hpc_utils.get_hpc_resources({"profile": "no_such_profile"})


# ---------------------------------------------------------------------------
# MOCK_PROJECT_CONFIG vs the shipped project_config templates
# ---------------------------------------------------------------------------

class TestMockProjectConfigTracksTheTemplates:

    @pytest.fixture
    def template(self):
        # MOCK_PROJECT_CONFIG documents itself as mirroring test_config.yaml
        path = _PKG / "config" / "project_config" / "test_config.yaml"
        assert path.exists(), path
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_top_level_keys_still_exist(self, template):
        assert set(MOCK_PROJECT_CONFIG) <= set(template)

    def test_envir_dir_keys_still_exist(self, template):
        mock_keys = set(MOCK_PROJECT_CONFIG["envir_dir"])
        assert mock_keys
        assert mock_keys <= set(template["envir_dir"])

    def test_mock_task_overrides_name_real_tasks(self, real_config):
        assert set(MOCK_PROJECT_CONFIG["tasks"]) <= set(_tasks(real_config))
