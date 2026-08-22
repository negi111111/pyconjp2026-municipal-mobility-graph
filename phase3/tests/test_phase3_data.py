"""Regression checks for Phase 3 feature-store coverage and provenance."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"


def test_phase3_processing_report_adopts_only_complete_features():
    report = json.loads(
        (PROCESSED / "phase3_processing_report.json").read_text(encoding="utf-8")
    )
    assert report["phase"] == 3
    assert report["search_city_count"] == 100
    assert report["checks"] == {
        "climate_coverage": True,
        "shinkansen_coverage": True,
        "housing_adopted": False,
        "disaster_adopted": False,
        "nature_adopted": False,
    }
    assert report["coverage"]["climate"]["missing_value_count"] == 0
    assert report["coverage"]["weather_station_access"]["p95_km"] is not None
    assert report["coverage"]["shinkansen_access"]["source_station_catalog_count"] == 92


def test_environmental_metrics_preserve_feature_provenance():
    metrics = pd.read_parquet(PROCESSED / "environmental_metrics.parquet")
    required = {
        "municipality_id",
        "feature_name",
        "category",
        "value",
        "unit",
        "year",
        "period",
        "source_dataset",
        "source_url",
        "retrieved_at",
        "license",
        "redistribution",
        "geographic_granularity",
        "direction",
        "normalization",
        "missing_reason",
    }
    assert required <= set(metrics.columns)
    assert metrics["municipality_id"].nunique() == 100
    assert metrics["feature_name"].nunique() == 7
    assert metrics["value"].notna().all()
    assert metrics["source_url"].notna().all()
    assert metrics["license"].notna().all()
    assert metrics["redistribution"].notna().all()


def test_phase3_access_tables_cover_search_universe():
    weather = pd.read_parquet(PROCESSED / "weather_station_access.parquet")
    rail = pd.read_parquet(PROCESSED / "shinkansen_access.parquet")
    assert weather["municipality_id"].nunique() == 100
    assert rail["municipality_id"].nunique() == 100
    assert (weather["distance_km"] >= 0).all()
    assert (rail["distance_km"] >= 0).all()
    assert set(rail["station_in_municipality_status"]) == {"not_spatially_joined"}


def test_phase3_provenance_sources_are_adopted_and_gaps_are_explicit():
    sources = yaml.safe_load(
        (ROOT / "data" / "provenance" / "phase3_sources.yml").read_text(encoding="utf-8")
    )
    assert sources["phase"] == 3
    assert {item["dataset"] for item in sources["datasets"]} == {
        "JMA normal_surface",
        "MLIT National Land Numerical Information N02-20",
    }
    catalog = json.loads(
        (PROCESSED / "phase3_feature_catalog.json").read_text(encoding="utf-8")
    )
    assert catalog["housing_status"] == "not_adopted_coverage_unverified"
    assert catalog["disaster_status"] == "feasibility_deferred"
    assert catalog["nature_status"] == "feasibility_deferred"


def test_phase3_acceptance_html_is_self_contained_and_links_json_evidence():
    html = (ROOT / "docs" / "phase3_acceptance.html").read_text(encoding="utf-8")
    assert '<html lang="ja">' in html
    assert "Phase 3 Acceptance Report" in html
    assert "P3-1" in html and "P3-6" in html
    assert "phase3_processing_report.json" in html
    assert "<table>" in html
