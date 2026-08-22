"""Focused tests for the Phase 1 natural-language query boundary."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from app.analysis import FeatureSpec, rank_airport_access
from app.executor import (
    CityIndex,
    QueryExecutor,
    execution_is_finite,
    load_similarity_feature_specs,
)
from app.graph import build_mobility_graph
from app.planner import (
    INTENT_AIRPORT_BETTER,
    INTENT_AIRPORT_RANK,
    INTENT_BIDIRECTIONAL_FLOW,
    INTENT_CATEGORY_SIMILARITY,
    INTENT_CITY_SIMILARITY,
    INTENT_CROSS_PREFECTURE_COMMUNITIES,
    INTENT_FLOW_HUB,
    INTENT_SIMILAR_AIRPORT,
    INTENT_UNSUPPORTED,
    QueryPlan,
    plan_query,
)
from app.query import build_parser
from app.response import ResponseSupplement, attach_response_supplement, render_response


@pytest.fixture
def municipality_data() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "municipality_id": "R34100",
                "municipality_code": "34100",
                "prefecture": "広島県",
                "name": "広島市",
                "latitude": 34.4,
                "longitude": 132.45,
                "total_population": 1_000.0,
                "hospital_count": 10.0,
                "school_count": 20.0,
                "income": 500.0,
                "welfare_facilities": 5.0,
            },
            {
                "municipality_id": "R34202",
                "municipality_code": "34202",
                "prefecture": "広島県",
                "name": "呉市",
                "latitude": 34.25,
                "longitude": 132.56,
                "total_population": 800.0,
                "hospital_count": 8.0,
                "school_count": 15.0,
                "income": 450.0,
                "welfare_facilities": 4.0,
            },
            {
                "municipality_id": "R35208",
                "municipality_code": "35208",
                "prefecture": "山口県",
                "name": "岩国市",
                "latitude": 34.17,
                "longitude": 132.22,
                "total_population": 500.0,
                "hospital_count": 5.5,
                "school_count": 9.0,
                "income": 350.0,
                "welfare_facilities": 3.0,
            },
            {
                "municipality_id": "R37201",
                "municipality_code": "37201",
                "prefecture": "香川県",
                "name": "高松市",
                "latitude": 34.34,
                "longitude": 134.05,
                "total_population": 900.0,
                "hospital_count": 9.0,
                "school_count": 18.0,
                "income": 480.0,
                "welfare_facilities": 4.5,
            },
        ]
    )


@pytest.fixture
def executor(municipality_data: pd.DataFrame) -> QueryExecutor:
    commute = pd.DataFrame(
        [
            {"source": "R34100", "target": "R34202", "commuters": 100, "year": 2020},
            {"source": "R34202", "target": "R34100", "commuters": 80, "year": 2020},
            {"source": "R34100", "target": "R35208", "commuters": 30, "year": 2020},
            {"source": "R35208", "target": "R34100", "commuters": 25, "year": 2020},
            {"source": "R34202", "target": "R35208", "commuters": 40, "year": 2020},
            {"source": "R35208", "target": "R34202", "commuters": 35, "year": 2020},
            {"source": "R37201", "target": "R34100", "commuters": 5, "year": 2020},
        ]
    )
    study = pd.DataFrame(
        [
            {"source": "R34100", "target": "R34202", "students": 10, "year": 2020},
            {"source": "R34202", "target": "R34100", "students": 8, "year": 2020},
            {"source": "R34100", "target": "R35208", "students": 3, "year": 2020},
            {"source": "R35208", "target": "R34100", "students": 2, "year": 2020},
            {"source": "R34202", "target": "R35208", "students": 4, "year": 2020},
            {"source": "R35208", "target": "R34202", "students": 3, "year": 2020},
        ]
    )
    airports = pd.DataFrame(
        [
            {
                "airport_id": "A_HIJ",
                "name": "広島空港",
                "latitude": 34.44,
                "longitude": 132.92,
                "airport_type": "regional",
                "airport_scale": 2,
                "scheduled_service": True,
                "source_url": "https://example.test/airport",
            },
            {
                "airport_id": "A_IWK",
                "name": "岩国錦帯橋空港",
                "latitude": 34.14,
                "longitude": 132.24,
                "airport_type": "regional",
                "airport_scale": 3,
                "scheduled_service": True,
                "source_url": "https://example.test/airport",
            },
            {
                "airport_id": "A_TAK",
                "name": "高松空港",
                "latitude": 34.21,
                "longitude": 134.02,
                "airport_type": "regional",
                "airport_scale": 2,
                "scheduled_service": True,
                "source_url": "https://example.test/airport",
            },
        ]
    )
    access = pd.DataFrame(
        [
            {
                "source": "R34100",
                "target": "A_HIJ",
                "distance_km": 50,
                "airport_scale": 2,
                "rank": 1,
            },
            {
                "source": "R34202",
                "target": "A_HIJ",
                "distance_km": 40,
                "airport_scale": 2,
                "rank": 1,
            },
            {
                "source": "R35208",
                "target": "A_IWK",
                "distance_km": 5,
                "airport_scale": 3,
                "rank": 1,
            },
            {
                "source": "R37201",
                "target": "A_TAK",
                "distance_km": 10,
                "airport_scale": 2,
                "rank": 1,
            },
        ]
    )
    graph = build_mobility_graph(
        municipality_data,
        commute_edges=commute,
        study_edges=study,
        airports=airports,
        airport_access=access,
    )
    specs = [
        FeatureSpec("total_population", "population", log1p=True),
        FeatureSpec(
            "hospital_count",
            "medical",
            per_capita=True,
            denominator="total_population",
            log1p=True,
        ),
        FeatureSpec(
            "school_count",
            "education",
            per_capita=True,
            denominator="total_population",
            log1p=True,
        ),
        FeatureSpec("income", "economy", log1p=True),
        FeatureSpec(
            "welfare_facilities",
            "welfare",
            per_capita=True,
            denominator="total_population",
            log1p=True,
        ),
    ]
    return QueryExecutor(municipality_data, graph, feature_specs=specs)


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        ("広島市と人の行き来が最も多い都市は？", INTENT_BIDIRECTIONAL_FLOW),
        ("広島周辺で人流のハブになっている都市は？", INTENT_FLOW_HUB),
        ("県境をまたぐ実質的な生活圏はある？", INTENT_CROSS_PREFECTURE_COMMUNITIES),
        ("広島市と都市特性が似ている都市は？", INTENT_CITY_SIMILARITY),
        ("広島市より空港アクセスが良い都市は？", INTENT_AIRPORT_BETTER),
        ("広島みたいな都市で空港が近いところは？", INTENT_SIMILAR_AIRPORT),
        ("医療面で広島市と似ている都市は？", INTENT_CATEGORY_SIMILARITY),
    ],
)
def test_offline_planner_covers_acceptance_queries(query: str, intent: str):
    plan = plan_query(query)
    assert plan.intent == intent
    assert plan.planner == "offline_japanese_rules_v1"


def test_planner_detects_unavailable_conditions_but_keeps_airport_part():
    plan = plan_query("自然が豊かで温泉もあって空港が近い都市は？")
    assert plan.intent == INTENT_AIRPORT_RANK
    assert plan.criteria == ("nearest_airport_distance",)
    assert {item.condition for item in plan.missing_conditions} == {"nature", "hot_springs"}


@pytest.mark.parametrize(
    "query",
    [
        "広島市より空港アクセスが悪い都市は？",
        "空港が遠い都市は？",
    ],
)
def test_planner_rejects_negative_airport_polarity(query: str):
    plan = plan_query(query)
    assert plan.intent == INTENT_UNSUPPORTED
    assert {item.condition for item in plan.missing_conditions} == {"airport_polarity"}


def test_generic_airport_access_defaults_to_nearest_scheduled_airport_distance():
    better = plan_query("広島市より空港アクセスが良い都市は？")
    combined = plan_query("広島市と似ていて空港アクセスも良い都市は？")
    default_plan = QueryPlan(query="空港アクセスは？", intent=INTENT_AIRPORT_RANK)

    assert better.airport_metric == "nearest_distance"
    assert better.criteria == ("nearest_airport_distance",)
    assert combined.airport_metric == "nearest_distance"
    assert combined.criteria == ("city_similarity", "nearest_airport_distance")
    assert default_plan.airport_metric == "nearest_distance"


def test_airport_scale_score_requires_explicit_scale_or_passenger_wording():
    plan = plan_query("広島市より空港規模と距離のアクセススコアが良い都市は？")
    assert plan.intent == INTENT_AIRPORT_BETTER
    assert plan.airport_metric == "access_score"
    assert plan.criteria == ("airport_access",)


def test_alias_resolves_hiroshima_without_city_suffix(municipality_data: pd.DataFrame):
    assert CityIndex(municipality_data).resolve("広島") == "R34100"
    assert plan_query("広島みたいな都市で空港が近いところは？").city == "広島市"


def test_similarity_feature_config_is_loaded_as_explicit_specs(tmp_path):
    path = tmp_path / "similarity_features.yml"
    path.write_text(
        """\
