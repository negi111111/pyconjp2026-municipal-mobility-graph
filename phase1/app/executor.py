"""Execute validated query plans with pandas and NetworkX only."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd
import yaml

from .analysis import (
    FeatureSpec,
    city_similarity,
    compute_flow_centrality,
    detect_flow_communities,
    find_similar_cities_with_better_airport,
    rank_airport_access,
    rank_bidirectional_flows,
)
from .graph import build_graph_from_parquet
from .planner import (
    INTENT_AIRPORT_BETTER,
    INTENT_AIRPORT_RANK,
    INTENT_BIDIRECTIONAL_FLOW,
    INTENT_CATEGORY_SIMILARITY,
    INTENT_CITY_SIMILARITY,
    INTENT_CROSS_PREFECTURE_COMMUNITIES,
    INTENT_FLOW_HUB,
    INTENT_SIMILAR_AIRPORT,
    INTENT_UNSUPPORTED,
    PlannerProvider,
    QueryPlan,
    plan_query,
)

_CATEGORY_FEATURE_TOKENS: dict[str, tuple[str, ...]] = {
    "medical": (
        "medical",
        "health",
        "hospital",
        "doctor",
        "clinic",
        "医療",
        "病院",
        "医師",
        "診療",
        "歯科",
        "薬局",
        "病床",
    ),
    "education": (
        "education",
        "school",
        "student",
        "教育",
        "学校",
        "生徒",
        "学生",
        "幼稚園",
    ),
    "economy": (
        "econom",
        "income",
        "employment",
        "worker",
        "経済",
        "所得",
        "就業",
        "労働",
        "事業所",
    ),
    "welfare": (
        "welfare",
        "care",
        "nursery",
        "福祉",
        "介護",
        "保育",
        "老人ホーム",
    ),
    "population": (
        "population",
        "household",
        "age",
        "人口",
        "世帯",
        "年齢",
    ),
}

_INTENTS_REQUIRING_CITY = frozenset(
    {
        INTENT_BIDIRECTIONAL_FLOW,
        INTENT_CITY_SIMILARITY,
        INTENT_CATEGORY_SIMILARITY,
        INTENT_AIRPORT_BETTER,
        INTENT_SIMILAR_AIRPORT,
    }
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

_PROVENANCE_PATH = "data/provenance/sources.yml"
_SSDSE_DATASET = {
    "dataset": "SSDSE-A-2026",
    "provider": "National Statistics Center, Japan",
    "edition": "2026-06-30 publication; columns have individual reference years",
    "source_url": "https://www.nstac.go.jp/use/literacy/ssdse/",
    "provenance_path": _PROVENANCE_PATH,
}
_CENSUS_OD_DATASET = {
    "dataset": "2020 Population Census Table 3 place-of-work/school OD",
    "provider": "Statistics Bureau of Japan / e-Stat",
    "edition": "2020 Population Census",
    "source_url": "https://www.e-stat.go.jp/stat-search/database?statdisp_id=0003454524",
    "provenance_path": _PROVENANCE_PATH,
}
_MUNICIPAL_OFFICE_DATASET = {
    "dataset": "National Land Numerical Information P05-22",
    "provider": "MLIT, Japan",
    "edition": "2022-04 reference date",
    "source_url": "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P05-v3_0.html",
    "provenance_path": _PROVENANCE_PATH,
}
_AIRPORT_DATASET = {
    "dataset": "National Land Numerical Information C28-21 Airport Data",
    "provider": "MLIT, Japan",
    "edition": "2021-12-31 snapshot",
    "source_url": "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-C28-2021.html",
    "provenance_path": _PROVENANCE_PATH,
}
_AIRPORT_PASSENGER_DATASET = {
    "dataset": "2025 Airport Management Status Report",
    "provider": "Civil Aviation Bureau, MLIT, Japan",
    "edition": "Reiwa 7 (2025) report workbook",
    "source_url": "https://www.mlit.go.jp/koku/15_bf_000185.html",
    "provenance_path": _PROVENANCE_PATH,
}


def _metric(name: str, unit: str, definition: str) -> dict[str, str]:
    return {"name": name, "unit": unit, "definition": definition}


def _distance_only_access(record: Mapping[str, Any]) -> dict[str, Any]:
    """Expose only evidence used by the default Phase 1 airport metric."""

    nearest = record.get("nearest_airport") or {}
    airport_fields = (
        "airport_id",
        "name",
        "airport_type",
        "scheduled_service",
        "distance_km",
        "source_rank",
    )
    result = {
        key: record[key]
        for key in ("municipality_id", "name", "prefecture", "rank", "airports_considered")
        if key in record
    }
    result["nearest_airport"] = {key: nearest[key] for key in airport_fields if key in nearest}
    return result


def _normalize_city(value: Any) -> str:
    return re.sub(r"[\s　]+", "", str(value)).strip()


def _portable_project_path(value: str | Path | None) -> str | None:
    """Keep generated evidence portable when a path is inside this project."""

    if value is None:
        return None
    path = Path(value)
    try:
        return str(path.resolve().relative_to(_PROJECT_ROOT))
    except ValueError:
        return str(path)


class CityIndex:
    """Resolve municipality IDs, exact names, and unambiguous ``市``-less aliases."""

    def __init__(self, municipalities: pd.DataFrame):
        required = {"municipality_id", "name"}
        missing = sorted(required.difference(municipalities.columns))
        if missing:
            raise ValueError(f"municipalities is missing required columns: {', '.join(missing)}")
        aliases: dict[str, set[Any]] = {}
        canonical_names: dict[Any, str] = {}
        for row in municipalities[["municipality_id", "name"]].to_dict(orient="records"):
            municipality_id = row["municipality_id"]
            name = str(row["name"])
            canonical_names[municipality_id] = name
            candidates = {_normalize_city(municipality_id), _normalize_city(name)}
            if name.endswith("市") and len(name) > 1:
                candidates.add(_normalize_city(name[:-1]))
            for alias in candidates:
                aliases.setdefault(alias, set()).add(municipality_id)
        self._aliases = aliases
        self._names = canonical_names

    @property
    def city_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._names.values()))

    def resolve(self, value: Any) -> Any:
        key = _normalize_city(value)
        matches = self._aliases.get(key, set())
        if not matches:
            raise KeyError(f"対象都市 {value!r} はPhase 1の都市データにありません。")
        if len(matches) > 1:
            names = sorted(self._names[item] for item in matches)
            raise ValueError(f"都市名 {value!r} は曖昧です: {', '.join(names)}")
        return next(iter(matches))


def load_similarity_feature_specs(path: str | Path) -> list[FeatureSpec]:
    """Load auditable similarity transformations from YAML."""

    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    values = raw.get("features") if isinstance(raw, Mapping) else None
    if not isinstance(values, list) or not values:
        raise ValueError(f"{config_path}: 'features' must be a non-empty list")
    allowed = {"name", "category", "per_capita", "denominator", "per_capita_scale", "log1p"}
    specs: list[FeatureSpec] = []
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            raise ValueError(f"{config_path}: features[{index}] must be a mapping")
        unknown = set(value).difference(allowed)
        if unknown:
            raise ValueError(
                f"{config_path}: features[{index}] has unknown fields: {', '.join(sorted(unknown))}"
            )
        specs.append(FeatureSpec(**dict(value)))
    return specs


def _discover_similarity_config(processed_dir: Path) -> Path | None:
    candidates = (
        processed_dir / "similarity_features.yml",
        processed_dir.parent.parent / "configs" / "similarity_features.yml",
    )
    return next((path for path in candidates if path.exists()), None)


class QueryExecutor:
    """Run a :class:`QueryPlan` and return JSON-friendly structured evidence."""

    def __init__(
        self,
        municipalities: pd.DataFrame,
        graph: nx.MultiDiGraph,
        *,
        feature_specs: Sequence[FeatureSpec] | None = None,
        feature_config_path: str | Path | None = None,
    ):
        self.municipalities = municipalities.copy()
        self.graph = graph
        self.city_index = CityIndex(self.municipalities)
        self.feature_specs = tuple(feature_specs) if feature_specs is not None else None
        self.feature_config_path = _portable_project_path(feature_config_path)

    def _attach_evidence(
        self,
        result: dict[str, Any],
        *,
        datasets: Sequence[Mapping[str, str]],
        metrics: Sequence[Mapping[str, str]],
        limitations: Sequence[str],
        relation_scope: str,
    ) -> dict[str, Any]:
        """Attach the deterministic provenance/units boundary to computed facts."""

        result["evidence_metadata"] = {
            "datasets": [dict(dataset) for dataset in datasets],
            "metrics": [dict(metric) for metric in metrics],
            "universe": {
                "label": "phase1_fixed_20_city_induced_universe",
                "expected_municipality_count": 20,
                "actual_municipality_count": int(self.municipalities["municipality_id"].nunique()),
                "relation_scope": relation_scope,
            },
            "limitations": list(limitations),
        }
        return result

    @classmethod
    def from_processed_dir(
        cls,
        processed_dir: str | Path,
        *,
        similarity_config: str | Path | None = None,
        strict: bool = True,
    ) -> QueryExecutor:
        directory = Path(processed_dir)
        municipalities_path = directory / "municipalities.parquet"
        if not municipalities_path.exists():
            raise FileNotFoundError(municipalities_path)
        municipalities = pd.read_parquet(municipalities_path)
        graph = build_graph_from_parquet(directory, strict=strict)
        config_path = (
            Path(similarity_config) if similarity_config else _discover_similarity_config(directory)
        )
        specs = load_similarity_feature_specs(config_path) if config_path is not None else None
        return cls(
            municipalities,
            graph,
            feature_specs=specs,
            feature_config_path=config_path,
        )

    def execute(
        self,
        plan_or_query: QueryPlan | str,
        *,
        planner_provider: PlannerProvider | None = None,
    ) -> dict[str, Any]:
        """Compute evidence; unavailable conditions remain explicitly separate."""

        plan = (
            plan_query(
                plan_or_query,
                available_cities=self.city_index.city_names,
                provider=planner_provider,
            )
            if isinstance(plan_or_query, str)
            else plan_or_query
        )
        missing_conditions = [item.to_dict() for item in plan.missing_conditions]
        base: dict[str, Any] = {
            "query": plan.query,
            "plan": plan.to_dict(),
            "status": "partial" if missing_conditions else "ok",
            "hard_facts": None,
            "missing_structured_conditions": missing_conditions,
            "soft_knowledge": None,
            "provenance_boundary": {
                "computed_by": "pandas/networkx",
                "llm_used_for_numbers": False,
                "wikipedia_or_graphrag_used": False,
                "execution_path": [
                    "llm_planner" if planner_provider is not None else "rule_planner",
                    "query_executor",
                    "pandas_networkx_analysis",
                ],
                "retrievers_used": [],
                "feature_config": self.feature_config_path,
            },
            "errors": [],
        }

        if plan.intent == INTENT_UNSUPPORTED:
            base["status"] = "unsupported"
            return base
        if plan.intent in _INTENTS_REQUIRING_CITY and plan.city is None:
            base["status"] = "cannot_execute"
            base["errors"].append("比較基準となる都市名を識別できませんでした。")
            return base

        try:
            city_id = self.city_index.resolve(plan.city) if plan.city is not None else None
            hard_facts = self._dispatch(plan, city_id)
        except (KeyError, ValueError) as exc:
            base["status"] = "cannot_execute"
            base["errors"].append(str(exc).strip("'"))
            return base

        base["hard_facts"] = hard_facts
        if not hard_facts.get("ranking") and plan.intent not in {
            INTENT_FLOW_HUB,
            INTENT_CROSS_PREFECTURE_COMMUNITIES,
        }:
            base["status"] = "no_result" if not missing_conditions else "partial"
        return base

    def _dispatch(self, plan: QueryPlan, city_id: Any) -> dict[str, Any]:
        similarity_options: dict[str, Any] = {}
        if self.feature_specs is not None:
            similarity_options["feature_specs"] = self.feature_specs

        if plan.intent == INTENT_BIDIRECTIONAL_FLOW:
            result = rank_bidirectional_flows(self.graph, city_id, top_n=plan.top_n)
            result["strongest"] = result["ranking"][0] if result["ranking"] else None
            result["evidence_source"] = "2020 Census COMMUTES_TO/STUDIES_IN edges"
            return self._attach_evidence(
                result,
                datasets=[_CENSUS_OD_DATASET],
                metrics=[
                    _metric(
                        "forward_flow/reverse_flow/bidirectional_flow",
                        "persons",
                        "commuters plus students; bidirectional is A-to-B plus B-to-A",
                    )
                ],
                limitations=[
                    "Only OD pairs with both endpoints in the fixed 20-city seed are ranked.",
                    "Self flows are excluded; this is a 2020 statistical count, not live movement.",
                ],
                relation_scope="COMMUTES_TO and STUDIES_IN only; IS_IN/ACCESS_TO excluded",
            )
        if plan.intent == INTENT_FLOW_HUB:
            result = compute_flow_centrality(self.graph)
            result["rankings"] = {
                metric: values[: plan.top_n] for metric, values in result["rankings"].items()
            }
            result["display_top_n"] = plan.top_n
            result["evidence_source"] = "2020 Census COMMUTES_TO/STUDIES_IN edges only"
            return self._attach_evidence(
                result,
                datasets=[_CENSUS_OD_DATASET],
                metrics=[
                    _metric("weighted_in_degree", "persons", "sum of incoming OD weights"),
                    _metric("weighted_out_degree", "persons", "sum of outgoing OD weights"),
                    _metric("weighted_degree", "persons", "weighted in-degree plus out-degree"),
                    _metric("weighted_pagerank", "dimensionless", "weighted directed PageRank"),
                ],
                limitations=[
                    (
                        "Centrality is relative to the fixed 20-city induced graph; "
                        "outside flows are absent."
                    ),
                    "Self flows are excluded and the OD observation year is 2020.",
                ],
                relation_scope="COMMUTES_TO and STUDIES_IN only; IS_IN/ACCESS_TO excluded",
            )
        if plan.intent == INTENT_CROSS_PREFECTURE_COMMUNITIES:
            result = detect_flow_communities(self.graph, top_cross_prefecture_links=plan.top_n)
            result["evidence_source"] = "Louvain on Census flow edges; IS_IN is annotation only"
            return self._attach_evidence(
                result,
                datasets=[_CENSUS_OD_DATASET],
                metrics=[
                    _metric(
                        "internal_symmetric_weight/bidirectional_total_flow",
                        "persons",
                        "sum of directed commuter and student counts in both directions",
                    ),
                    _metric("modularity", "dimensionless", "Louvain partition modularity"),
                ],
                limitations=[
                    "Communities depend on the fixed 20-city seed, Louvain resolution, and seed.",
                    "Cross-prefecture is an annotation after flow-only community detection.",
                ],
                relation_scope=(
                    "Louvain uses COMMUTES_TO/STUDIES_IN only; prefecture edges excluded"
                ),
            )
        if plan.intent == INTENT_CITY_SIMILARITY:
            result = city_similarity(
                self.municipalities,
                city_id,
                top_n=plan.top_n,
                **similarity_options,
            )
            result["requested_category"] = "overall"
            result["evidence_source"] = "transformed SSDSE municipality attributes"
            return self._attach_evidence(
                result,
                datasets=[_SSDSE_DATASET],
                metrics=[
                    _metric(
                        "similarity/category_scores",
                        "dimensionless cosine similarity [-1, 1]",
                        "cosine over configured, transformed, imputed, and z-scored SSDSE features",
                    )
                ],
                limitations=[
                    "Similarity is relative to the configured features and fixed 20-city universe.",
                    "SSDSE columns have individual reference years; see returned feature metadata.",
                ],
                relation_scope=(
                    "municipality attributes only; graph edges are not similarity inputs"
                ),
            )
        if plan.intent == INTENT_CATEGORY_SIMILARITY:
            return self._category_similarity(city_id, plan.category or "other", plan.top_n)
        if plan.intent == INTENT_AIRPORT_RANK:
            return self._airport_rank(plan.airport_metric, plan.top_n)
        if plan.intent == INTENT_AIRPORT_BETTER:
            return self._airport_better(city_id, plan.airport_metric, plan.top_n)
        if plan.intent == INTENT_SIMILAR_AIRPORT:
            if plan.airport_metric == "nearest_distance":
                return self._similar_with_nearer_airport(
                    city_id,
                    plan.top_n,
                    similarity_options,
                )
            result = find_similar_cities_with_better_airport(
                self.municipalities,
                self.graph,
                city_id,
                require_nearer=plan.airport_metric == "nearest_distance",
                top_n=plan.top_n,
                **similarity_options,
            )
            result["requested_airport_metric"] = plan.airport_metric
            result["evidence_source"] = (
                "transformed SSDSE attributes plus scheduled-airport straight-line distance/scale"
            )
            return self._attach_evidence(
                result,
                datasets=[
                    _SSDSE_DATASET,
                    _MUNICIPAL_OFFICE_DATASET,
                    _AIRPORT_DATASET,
                    _AIRPORT_PASSENGER_DATASET,
                ],
                metrics=[
                    _metric(
                        "similarity",
                        "dimensionless cosine similarity [-1, 1]",
                        "SSDSE cosine similarity",
                    ),
                    _metric(
                        "nearest_airport.distance_km",
                        "km",
                        "haversine straight-line distance from main municipal office",
                    ),
                    _metric(
                        "access_score",
                        "dimensionless",
                        "passenger-derived airport scale divided by distance decay",
                    ),
                ],
                limitations=[
                    (
                        "The access score is used only because the query explicitly "
                        "requested scale/passengers."
                    ),
                    "Distance is straight-line, not road/rail travel time or terminal access time.",
                    "Airport geometry is a 2021 snapshot; passenger scale uses the 2025 report.",
                ],
                relation_scope="SSDSE attributes plus municipality-to-scheduled-airport ACCESS_TO",
            )
        raise ValueError(f"intent {plan.intent!r} has no executor")

    def _category_similarity(self, city_id: Any, category: str, top_n: int) -> dict[str, Any]:
        if self.feature_specs is not None:
            specs = [spec for spec in self.feature_specs if spec.category == category]
            if not specs:
                raise ValueError(f"カテゴリ {category!r} の類似度特徴量が設定されていません。")
            result = city_similarity(
                self.municipalities,
                city_id,
                feature_specs=specs,
                top_n=top_n,
            )
        else:
            tokens = _CATEGORY_FEATURE_TOKENS.get(category, ())
            features = [
                str(column)
                for column in self.municipalities.columns
                if any(token in str(column).lower() for token in tokens)
                and pd.to_numeric(self.municipalities[column], errors="coerce").notna().any()
            ]
            if not features:
                raise ValueError(f"カテゴリ {category!r} に対応するSSDSE指標がありません。")
            result = city_similarity(
                self.municipalities,
                city_id,
                features=features,
                category_map={feature: category for feature in features},
                top_n=top_n,
            )
        result["requested_category"] = category
        result["evidence_source"] = f"transformed SSDSE {category} attributes"
        return self._attach_evidence(
            result,
            datasets=[_SSDSE_DATASET],
            metrics=[
                _metric(
                    "similarity",
                    "dimensionless cosine similarity [-1, 1]",
                    f"cosine over configured and transformed SSDSE {category} features only",
                )
            ],
            limitations=[
                f"The result covers only configured {category} features and the fixed 20 cities.",
                "SSDSE columns have individual reference years; see returned feature metadata.",
            ],
            relation_scope="municipality attributes only; graph edges are not similarity inputs",
        )

    def _airport_rank(self, metric: str, top_n: int) -> dict[str, Any]:
        result = rank_airport_access(self.graph, top_n=None)
        ranking = list(result["ranking"])
        if metric == "nearest_distance":
            ranking.sort(
                key=lambda item: (
                    float(item["nearest_airport"]["distance_km"]),
                    str(item["municipality_id"]),
                )
            )
            for rank, item in enumerate(ranking, start=1):
                item["rank"] = rank
            result["method"] = "nearest_scheduled_airport_geodesic_distance"
            result["score_formula"] = None
            ranking = [_distance_only_access(item) for item in ranking]
            result["parameters"] = {
                "top_n": top_n,
                "airport_filter": "in-service airports with scheduled service",
            }
        else:
            result["parameters"]["top_n"] = top_n
        result["ranking"] = ranking[:top_n]
        result["requested_metric"] = metric
        if metric == "nearest_distance":
            datasets = [_MUNICIPAL_OFFICE_DATASET, _AIRPORT_DATASET]
            metrics = [
                _metric(
                    "nearest_airport.distance_km",
                    "km",
                    "haversine straight-line distance from main municipal office",
                )
            ]
            result["evidence_source"] = (
                "scheduled-airport public coordinates and computed straight-line distance"
            )
            limitations = [
                "Distance is straight-line, not road/rail travel time or terminal access time.",
                "Municipality points are main offices; airport points are C28 reference points.",
                "Operating/scheduled-service status is fixed at the C28 2021 snapshot.",
            ]
        else:
            datasets = [
                _MUNICIPAL_OFFICE_DATASET,
                _AIRPORT_DATASET,
                _AIRPORT_PASSENGER_DATASET,
            ]
            metrics = [
                _metric("nearest_airport.distance_km", "km", "haversine straight-line distance"),
                _metric(
                    "access_score",
                    "dimensionless",
                    "passenger-derived airport scale divided by distance decay",
                ),
            ]
            result["evidence_source"] = (
                "scheduled-airport straight-line distance and passenger-derived airport scale"
            )
            limitations = [
                "The scale score is an ordinal passenger band, not route count or travel time.",
                "Airport geometry is a 2021 snapshot; passenger scale uses the 2025 report.",
            ]
        return self._attach_evidence(
            result,
            datasets=datasets,
            metrics=metrics,
            limitations=limitations,
            relation_scope="municipality-to-nearest-scheduled-airport ACCESS_TO only",
        )

    def _airport_better(self, city_id: Any, metric: str, top_n: int) -> dict[str, Any]:
        access = rank_airport_access(self.graph, top_n=None)
        by_id = {item["municipality_id"]: item for item in access["ranking"]}
        if city_id not in by_id:
            raise ValueError(f"基準都市 {city_id!r} にACCESS_TOデータがありません。")
        reference = by_id[city_id]
        candidates = [item for item in access["ranking"] if item["municipality_id"] != city_id]
        if metric == "nearest_distance":
            threshold = float(reference["nearest_airport"]["distance_km"])
            candidates = [
                item
                for item in candidates
                if float(item["nearest_airport"]["distance_km"]) < threshold
            ]
            candidates.sort(
                key=lambda item: (
                    float(item["nearest_airport"]["distance_km"]),
                    str(item["municipality_id"]),
                )
            )
            formula = "candidate nearest_airport.distance_km < reference distance"
        else:
            threshold = float(reference["access_score"])
            candidates = [item for item in candidates if float(item["access_score"]) > threshold]
            candidates.sort(
                key=lambda item: (-float(item["access_score"]), str(item["municipality_id"]))
            )
            formula = access["score_formula"] + "; candidate score > reference score"
        for rank, item in enumerate(candidates, start=1):
            item["rank"] = rank
            comparison = {
                "nearest_distance_improvement_km": (
                    float(reference["nearest_airport"]["distance_km"])
                    - float(item["nearest_airport"]["distance_km"])
                )
            }
            if metric == "access_score":
                comparison["access_score_gain"] = float(item["access_score"]) - float(
                    reference["access_score"]
                )
            item["comparison_to_reference"] = comparison
        if metric == "nearest_distance":
            reference_result = _distance_only_access(reference)
            candidate_results = []
            for item in candidates:
                cleaned = _distance_only_access(item)
                cleaned["comparison_to_reference"] = item["comparison_to_reference"]
                candidate_results.append(cleaned)
        else:
            reference_result = reference
            candidate_results = candidates
        result = {
            "analysis": "airport_better_than_reference",
            "requested_metric": metric,
            "formula": formula,
            "reference": reference_result,
            "candidate_count": len(candidates),
            "ranking": candidate_results[:top_n],
            "missing_access_city_ids": access["missing_access_city_ids"],
            "evidence_source": (
                "scheduled-airport public coordinates and computed straight-line distance"
                if metric == "nearest_distance"
                else "scheduled-airport straight-line distance and passenger-derived scale"
            ),
        }
        datasets = [_MUNICIPAL_OFFICE_DATASET, _AIRPORT_DATASET]
        metrics = [
            _metric(
                "nearest_airport.distance_km",
                "km",
                "haversine straight-line distance from main municipal office",
            )
        ]
        limitations = [
            "Distance is straight-line, not road/rail travel time or terminal access time.",
            "Operating/scheduled-service status is fixed at the C28 2021 snapshot.",
        ]
        if metric == "access_score":
            datasets.append(_AIRPORT_PASSENGER_DATASET)
            metrics.append(
                _metric(
                    "access_score",
                    "dimensionless",
                    "passenger-derived airport scale divided by distance decay",
                )
            )
            limitations.append(
                "Airport geometry is a 2021 snapshot; passenger scale uses the 2025 report."
            )
        return self._attach_evidence(
            result,
            datasets=datasets,
            metrics=metrics,
            limitations=limitations,
            relation_scope="municipality-to-nearest-scheduled-airport ACCESS_TO only",
        )

    def _similar_with_nearer_airport(
        self,
        city_id: Any,
        top_n: int,
        similarity_options: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Filter by literal nearest-airport distance, then rank by SSDSE similarity."""

        similarity = city_similarity(
            self.municipalities,
            city_id,
            top_n=None,
            **similarity_options,
        )
        access = rank_airport_access(self.graph, top_n=None)
        access_by_id = {item["municipality_id"]: item for item in access["ranking"]}
        if city_id not in access_by_id:
            raise ValueError(f"基準都市 {city_id!r} にACCESS_TOデータがありません。")
        target_access = access_by_id[city_id]
        target_distance = float(target_access["nearest_airport"]["distance_km"])
        ranking: list[dict[str, Any]] = []
        for similar in similarity["ranking"]:
            candidate_access = access_by_id.get(similar["municipality_id"])
            if candidate_access is None or similar["similarity"] is None:
                continue
            candidate_distance = float(candidate_access["nearest_airport"]["distance_km"])
            distance_gain = target_distance - candidate_distance
            if distance_gain <= 0:
                continue
            ranking.append(
                {
                    **similar,
                    "candidate_airport_access": _distance_only_access(candidate_access),
                    "target_airport_access": _distance_only_access(target_access),
                    "nearest_distance_improvement_km": distance_gain,
                    "is_nearer": True,
                }
            )
        ranking.sort(
            key=lambda item: (
                -float(item["similarity"]),
                -float(item["nearest_distance_improvement_km"]),
                str(item["municipality_id"]),
            )
        )
        for rank, item in enumerate(ranking, start=1):
            item["rank"] = rank
        result = {
            "analysis": "similar_cities_with_better_airport",
            "target": similarity["target"],
            "target_airport_access": _distance_only_access(target_access),
            "criteria": {
                "airport_filter": "candidate nearest distance < reference nearest distance",
                "ranking": "SSDSE cosine similarity descending",
            },
            "score_formula": None,
            "similarity_method": similarity["method"],
            "similarity_features": similarity["features"],
            "airport_access_method": {
                "method": "nearest_scheduled_airport_geodesic_distance",
                "score_formula": None,
            },
            "requested_airport_metric": "nearest_distance",
            "evaluated_candidate_count": len(similarity["ranking"]),
            "qualified_candidate_count": len(ranking),
            "ranking": ranking[:top_n],
            "evidence_source": (
                "transformed SSDSE attributes and scheduled-airport straight-line distance"
            ),
        }
        return self._attach_evidence(
            result,
            datasets=[_SSDSE_DATASET, _MUNICIPAL_OFFICE_DATASET, _AIRPORT_DATASET],
            metrics=[
                _metric(
                    "similarity",
                    "dimensionless cosine similarity [-1, 1]",
                    "cosine over configured and transformed SSDSE features",
                ),
                _metric(
                    "nearest_airport.distance_km/nearest_distance_improvement_km",
                    "km",
                    "haversine straight-line distance from main municipal office",
                ),
            ],
            limitations=[
                (
                    "Candidates are filtered to a shorter nearest-airport distance, "
                    "then ranked by similarity."
                ),
                "Distance is straight-line, not road/rail travel time or terminal access time.",
                "Similarity and distance comparisons cover only the fixed 20-city universe.",
            ],
            relation_scope="SSDSE attributes plus municipality-to-nearest-airport ACCESS_TO",
        )


def execution_is_finite(value: Any) -> bool:
    """Return whether all numeric leaves can be safely serialized as JSON."""

    if isinstance(value, Mapping):
        return all(execution_is_finite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(execution_is_finite(item) for item in value)
    if isinstance(value, float):
        return math.isfinite(value)
    return True


__all__ = [
    "CityIndex",
    "QueryExecutor",
    "execution_is_finite",
    "load_similarity_feature_specs",
]
