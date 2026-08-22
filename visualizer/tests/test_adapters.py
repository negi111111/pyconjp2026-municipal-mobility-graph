"""Tests for visualizer adapters without starting Streamlit."""

from __future__ import annotations

from adapters import PhaseRepository


def test_phase_summaries_match_processed_graph_facts():
    phase1 = PhaseRepository("phase1").summary()
    phase2 = PhaseRepository("phase2").summary()
    phase3 = PhaseRepository("phase3").summary()
    assert phase1["search_universe_count"] == 20
    assert phase2["analysis_universe_count"] == 1719
    assert phase2["search_universe_count"] == 100
    assert phase3["graph_edge_count"] == phase2["graph_edge_count"]
    assert "climate.january_mean_temperature" in phase3["features"]


def test_graph_view_uses_real_relations_and_search_subset():
    repository = PhaseRepository("phase3")
    nodes, edges = repository.graph_view(
        relation_filter={"COMMUTES_TO", "STUDIES_IN"},
        node_type_filter={"Municipality"},
        max_nodes=100,
        top_edges=50,
    )
    assert len(nodes) <= 100
    assert len(edges) <= 50
    assert all(edge["relation"] in {"COMMUTES_TO", "STUDIES_IN"} for edge in edges)


def test_graph_view_includes_real_administrative_and_airport_neighbors():
    nodes, edges = PhaseRepository("phase1").graph_view(
        relation_filter={"IS_IN", "ACCESS_TO"},
        node_type_filter={"Municipality", "Prefecture", "Airport"},
        max_nodes=100,
        top_edges=100,
    )
    assert any(node["node_type"] == "Prefecture" for node in nodes)
    assert any(node["node_type"] == "Airport" for node in nodes)
    assert {edge["relation"] for edge in edges} <= {"IS_IN", "ACCESS_TO"}


def test_graph_view_region_filter_reduces_municipalities():
    repository = PhaseRepository("phase3")
    nodes, _ = repository.graph_view(
        relation_filter={"IS_IN", "COMMUTES_TO", "STUDIES_IN", "ACCESS_TO"},
        node_type_filter={"Municipality", "Prefecture", "Airport"},
        selected_id="R01100",
        region="北海道",
        max_nodes=100,
        top_edges=100,
    )
    assert 0 < sum(node["node_type"] == "Municipality" for node in nodes) <= 6


def test_phase3_inspector_keeps_feature_store_separate_from_graph():
    result = PhaseRepository("phase3").inspector("R40130")
    assert result["basic"]["node_type"] == "Municipality"
    assert result["phase3_features"]
    assert result["weather_station"]
    assert result["shinkansen"]


def test_phase1_inspector_hides_phase3_only_tables():
    result = PhaseRepository("phase1").inspector("R34100")
    assert result["basic"]["node_type"] == "Municipality"
    assert len(result["ssdse"]) == 125
    assert result["phase3_features"] == []
    assert result["weather_station"] == {}
    assert result["shinkansen"] == {}


def test_non_municipality_nodes_have_connection_details():
    repository = PhaseRepository("phase1")
    graph = repository.load_graph()
    prefecture = next(
        node
        for node, data in graph.nodes(data=True)
        if data.get("node_type") == "Prefecture"
    )
    airport = next(
        node
        for node, data in graph.nodes(data=True)
        if data.get("node_type") == "Airport" and graph.degree(node) > 0
    )
    assert repository.inspector(prefecture)["connections"]
    assert repository.inspector(airport)["connections"]
