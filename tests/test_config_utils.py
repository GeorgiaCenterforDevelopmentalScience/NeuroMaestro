"""
test_config_utils.py

Tests for pipeline/utils/config_utils.py

Covers:
- find_task_config_by_name            basic lookup
- find_task_config_by_name_with_project  merge priority (project overrides global)
- get_all_task_names / get_tasks_by_suffix
- expand_task_names
- clean_all_only
- CLI argument flow: --task-prep cards  →  cards_preprocess  (integration-level unit test)
"""

import pytest
from unittest.mock import patch, MagicMock
from tests.conftest import MOCK_CONFIG, MOCK_PROJECT_CONFIG


# ---------------------------------------------------------------------------
# Helpers: patch the module-level `config` variable so tests are hermetic
# ---------------------------------------------------------------------------

CONFIG_PATH = "neuro_pipeline.pipeline.utils.config_utils.config"


# ===========================================================================
# find_task_config_by_name
# ===========================================================================

class TestFindTaskConfigByName:

    def test_finds_task_in_prep_section(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import find_task_config_by_name
            result = find_task_config_by_name("unzip")
        assert result is not None
        assert result["name"] == "unzip"
        assert result["profile"] == "standard"

    def test_finds_task_in_task_section(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import find_task_config_by_name
            result = find_task_config_by_name("cards_preprocess")
        assert result is not None
        assert result["name"] == "cards_preprocess"
        assert "afni_cards_preprocessing.sh" in result["scripts"]

    def test_finds_task_in_qc_section(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import find_task_config_by_name
            result = find_task_config_by_name("mriqc_preprocess")
        assert result is not None
        assert result["name"] == "mriqc_preprocess"

    def test_returns_none_for_unknown_task(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import find_task_config_by_name
            result = find_task_config_by_name("nonexistent_task")
        assert result is None

    def test_returns_none_when_config_empty(self):
        with patch(CONFIG_PATH, {}):
            from neuro_pipeline.pipeline.utils.config_utils import find_task_config_by_name
            result = find_task_config_by_name("cards_preprocess")
        assert result is None


# ===========================================================================
# find_task_config_by_name_with_project  — merge logic
# ===========================================================================

class TestFindTaskConfigByNameWithProject:

    def test_returns_global_config_when_no_project(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import find_task_config_by_name_with_project
            result = find_task_config_by_name_with_project("cards_preprocess", project_config=None)
        assert result is not None
        assert result["name"] == "cards_preprocess"
        # Project-specific keys should NOT be present
        assert "remove_TRs" not in result

    def test_project_config_overrides_global_fields(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import find_task_config_by_name_with_project
            result = find_task_config_by_name_with_project("cards_preprocess", MOCK_PROJECT_CONFIG)
        assert result is not None
        # Project-specific key is merged in
        assert result["remove_TRs"] == 2
        assert result["blur_size"] == 4.0
        assert result["censor_motion"] == "0.3"

    def test_global_fields_preserved_when_project_does_not_override(self):
        """Fields only in global config must survive the merge."""
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import find_task_config_by_name_with_project
            result = find_task_config_by_name_with_project("cards_preprocess", MOCK_PROJECT_CONFIG)
        assert result["profile"] == "standard"
        assert "afni_cards_preprocessing.sh" in result["scripts"]

    def test_project_config_adds_container_field(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import find_task_config_by_name_with_project
            result = find_task_config_by_name_with_project("recon", MOCK_PROJECT_CONFIG)
        assert result["container"] == "dcm2bids_3.2.0.sif"

    def test_returns_none_for_unknown_task(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import find_task_config_by_name_with_project
            result = find_task_config_by_name_with_project("ghost_task", MOCK_PROJECT_CONFIG)
        assert result is None


# ===========================================================================
# get_all_task_names / get_tasks_by_suffix
# ===========================================================================

class TestTaskNameHelpers:

    def test_get_all_task_names_all_sections(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import get_all_task_names
            names = get_all_task_names()
        assert "cards_preprocess" in names
        assert "kidvid_preprocess" in names
        assert "unzip" in names
        assert "recon" in names
        assert "mriqc_preprocess" in names

    def test_get_all_task_names_preserves_config_order(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import get_all_task_names
            names = get_all_task_names()
        assert names.index("unzip") < names.index("recon")
        assert names.index("recon") < names.index("rest_preprocess")

    def test_get_all_task_names_single_section(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import get_all_task_names
            names = get_all_task_names("qc")
        assert "mriqc_preprocess" in names
        assert "mriqc_post" in names
        assert "unzip" not in names

    def test_get_all_task_names_cards_section(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import get_all_task_names
            names = get_all_task_names("cards")
        assert names == ["cards_preprocess", "cards_postprocess"]

    def test_get_all_task_names_unknown_category_returns_empty(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import get_all_task_names
            names = get_all_task_names("nonexistent_category")
        assert names == []

    def test_get_tasks_by_suffix_preprocess(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import get_tasks_by_suffix
            names = get_tasks_by_suffix("_preprocess")
        assert "cards_preprocess" in names
        assert "kidvid_preprocess" in names

    def test_get_tasks_by_suffix_postprocess(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import get_tasks_by_suffix
            names = get_tasks_by_suffix("_postprocess")
        assert names == ["cards_postprocess"]

    def test_get_tasks_by_suffix_no_match(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import get_tasks_by_suffix
            names = get_tasks_by_suffix("_nosuchsuffix")
        assert names == []


# ===========================================================================
# expand_task_names
# ===========================================================================

class TestExpandTaskNames:

    def test_adds_preprocess_suffix(self):
        from neuro_pipeline.pipeline.utils.config_utils import expand_task_names
        result = expand_task_names(["cards", "kidvid"], "_preprocess")
        assert result == ["cards_preprocess", "kidvid_preprocess"]

    def test_adds_postprocess_suffix(self):
        from neuro_pipeline.pipeline.utils.config_utils import expand_task_names
        result = expand_task_names(["cards"], "_postprocess")
        assert result == ["cards_postprocess"]

    def test_empty_list(self):
        from neuro_pipeline.pipeline.utils.config_utils import expand_task_names
        assert expand_task_names([], "_preprocess") == []


# ===========================================================================
# clean_all_only
# ===========================================================================

class TestCleanAllOnly:

    def test_passthrough_when_no_all(self):
        from neuro_pipeline.pipeline.utils.config_utils import clean_all_only
        result = clean_all_only(["cards", "kidvid"], "task_prep")
        assert result == ["cards", "kidvid"]

    def test_passthrough_when_only_all(self):
        from neuro_pipeline.pipeline.utils.config_utils import clean_all_only
        result = clean_all_only(["all"], "task_prep")
        assert result == ["all"]

    def test_strips_others_when_all_mixed_in(self):
        from neuro_pipeline.pipeline.utils.config_utils import clean_all_only
        result = clean_all_only(["all", "cards"], "task_prep")
        assert result == ["all"]

    def test_strips_others_order_independent(self):
        from neuro_pipeline.pipeline.utils.config_utils import clean_all_only
        result = clean_all_only(["cards", "all", "kidvid"], "task_prep")
        assert result == ["all"]


# ===========================================================================
# CLI flow: --task-prep cards  →  cards_preprocess
# (simulates what core.run() does before calling DAGExecutor)
# ===========================================================================

class TestCLITaskPrepFlow:
    """
    Verify that the string 'cards' entered via --task-prep
    becomes 'cards_preprocess' after parsing, and that it
    successfully validates against the config.
    """

    def test_cards_becomes_cards_preprocess(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import expand_task_names, validate_task_name

            raw_input = ["cards"]  # what the user types
            parsed = expand_task_names(raw_input, "_preprocess")

            assert parsed == ["cards_preprocess"]
            assert validate_task_name("cards_preprocess") is True

    def test_kidvid_becomes_kidvid_preprocess(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import expand_task_names, validate_task_name

            parsed = expand_task_names(["kidvid"], "_preprocess")
            assert parsed == ["kidvid_preprocess"]
            assert validate_task_name("kidvid_preprocess") is True

    def test_unknown_task_fails_validation(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import expand_task_names, validate_task_name

            parsed = expand_task_names(["ghost"], "_preprocess")
            # ghost_preprocess does not exist in config
            assert validate_task_name(parsed[0]) is False

    def test_comma_separated_input_expands_correctly(self):
        """Simulate --task-prep cards,kidvid (single option, comma-separated)."""
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import expand_task_names

            raw = "cards,kidvid"
            items = [t.strip() for t in raw.split(",") if t.strip()]
            parsed = expand_task_names(items, "_preprocess")

            assert "cards_preprocess" in parsed
            assert "kidvid_preprocess" in parsed
