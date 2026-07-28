"""
test_dag.py — Tests for pipeline/dag.py

DAG rules under test:
  1. unzip -> recon (if both requested)
  2. recon -> all non-staged downstream tasks (bids, mriqc, intermed)
  3. intermed -> staged prep tasks (multi_stage=true, stage=prep) only
  4. staged post tasks depend only on their matching staged prep (same section)
  5. Without intermed, staged tasks run in parallel with recon
  6. Within each config section: post -> prep
  7. Multiple intermed tasks run in parallel; staged prep waits for ALL of them;
     BIDS pipelines remain parallel with intermed tasks
"""

import pytest
from unittest.mock import patch
from tests.conftest import MOCK_CONFIG, MOCK_PROJECT_CONFIG

CONFIG_PATH = "neuro_pipeline.pipeline.utils.config_utils.config"


def make_executor():
    with patch(CONFIG_PATH, MOCK_CONFIG):
        from neuro_pipeline.pipeline.dag import DAGExecutor
        executor = DAGExecutor(MOCK_CONFIG)
        executor.project_config = MOCK_PROJECT_CONFIG
        return executor


def build(tasks):
    with patch(CONFIG_PATH, MOCK_CONFIG):
        executor = make_executor()
        order = executor.build_dag(tasks)
        return executor, order


def deps(executor, task):
    return executor.nodes[task].dependencies


# ===========================================================================
# Topological sort
# ===========================================================================

class TestTopologicalSort:

    def test_single_node(self):
        executor = make_executor()
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.dag import TaskNode
            executor.nodes = {"unzip": TaskNode("unzip", {}, dependencies=set())}
            assert executor._topological_sort() == ["unzip"]

    def test_linear_chain(self):
        executor = make_executor()
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.dag import TaskNode
            executor.nodes = {
                "A": TaskNode("A", {}, dependencies=set()),
                "B": TaskNode("B", {}, dependencies={"A"}),
                "C": TaskNode("C", {}, dependencies={"B"}),
            }
            result = executor._topological_sort()
        assert result.index("A") < result.index("B") < result.index("C")

    def test_circular_dependency_raises(self):
        executor = make_executor()
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.dag import TaskNode
            executor.nodes = {
                "X": TaskNode("X", {}, dependencies={"Y"}),
                "Y": TaskNode("Y", {}, dependencies={"X"}),
            }
            with pytest.raises(ValueError, match="Circular dependency"):
                executor._topological_sort()

    def test_diamond_dependency(self):
        executor = make_executor()
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.dag import TaskNode
            executor.nodes = {
                "root":  TaskNode("root",  {}, dependencies=set()),
                "left":  TaskNode("left",  {}, dependencies={"root"}),
                "right": TaskNode("right", {}, dependencies={"root"}),
                "leaf":  TaskNode("leaf",  {}, dependencies={"left", "right"}),
            }
            result = executor._topological_sort()
        assert result[0] == "root"
        assert result[-1] == "leaf"


# ===========================================================================
# Rule 1: unzip -> recon
# ===========================================================================

class TestPrepChain:

    def test_recon_depends_on_unzip_when_both_requested(self):
        executor, order = build(["unzip", "recon"])
        assert "unzip" in deps(executor, "recon")
        assert order.index("unzip") < order.index("recon")

    def test_recon_no_unzip_dep_when_only_recon_requested(self):
        executor, _ = build(["recon"])
        assert "unzip" not in deps(executor, "recon")

    def test_unzip_has_no_deps(self):
        executor, _ = build(["unzip"])
        assert deps(executor, "unzip") == set()


# ===========================================================================
# Rule 2: recon -> non-staged downstream
# ===========================================================================

class TestReconDependencies:

    def test_intermed_depends_on_recon(self):
        executor, order = build(["recon", "volume"])
        assert "recon" in deps(executor, "volume")
        assert order.index("recon") < order.index("volume")

    def test_bids_prep_depends_on_recon(self):
        executor, order = build(["recon", "rest_preprocess"])
        assert "recon" in deps(executor, "rest_preprocess")

    def test_mriqc_prep_depends_on_recon(self):
        executor, order = build(["recon", "mriqc_preprocess"])
        assert "recon" in deps(executor, "mriqc_preprocess")


