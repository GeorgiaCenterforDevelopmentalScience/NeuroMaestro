"""
Tests for init_project_templates in pipeline/utils/init_utils.py.
"""

import shutil
from pathlib import Path
import pytest


class TestInitProjectTemplates:

    def test_copies_global_config_files(self, tmp_path):
        from neuro_pipeline.pipeline.utils.init_utils import init_project_templates
        config_dir = tmp_path / "config"
        copied = init_project_templates(config_dir)

        assert "config.yaml" in copied
        assert "hpc_config.yaml" in copied
        assert (config_dir / "config.yaml").exists()
        assert (config_dir / "hpc_config.yaml").exists()

    def test_copies_project_config_subdir(self, tmp_path):
        from neuro_pipeline.pipeline.utils.init_utils import init_project_templates
        config_dir = tmp_path / "config"
        copied = init_project_templates(config_dir)

        assert "project_config/" in copied
        assert (config_dir / "project_config").is_dir()
        assert any((config_dir / "project_config").iterdir())

    def test_copies_results_check_subdir(self, tmp_path):
        from neuro_pipeline.pipeline.utils.init_utils import init_project_templates
        config_dir = tmp_path / "config"
        copied = init_project_templates(config_dir)

        assert "results_check/" in copied
        assert (config_dir / "results_check").is_dir()
        assert any((config_dir / "results_check").iterdir())

    def test_creates_config_dir_if_missing(self, tmp_path):
        from neuro_pipeline.pipeline.utils.init_utils import init_project_templates
        config_dir = tmp_path / "deep" / "nested" / "config"
        assert not config_dir.exists()
        init_project_templates(config_dir)
        assert config_dir.is_dir()

    def test_scripts_placed_next_to_config(self, tmp_path):
        from neuro_pipeline.pipeline.utils.init_utils import init_project_templates
        config_dir = tmp_path / "study" / "config"
        copied = init_project_templates(config_dir)

        assert "scripts/" in copied
        scripts_dir = tmp_path / "study" / "scripts"
        assert scripts_dir.is_dir()
        assert any(scripts_dir.glob("*.sh"))
        # the regression: scripts must sit beside config_dir, not inside it
        assert not (config_dir / "scripts").exists()

    def test_idempotent_on_repeat_call(self, tmp_path):
        from neuro_pipeline.pipeline.utils.init_utils import init_project_templates
        config_dir = tmp_path / "config"
        init_project_templates(config_dir)
        copied2 = init_project_templates(config_dir)
        assert "config.yaml" in copied2
