"""
test_dag_visualization.py

Tests for build_dag_elements() in analysis_control.py.
Verifies that the correct Cytoscape nodes and edges are generated
for different pipeline selections.
"""

import pytest
from neuromaestro.interface.components.analysis_control import build_dag_elements


def node_ids(elements):
    return {e["data"]["id"] for e in elements if "source" not in e["data"]}

def edge_pairs(elements):
    return {(e["data"]["source"], e["data"]["target"])
            for e in elements if "source" in e["data"]}


class TestBuildDagElementsEmpty:

    def test_no_selection_returns_empty(self):
        elements = build_dag_elements(
            prep_option="none", intermed_value=[],
            bids_prep=[], bids_post=[],
            staged_prep=[], staged_post=[],
            mriqc_option="none",
        )
        assert elements == []


class TestPrepNodes:

    def test_unzip_only(self):
        elements = build_dag_elements(
            "unzip", [], [], [], [], [], "none"
        )
        assert "unzip" in node_ids(elements)
        assert "recon" not in node_ids(elements)

    def test_recon_only(self):
        elements = build_dag_elements(
            "recon", [], [], [], [], [], "none"
        )
        assert "recon" in node_ids(elements)
        assert "unzip" not in node_ids(elements)

    def test_unzip_recon_creates_edge(self):
        elements = build_dag_elements(
            "unzip_recon", [], [], [], [], [], "none"
        )
        ids = node_ids(elements)
        assert "unzip" in ids
        assert "recon" in ids
        assert ("unzip", "recon") in edge_pairs(elements)


class TestIntermedNodes:

    def test_intermed_node_created(self):
        elements = build_dag_elements(
            "recon", ["volume"], [], [], [], [], "none"
        )
        assert "intermed" in node_ids(elements)

    def test_recon_to_intermed_edge(self):
        elements = build_dag_elements(
            "recon", ["volume"], [], [], [], [], "none"
        )
        assert ("recon", "intermed") in edge_pairs(elements)

    def test_no_intermed_node_when_none(self):
        elements = build_dag_elements(
            "recon", [], [], [], [], [], "none"
        )
        assert "intermed" not in node_ids(elements)


class TestBIDSPipelines:

    def test_bids_prep_node_created(self):
        elements = build_dag_elements(
            "recon", [], ["rest"], [], [], [], "none"
        )
        assert "bids_prep_rest" in node_ids(elements)

    def test_recon_to_bids_prep_edge(self):
        elements = build_dag_elements(
            "recon", [], ["rest"], [], [], [], "none"
        )
        assert ("recon", "bids_prep_rest") in edge_pairs(elements)

    def test_bids_post_node_created(self):
        elements = build_dag_elements(
            "recon", [], [], ["rest"], [], [], "none"
        )
        assert "bids_post_rest" in node_ids(elements)

    def test_bids_prep_to_post_edge_when_both_selected(self):
        elements = build_dag_elements(
            "recon", [], ["rest"], ["rest"], [], [], "none"
        )
        assert ("bids_prep_rest", "bids_post_rest") in edge_pairs(elements)

    def test_bids_post_no_prep_edge_when_prep_not_selected(self):
        elements = build_dag_elements(
            "recon", [], [], ["rest"], [], [], "none"
        )
        assert ("bids_prep_rest", "bids_post_rest") not in edge_pairs(elements)


class TestStagedPipelines:

    def test_staged_prep_node_created(self):
        elements = build_dag_elements(
            "none", [], [], [], ["cards"], [], "none"
        )
        assert "staged_prep_cards" in node_ids(elements)

    def test_intermed_to_staged_prep_edge(self):
        elements = build_dag_elements(
            "recon", ["volume"], [], [], ["cards"], [], "none"
        )
        assert ("intermed", "staged_prep_cards") in edge_pairs(elements)

    def test_staged_prep_no_intermed_edge_when_intermed_absent(self):
        elements = build_dag_elements(
            "none", [], [], [], ["cards"], [], "none"
        )
        assert "intermed" not in node_ids(elements)
        assert all(e["data"].get("target") != "staged_prep_cards"
                   or e["data"].get("source") != "intermed"
                   for e in elements if "source" in e["data"])

    def test_staged_prep_to_post_edge(self):
        elements = build_dag_elements(
            "none", [], [], [], ["cards"], ["cards"], "none"
        )
        assert ("staged_prep_cards", "staged_post_cards") in edge_pairs(elements)


