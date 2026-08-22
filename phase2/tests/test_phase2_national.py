"""Acceptance-level checks for the national analysis/search-space boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.executor import QueryExecutor

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def executor() -> QueryExecutor:
    return QueryExecutor.from_processed_dir(ROOT / "data" / "processed")


def test_executor_separates_national_analysis_and_100_city_search(executor: QueryExecutor):
    assert len(executor.municipalities) == 1719
    assert len(executor.search_municipalities) == 100
    assert len(executor.city_index.city_names) == 100


def test_national_hub_query_projects_full_metrics_to_search_universe(executor: QueryExecutor):
    result = executor.execute("全国主要都市で人流ハブ性が高い都市は？")

    assert result["status"] == "ok"
    assert result["hard_facts"]["analysis"] == "flow_centrality"
    assert result["hard_facts"]["evidence_metadata"]["universe"]["analysis_universe_count"] == 1719
    assert result["hard_facts"]["rankings"]["weighted_pagerank"][0]["name"] == "東京都区部"


def test_region_similarity_filter_uses_only_kyushu_candidates(executor: QueryExecutor):
    result = executor.execute("九州で福岡市に似ている都市は？")

    assert result["status"] == "ok"
    kyushu_prefectures = {
        "福岡県",
        "佐賀県",
        "長崎県",
        "熊本県",
        "大分県",
        "宮崎県",
        "鹿児島県",
    }
    assert all(item["prefecture"] in kyushu_prefectures for item in result["hard_facts"]["ranking"])


def test_excluded_region_keeps_reference_city_but_filters_candidates(executor: QueryExecutor):
    result = executor.execute("九州以外で福岡市に似ていて空港アクセスが良い都市は？")

    assert result["status"] in {"ok", "no_result"}
    assert result["hard_facts"]["analysis"] == "similar_cities_with_better_airport"
    kyushu_prefectures = {
        "福岡県",
        "佐賀県",
        "長崎県",
        "熊本県",
        "大分県",
        "宮崎県",
        "鹿児島県",
    }
    assert all(
        item["prefecture"] not in kyushu_prefectures for item in result["hard_facts"]["ranking"]
    )


def test_population_and_urban_function_query_returns_explicit_proxy(executor: QueryExecutor):
    result = executor.execute("人口規模を抑えながら、都市機能が比較的充実した都市は？")

    assert result["status"] == "ok"
    assert result["hard_facts"]["analysis"] == "multi_criteria_search"
    assert result["hard_facts"]["criteria"]["urban_function_proxy"] == "weighted_degree"
    assert all(item["population"] < 1_000_000 for item in result["hard_facts"]["ranking"])