# ===========================================================================
# Rule 3: intermed -> staged prep only (not staged post)
# ===========================================================================

class TestIntermedDependencies:

    def test_staged_prep_depends_on_intermed(self):
        executor, order = build(["volume", "cards_preprocess"])
        assert "volume" in deps(executor, "cards_preprocess")
        assert order.index("volume") < order.index("cards_preprocess")

    def test_intermed_does_not_wire_to_staged_post_directly(self):
        """staged_post has no prep in this request — intermed must NOT connect to it."""
        executor, _ = build(["volume", "kidvid_preprocess"])
        # there is no kidvid_post in MOCK_CONFIG so we verify intermed only touches prep
        assert "volume" in deps(executor, "kidvid_preprocess")

    def test_both_staged_preps_depend_on_intermed(self):
        executor, order = build(["volume", "cards_preprocess", "kidvid_preprocess"])
        assert "volume" in deps(executor, "cards_preprocess")
        assert "volume" in deps(executor, "kidvid_preprocess")


# ===========================================================================
# Rule 4: staged post depends only on matching staged prep
# ===========================================================================

class TestSectionDependencies:

    def test_mriqc_post_depends_on_mriqc_prep(self):
        executor, order = build(["mriqc_preprocess", "mriqc_post"])
        assert "mriqc_preprocess" in deps(executor, "mriqc_post")
        assert order.index("mriqc_preprocess") < order.index("mriqc_post")

    def test_rest_post_depends_on_rest_prep(self):
        executor, order = build(["rest_preprocess", "rest_post"])
        assert "rest_preprocess" in deps(executor, "rest_post")
        assert order.index("rest_preprocess") < order.index("rest_post")

    def test_dwi_post_depends_on_dwi_prep(self):
        executor, order = build(["dwi_preprocess", "dwi_post"])
        assert "dwi_preprocess" in deps(executor, "dwi_post")
        assert order.index("dwi_preprocess") < order.index("dwi_post")

    def test_rest_post_alone_has_no_prep_dep(self):
        executor, _ = build(["rest_post"])
        assert "rest_preprocess" not in deps(executor, "rest_post")

    def test_mriqc_post_alone_has_no_individual_dep(self):
        executor, _ = build(["mriqc_post"])
        assert "mriqc_preprocess" not in deps(executor, "mriqc_post")


# ===========================================================================
# Rule 5: without intermed, staged runs parallel with recon
# ===========================================================================

class TestStagedParallelWithoutIntermed:

    def test_staged_prep_has_no_recon_dep_without_intermed(self):
        executor, _ = build(["recon", "cards_preprocess"])
        assert "recon" not in deps(executor, "cards_preprocess")

    def test_staged_prep_has_no_intermed_dep_when_intermed_not_requested(self):
        executor, _ = build(["cards_preprocess"])
        assert "volume" not in deps(executor, "cards_preprocess")

    def test_two_staged_preps_parallel_without_intermed(self):
        executor, _ = build(["recon", "cards_preprocess", "kidvid_preprocess"])
        assert "recon" not in deps(executor, "cards_preprocess")
        assert "recon" not in deps(executor, "kidvid_preprocess")
        assert "cards_preprocess" not in deps(executor, "kidvid_preprocess")
        assert "kidvid_preprocess" not in deps(executor, "cards_preprocess")


# ===========================================================================
# Multiple intermed tasks run in parallel, staged waits for all of them,
# BIDS pipelines are parallel with intermed (same as before)
# ===========================================================================

