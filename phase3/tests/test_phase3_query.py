"""Regression checks for Phase 3 natural-language query boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.executor import QueryExecutor
from app.response import ResponseSupplement, attach_response_supplement, render_response

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def executor() -> QueryExecutor:
    return QueryExecutor.from_processed_dir(ROOT / "data" / "processed")


def test_environmental_executor_loads_complete_phase3_access_tables(executor: QueryExecutor):
    assert len(executor.environmental_metrics) == 700
    assert len(executor.weather_station_access) == 100
    assert len(executor.shinkansen_access) == 100
    assert set(executor.environmental_features.columns) >= {
        "climate.january_mean_temperature",
        "climate.annual_snowfall",
        "transport.nearest_shinkansen_distance",
    }
    assert executor._flow_centrality_cache is not None


def test_housing_condition_is_partial_and_never_silently_ranked(executor: QueryExecutor):
    result = executor.execute("福岡市に似ていて住居費が比較的安い都市は？")
    assert result["status"] == "partial"
    assert result["hard_facts"]["target"]["name"] == "福岡市"
    assert "rent" in {item["condition"] for item in result["missing_structured_conditions"]}
    assert all("rent" not in row for row in result["hard_facts"]["ranking"])


def test_reference_free_transport_query_uses_search_medians(executor: QueryExecutor):
    result = executor.execute("空港と新幹線の両方へのアクセスが良い都市は？")
    assert result["status"] == "ok"
    assert result["hard_facts"]["target"] is None
    assert result["hard_facts"]["analysis"] == "phase3_environmental_multi_criteria_search"
    assert all(
        row["transport.nearest_shinkansen_distance"] is not None
        and row["nearest_airport"]["distance_km"] is not None
        for row in result["hard_facts"]["ranking"]
    )


def test_combined_chugoku_shikoku_region_is_filtered_correctly(executor: QueryExecutor):
    result = executor.execute("中国・四国で冬が比較的暖かく、都市機能もある都市は？")
    assert result["status"] == "ok"
    assert result["plan"]["region"] == "中国・四国"
    allowed = {
        "鳥取県",
        "島根県",
        "岡山県",
        "広島県",
        "山口県",
        "徳島県",
        "香川県",
        "愛媛県",
        "高知県",
    }
    assert all(row["prefecture"] in allowed for row in result["hard_facts"]["ranking"])


def test_phase3_response_explains_environmental_units(executor: QueryExecutor):
    result = executor.execute("福岡市に似ていて冬が比較的暖かい都市は？")
    response = render_response(result)
    assert "1月平均気温" in response
    assert "degC" in response
    assert "JMA 2020 normals" in response
    assert "ランキング・数値計算にLLMは使用していません。" in response


def test_execution_path_exposes_no_retrievers(executor: QueryExecutor):
    result = executor.execute("福岡市に似ていて冬が比較的暖かい都市は？")
    boundary = result["provenance_boundary"]
    assert "query_executor" in boundary["execution_path"]
    assert "pandas_networkx_analysis" in boundary["execution_path"]
    assert boundary["retrievers_used"] == []


def test_llm_numeric_claim_check_marks_unverified_numbers(executor: QueryExecutor):
    execution = executor.execute("福岡市と都市特性が似ている都市は？")

    class Provider:
        name = "test_response_provider"

        def __init__(self, explanation: str):
            self.explanation = explanation

        def generate(self, query, plan, hard_facts):
            return ResponseSupplement(evidence_explanation=self.explanation)

    verified = attach_response_supplement(
        execution,
        Provider(f"上位候補の類似度は{execution['hard_facts']['ranking'][0]['similarity']:.4f}です。"),
    )
    assert verified["llm_response"]["numeric_claim_check"]["status"] == "pass"

    unverified = attach_response_supplement(
        execution,
        Provider("存在しない数値999.1234を主張します。"),
    )
    assert unverified["llm_response"]["numeric_claim_check"]["status"] == "warning"
    assert "999.1234" in unverified["llm_response"]["numeric_claim_check"]["unverified_numbers"]