class TestMRIQCNodes:

    def test_mriqc_individual_node(self):
        elements = build_dag_elements(
            "recon", [], [], [], [], [], "individual"
        )
        assert "mriqc_indiv" in node_ids(elements)

    def test_recon_to_mriqc_individual_edge(self):
        elements = build_dag_elements(
            "recon", [], [], [], [], [], "individual"
        )
        assert ("recon", "mriqc_indiv") in edge_pairs(elements)

    def test_mriqc_group_only(self):
        elements = build_dag_elements(
            "recon", [], [], [], [], [], "group"
        )
        ids = node_ids(elements)
        assert "mriqc_group" in ids
        assert "mriqc_indiv" not in ids

    def test_mriqc_all_creates_chain(self):
        elements = build_dag_elements(
            "recon", [], [], [], [], [], "all"
        )
        ids = node_ids(elements)
        assert "mriqc_indiv" in ids
        assert "mriqc_group" in ids
        assert ("mriqc_indiv", "mriqc_group") in edge_pairs(elements)


class TestMultipleIntermedVisualization:
    """With multiple intermed tasks the visualization still renders a single
    'intermed' node (the bubble label lists all selected tasks)."""

    def test_single_intermed_node_for_two_tasks(self):
        elements = build_dag_elements(
            "recon", ["volume", "bfc"], [], [], [], [], "none"
        )
        ids = node_ids(elements)
        assert "intermed" in ids
        assert len([e for e in elements if "id" in e["data"] and e["data"]["id"] == "intermed"]) == 1

    def test_recon_to_intermed_edge_with_two_tasks(self):
        elements = build_dag_elements(
            "recon", ["volume", "bfc"], [], [], [], [], "none"
        )
        assert ("recon", "intermed") in edge_pairs(elements)

    def test_intermed_to_staged_prep_edge_with_two_tasks(self):
        elements = build_dag_elements(
            "recon", ["volume", "bfc"], [], [], ["cards"], [], "none"
        )
        assert ("intermed", "staged_prep_cards") in edge_pairs(elements)

    def test_bids_pipeline_has_no_intermed_edge(self):
        elements = build_dag_elements(
            "recon", ["volume", "bfc"], ["rest"], [], [], [], "none"
        )
        assert ("intermed", "bids_prep_rest") not in edge_pairs(elements)
        assert ("recon", "bids_prep_rest") in edge_pairs(elements)

    def test_intermed_label_contains_both_task_names(self):
        elements = build_dag_elements(
            "recon", ["volume", "bfc"], [], [], [], [], "none"
        )
        intermed_node = next(
            e for e in elements
            if "id" in e["data"] and e["data"]["id"] == "intermed"
        )
        assert "volume" in intermed_node["data"]["label"]
        assert "bfc" in intermed_node["data"]["label"]


class TestFullPipelineSelection:

    def test_full_pipeline_has_all_expected_nodes(self):
        elements = build_dag_elements(
            prep_option="unzip_recon",
            intermed_value=["volume"],
            bids_prep=["rest"],
            bids_post=["rest"],
            staged_prep=["cards"],
            staged_post=["cards"],
            mriqc_option="all",
        )
        ids = node_ids(elements)
        assert "unzip" in ids
        assert "recon" in ids
        assert "intermed" in ids
        assert "bids_prep_rest" in ids
        assert "bids_post_rest" in ids
        assert "staged_prep_cards" in ids
        assert "staged_post_cards" in ids
        assert "mriqc_indiv" in ids
        assert "mriqc_group" in ids

    def test_full_pipeline_edges_are_exactly_these(self):
        elements = build_dag_elements(
            "unzip_recon", ["volume"],
            ["rest"], ["rest"], ["cards"], ["cards"], "all",
        )
        assert edge_pairs(elements) == {
            ("unzip", "recon"),
            ("recon", "intermed"),
            ("recon", "bids_prep_rest"),
            ("bids_prep_rest", "bids_post_rest"),
            ("intermed", "staged_prep_cards"),
            ("staged_prep_cards", "staged_post_cards"),
            ("recon", "mriqc_indiv"),
            ("mriqc_indiv", "mriqc_group"),
        }