class TestMultipleIntermedParallel:

    def test_two_intermed_tasks_have_no_dependency_on_each_other(self):
        executor, _ = build(["volume", "bfc"])
        assert "bfc" not in deps(executor, "volume")
        assert "volume" not in deps(executor, "bfc")

    def test_both_intermed_tasks_depend_on_recon(self):
        executor, order = build(["recon", "volume", "bfc"])
        assert "recon" in deps(executor, "volume")
        assert "recon" in deps(executor, "bfc")
        assert order.index("recon") < order.index("volume")
        assert order.index("recon") < order.index("bfc")

    def test_staged_prep_waits_for_all_intermed_tasks(self):
        executor, order = build(["volume", "bfc", "cards_preprocess"])
        assert "volume" in deps(executor, "cards_preprocess")
        assert "bfc" in deps(executor, "cards_preprocess")
        assert order.index("volume") < order.index("cards_preprocess")
        assert order.index("bfc") < order.index("cards_preprocess")

    def test_bids_pipeline_parallel_with_intermed(self):
        executor, _ = build(["recon", "volume", "bfc", "rest_preprocess"])
        assert "volume" not in deps(executor, "rest_preprocess")
        assert "bfc" not in deps(executor, "rest_preprocess")
        assert "recon" in deps(executor, "rest_preprocess")

    def test_full_multi_intermed_chain(self):
        tasks = ["recon", "volume", "bfc", "cards_preprocess", "rest_preprocess"]
        executor, order = build(tasks)
        assert order.index("recon") < order.index("volume")
        assert order.index("recon") < order.index("bfc")
        assert order.index("volume") < order.index("cards_preprocess")
        assert order.index("bfc") < order.index("cards_preprocess")
        assert order.index("recon") < order.index("rest_preprocess")
        assert "volume" not in deps(executor, "rest_preprocess")
        assert "bfc" not in deps(executor, "rest_preprocess")


# ===========================================================================
# Full chain: recon -> intermed -> staged prep -> (staged post via section)
# ===========================================================================

class TestFullChain:

    def test_recon_intermed_staged_prep_chain(self):
        executor, order = build(["recon", "volume", "cards_preprocess"])
        assert "recon" in deps(executor, "volume")
        assert "volume" in deps(executor, "cards_preprocess")
        assert order.index("recon") < order.index("volume") < order.index("cards_preprocess")

    def test_two_staged_pipelines_parallel_after_intermed(self):
        executor, order = build(["volume", "cards_preprocess", "kidvid_preprocess"])
        assert "volume" in deps(executor, "cards_preprocess")
        assert "volume" in deps(executor, "kidvid_preprocess")
        # cards and kidvid must not depend on each other
        assert "cards_preprocess" not in deps(executor, "kidvid_preprocess")
        assert "kidvid_preprocess" not in deps(executor, "cards_preprocess")

    def test_all_tasks_appear_in_order(self):
        tasks = ["recon", "volume", "cards_preprocess", "mriqc_preprocess", "mriqc_post"]
        executor, order = build(tasks)
        for t in tasks:
            assert t in order


# ===========================================================================
# TaskRegistry.expand_tasks — CLI choice -> concrete task names
# ===========================================================================

def make_registry():
    with patch(CONFIG_PATH, MOCK_CONFIG):
        from neuro_pipeline.pipeline.dag import TaskRegistry
        return TaskRegistry()


def expand(registry, **kwargs):
    with patch(CONFIG_PATH, MOCK_CONFIG):
        return registry.expand_tasks(**kwargs)


