"""Focused tests for the deterministic Phase 1 SVG renderer."""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pandas as pd
import pytest
import visualize_phase1 as V


def sample_tables() -> V.Phase1Tables:
    municipalities = pd.DataFrame(
        [
            {
                "municipality_id": "R1",
                "name": "甲市",
                "prefecture": "広島県",
                "latitude": 34.40,
                "longitude": 132.45,
            },
            {
                "municipality_id": "R2",
                "name": "乙市",
                "prefecture": "広島県",
                "latitude": 34.25,
                "longitude": 132.57,
            },
            {
                "municipality_id": "R3",
                "name": "丙市",
                "prefecture": "山口県",
                "latitude": 34.16,
                "longitude": 132.22,
            },
            {
                "municipality_id": "R4",
                "name": "丁市",
                "prefecture": "岡山県",
                "latitude": 34.66,
                "longitude": 133.92,
            },
        ]
    )
    flow_edges = pd.DataFrame(
        [
            {"source": "R1", "target": "R2", "total": 100, "year": 2020},
            {"source": "R2", "target": "R1", "total": 40, "year": 2020},
            {"source": "R1", "target": "R3", "total": 80, "year": 2020},
            {"source": "R3", "target": "R1", "total": 30, "year": 2020},
            {"source": "R4", "target": "R1", "total": 20, "year": 2020},
            {"source": "R1", "target": "R1", "total": 9_999, "year": 2020},
        ]
    )
    airports = pd.DataFrame(
        [
            {
                "airport_id": "A1",
                "name": "西空港",
                "latitude": 34.00,
                "longitude": 132.00,
            },
            {
                "airport_id": "A2",
                "name": "東空港",
                "latitude": 34.75,
                "longitude": 133.80,
            },
        ]
    )
    airport_access = pd.DataFrame(
        [
            {"source": "R1", "target": "A1", "distance_km": 42.0, "rank": 1},
            {"source": "R2", "target": "A1", "distance_km": 51.0, "rank": 1},
            {"source": "R3", "target": "A1", "distance_km": 19.0, "rank": 1},
            {"source": "R4", "target": "A2", "distance_km": 22.0, "rank": 1},
        ]
    )
    return V.Phase1Tables(municipalities, flow_edges, airports, airport_access)


def test_builds_four_valid_self_contained_svgs(tmp_path):
    paths = V.build_visualizations(sample_tables(), tmp_path, top_flows=4, top_ranking=3)

    assert [path.name for path in paths] == [
        "administrative_membership.svg",
        "top_intercity_flows.svg",
        "mobility_nearest_airport.svg",
        "bidirectional_flow_ranking.svg",
    ]
    for path in paths:
        root = ET.parse(path).getroot()
        assert root.tag == "{http://www.w3.org/2000/svg}svg"
        contents = path.read_text(encoding="utf-8")
        assert "<script" not in contents
        assert "nan" not in contents.lower()
        assert "infinity" not in contents.lower()


def test_flow_svg_exposes_quantitative_and_non_color_encodings(tmp_path):
    tables = sample_tables()
    path = tmp_path / "flows.svg"
    V.render_top_intercity_flows(
        tables.municipalities,
        tables.flow_edges,
        path,
        top_n=4,
    )

    contents = path.read_text(encoding="utf-8")
    assert "2020年" in contents
    assert "就業者＋通学者、人" in contents
    assert "e-Stat" in contents
    assert "跨県" in contents
    assert 'stroke-dasharray="9 5"' in contents
    assert "marker-end=" in contents
    assert "9,999" not in contents  # Self-flow is excluded before the ranking.


def test_bidirectional_ranking_sums_both_directions_and_excludes_self():
    ranking = V._bidirectional_pairs(sample_tables().flow_edges)

    first = ranking.iloc[0]
    assert {first["a"], first["b"]} == {"R1", "R2"}
    assert first["flow"] == pytest.approx(140)
    assert not (ranking["a"] == ranking["b"]).any()


def test_airport_svg_uses_rank_one_access_and_distance_labels(tmp_path):
    tables = sample_tables()
    path = tmp_path / "airport.svg"
    V.render_mobility_and_airports(
        tables.municipalities,
        tables.flow_edges,
        tables.airports,
        tables.airport_access,
        path,
        top_flows=3,
    )

    contents = path.read_text(encoding="utf-8")
    assert "最寄り空港" in contents
    assert "西空港" in contents
    assert "東空港" in contents
    assert 'stroke-dasharray="5 5"' in contents
    assert "国土交通省" in contents


def test_airport_rank_one_must_be_the_distance_minimum():
    access = pd.DataFrame(
        [
            {"source": "R1", "target": "A1", "distance_km": 40, "rank": 1},
            {"source": "R1", "target": "A2", "distance_km": 20, "rank": 2},
        ]
    )
    with pytest.raises(ValueError, match="rank=1 is not the minimum distance"):
        V._nearest_access(access)


def test_missing_real_parquet_files_fail_clearly(tmp_path):
    with pytest.raises(FileNotFoundError, match="Run the real-data preparation pipeline first"):
        V.load_phase1_data(tmp_path)


def test_missing_flow_measure_is_rejected():
    tables = sample_tables()
    broken = V.Phase1Tables(
        tables.municipalities,
        tables.flow_edges.drop(columns="total"),
        tables.airports,
        tables.airport_access,
    )
    with pytest.raises(ValueError, match="commuters and students"):
        V.build_visualizations(broken, "not-written")