features:
  - name: feature_doctors_per_10k
    category: medical
    log1p: true
  - name: feature_population_density
    category: population
""",
        encoding="utf-8",
    )
    specs = load_similarity_feature_specs(path)
    assert specs == [
        FeatureSpec("feature_doctors_per_10k", "medical", log1p=True),
        FeatureSpec("feature_population_density", "population"),
    ]


@pytest.mark.parametrize(
    ("query", "analysis"),
    [
        ("広島市と人の行き来が最も多い都市は？", "bidirectional_flow"),
        ("広島周辺で人流のハブになっている都市は？", "flow_centrality"),
        ("県境をまたぐ実質的な生活圏はある？", "flow_communities"),
        ("広島市と都市特性が似ている都市は？", "city_similarity"),
        ("広島市より空港アクセスが良い都市は？", "airport_better_than_reference"),
        ("広島みたいな都市で空港が近いところは？", "similar_cities_with_better_airport"),
        ("医療面で広島市と似ている都市は？", "city_similarity"),
    ],
)
def test_executor_computes_all_acceptance_families(
    executor: QueryExecutor,
    query: str,
    analysis: str,
):
    result = executor.execute(query)
    assert result["status"] in {"ok", "no_result"}
    assert result["hard_facts"]["analysis"] == analysis
    assert result["provenance_boundary"]["llm_used_for_numbers"] is False
    assert result["soft_knowledge"] is None
    metadata = result["hard_facts"]["evidence_metadata"]
    assert metadata["datasets"]
    assert all(item["edition"] for item in metadata["datasets"])
    assert all(
        item.get("source_url") or item.get("provenance_path")
        for item in metadata["datasets"]
    )
    assert metadata["metrics"] and all(item["unit"] for item in metadata["metrics"])
    assert metadata["universe"]["label"] == "phase1_fixed_20_city_induced_universe"
    assert metadata["limitations"]
    assert execution_is_finite(result)
    json.dumps(result, ensure_ascii=False, allow_nan=False)


def test_flow_answer_has_directional_quantitative_evidence(executor: QueryExecutor):
    result = executor.execute("広島と人の行き来が最も多い都市は？")
    strongest = result["hard_facts"]["strongest"]
    assert strongest["name"] == "呉市"
    assert strongest["forward_flow"] == 110
    assert strongest["reverse_flow"] == 88
    assert strongest["bidirectional_flow"] == 198
    answer = render_response(result)
    assert "実データに基づく根拠" in answer
    assert "198人" in answer
    assert "LLMは使用していません" in answer
    assert "データセット/版" in answer and "指標/単位" in answer


def test_partial_answer_separates_missing_conditions(executor: QueryExecutor):
    result = executor.execute("自然が豊かで温泉もあって空港が近い都市は？")
    assert result["status"] == "partial"
    assert result["hard_facts"]["analysis"] == "airport_access"
    assert {item["condition"] for item in result["missing_structured_conditions"]} == {
        "nature",
        "hot_springs",
    }
    answer = render_response(result)
    assert "現在の構造化データにない条件" in answer
    assert "自然の豊かさ" in answer and "温泉" in answer


def test_optional_llm_interfaces_cannot_add_hard_facts(executor: QueryExecutor):
    class FakePlanner:
        name = "fake_llm"

        def plan(self, _query, _available_cities):
            return {
                "intent": INTENT_CITY_SIMILARITY,
                "city": "広島",
                "criteria": ["city_similarity", "hot_springs"],
                "invented_score": 999,
            }

    planned = executor.execute("候補を探して", planner_provider=FakePlanner())
    assert planned["hard_facts"]["analysis"] == "city_similarity"
    assert planned["plan"].get("invented_score") is None
    assert planned["missing_structured_conditions"][0]["condition"] == "hot_springs"

    class FakeResponse:
        name = "fake_response_llm"

        def generate(self, _query, _plan, _hard_facts):
            return ResponseSupplement(
                evidence_explanation="計算済み根拠の説明です。",
                soft_knowledge="これは一般知識です。",
            )

    supplemented = attach_response_supplement(planned, FakeResponse())
    assert supplemented["hard_facts"] == planned["hard_facts"]
    assert supplemented["llm_response"]["used_for_ranking_or_numbers"] is False
    answer = render_response(supplemented)
    assert "Soft Knowledge（参考。ランキング未使用）" in answer


def test_provider_cannot_silently_enable_airport_scale_score():
    class AirportPlanner:
        name = "airport_llm"

        def plan(self, _query, _available_cities):
            return {
                "intent": INTENT_AIRPORT_BETTER,
                "city": "広島市",
                "criteria": ["airport_access"],
                "airport_metric": "access_score",
            }

    generic = plan_query(
        "広島市より空港アクセスが良い都市は？",
        provider=AirportPlanner(),
    )
    explicit = plan_query(
        "広島市より空港規模を含むアクセススコアが良い都市は？",
        provider=AirportPlanner(),
    )
    assert generic.airport_metric == "nearest_distance"
    assert generic.criteria == ("nearest_airport_distance",)
    assert explicit.airport_metric == "access_score"
    assert explicit.criteria == ("airport_access",)


def test_generic_and_explicit_airport_evidence_use_different_metrics(executor: QueryExecutor):
    generic = executor.execute("広島市より空港アクセスが良い都市は？")
    explicit = executor.execute(
        "広島市より空港規模と距離のアクセススコアが良い都市は？"
    )
    combined = executor.execute("広島市と似ていて空港アクセスも良い都市は？")

    assert generic["hard_facts"]["requested_metric"] == "nearest_distance"
    assert combined["hard_facts"]["requested_airport_metric"] == "nearest_distance"
    assert explicit["hard_facts"]["requested_metric"] == "access_score"
    assert "access_score" not in generic["hard_facts"]["reference"]
    assert "access_score" not in generic["hard_facts"]["ranking"][0]
    assert "access_score" not in combined["hard_facts"]["ranking"][0]
    assert "access_score" in explicit["hard_facts"]["reference"]
    assert "アクセススコア" not in render_response(generic).split("実データ")[0]
    generic_datasets = {
        item["dataset"] for item in generic["hard_facts"]["evidence_metadata"]["datasets"]
    }
    explicit_datasets = {
        item["dataset"] for item in explicit["hard_facts"]["evidence_metadata"]["datasets"]
    }
    assert "2025 Airport Management Status Report" not in generic_datasets
    assert "2025 Airport Management Status Report" in explicit_datasets


def test_airport_access_skips_unscheduled_airport(executor: QueryExecutor):
    executor.graph.nodes["A_HIJ"]["scheduled_service"] = False

    result = rank_airport_access(executor.graph, municipality_ids=["R34100"])

    assert result["ranking"] == []
    assert result["missing_access_city_ids"] == ["R34100"]


def test_cli_exposes_query_json_and_processed_data_options():
    args = build_parser().parse_args(
        [
            "--query",
            "広島市の人流ハブは？",
            "--processed-data",
            "/tmp/processed",
            "--llm",
            "--json",
        ]
    )
    assert args.query == "広島市の人流ハブは？"
    assert str(args.processed_data) == "/tmp/processed"
    assert args.llm is True
    assert args.json is True