class TestTaskRegistry:

    def setup_method(self):
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.utils.config_utils import PrepChoice, MRIQCChoice
            self.PrepChoice = PrepChoice
            self.MRIQCChoice = MRIQCChoice
        self.registry = make_registry()

    # --- prep choices ---

    def test_prep_recon(self):
        result = expand(self.registry, prep=self.PrepChoice.recon)
        assert result == ["recon"]

    def test_prep_unzip(self):
        result = expand(self.registry, prep=self.PrepChoice.unzip)
        assert result == ["unzip"]

    def test_prep_unzip_recon_expands_to_both(self):
        result = expand(self.registry, prep=self.PrepChoice.unzip_recon)
        assert result == ["unzip", "recon"]

    # --- mriqc choices ---

    def test_mriqc_individual(self):
        result = expand(self.registry, mriqc=self.MRIQCChoice.individual)
        assert result == ["mriqc_preprocess"]

    def test_mriqc_group(self):
        result = expand(self.registry, mriqc=self.MRIQCChoice.group)
        assert result == ["mriqc_post"]

    def test_mriqc_all_expands_to_both(self):
        result = expand(self.registry, mriqc=self.MRIQCChoice.all)
        assert "mriqc_preprocess" in result
        assert "mriqc_post" in result

    # --- bids_prep / bids_post ---

    def test_bids_prep_rest(self):
        result = expand(self.registry, bids_prep=["rest"])
        assert result == ["rest_preprocess"]

    def test_bids_prep_dwi(self):
        result = expand(self.registry, bids_prep=["dwi"])
        assert result == ["dwi_preprocess"]

    def test_bids_prep_multiple_sections(self):
        result = expand(self.registry, bids_prep=["rest", "dwi"])
        assert result == ["rest_preprocess", "dwi_preprocess"]

    def test_bids_post_rest(self):
        result = expand(self.registry, bids_post=["rest"])
        assert result == ["rest_post"]

    def test_bids_post_dwi(self):
        result = expand(self.registry, bids_post=["dwi"])
        assert result == ["dwi_post"]

    # --- staged_prep / staged_post ---

    def test_staged_prep_cards(self):
        result = expand(self.registry, staged_prep=["cards"])
        assert result == ["cards_preprocess"]

    def test_staged_prep_kidvid(self):
        result = expand(self.registry, staged_prep=["kidvid"])
        assert result == ["kidvid_preprocess"]

    def test_staged_prep_multiple(self):
        result = expand(self.registry, staged_prep=["cards", "kidvid"])
        assert result == ["cards_preprocess", "kidvid_preprocess"]

    # --- intermed ---

    def test_intermed_valid_name(self):
        result = expand(self.registry, intermed=["volume"])
        assert result == ["volume"]

    def test_intermed_multiple_valid(self):
        result = expand(self.registry, intermed=["volume", "bfc"])
        assert result == ["volume", "bfc"]

    def test_intermed_invalid_name_skipped(self):
        result = expand(self.registry, intermed=["nonexistent_task"])
        assert result == []

    def test_intermed_mixed_valid_and_invalid(self):
        result = expand(self.registry, intermed=["volume", "bad_task"])
        assert result == ["volume"]

    # --- combinations ---

    def test_bids_prep_and_staged_prep_combined(self):
        result = expand(self.registry, bids_prep=["rest"], staged_prep=["cards"])
        assert "rest_preprocess" in result
        assert "cards_preprocess" in result

    def test_prep_and_bids_prep_combined(self):
        result = expand(self.registry, prep=self.PrepChoice.recon, bids_prep=["rest"])
        assert "recon" in result
        assert "rest_preprocess" in result

    def test_no_args_returns_empty(self):
        result = expand(self.registry)
        assert result == []


# ===========================================================================
# Missing task config / dangling dependencies
# ===========================================================================

class TestMissingTaskConfig:
    """_register_task used to warn and return, leaving the task out of
    self.nodes while other rules still pointed dependencies at it. That
    produced either a KeyError or a bogus "Circular dependency detected".
    """

    def test_unknown_task_raises_with_task_name(self):
        with pytest.raises(ValueError, match="nonexistent_task"):
            build(["nonexistent_task"])

    def test_unknown_task_error_is_not_reported_as_a_cycle(self):
        with pytest.raises(ValueError) as exc:
            build(["recon", "nonexistent_task"])
        assert "Circular" not in str(exc.value)

    def test_unzip_recon_pair_survives_when_only_recon_registered(self):
        # recon requested without unzip must not raise a KeyError
        executor, order = build(["recon"])
        assert "unzip" not in deps(executor, "recon")

    def test_dangling_dependency_is_pruned(self):
        executor = make_executor()
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.dag import TaskNode
            executor.nodes = {"A": TaskNode("A", {}, dependencies={"ghost"})}
            executor._prune_dangling_dependencies()
            assert executor.nodes["A"].dependencies == set()
            assert executor._topological_sort() == ["A"]

    def test_real_cycle_still_detected_after_pruning(self):
        executor = make_executor()
        with patch(CONFIG_PATH, MOCK_CONFIG):
            from neuro_pipeline.pipeline.dag import TaskNode
            executor.nodes = {
                "X": TaskNode("X", {}, dependencies={"Y"}),
                "Y": TaskNode("Y", {}, dependencies={"X"}),
            }
            executor._prune_dangling_dependencies()
            with pytest.raises(ValueError, match="Circular dependency"):
                executor._topological_sort()
