"""Deterministic numerical analysis for the mobility knowledge graph.

Every public analysis function returns dictionaries/lists of data facts.  An
LLM may explain those facts later, but it is never asked to calculate ranks,
centrality, communities, similarities, or airport scores.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd

from .graph import (
    ACCESS_TO,
    AIRPORT,
    FLOW_RELATIONS,
    MUNICIPALITY,
    extract_relations,
)

DEFAULT_AIRPORT_SCALE_SCORES: dict[str, float] = {
    "unknown": 1.0,
    "small": 1.0,
    "small_airport": 1.0,
    "local": 1.0,
    "other": 1.0,
    "その他": 1.0,
    "地方管理空港": 1.5,
    "medium": 2.0,
    "medium_airport": 2.0,
    "regional": 2.0,
    "地方空港": 2.0,
    "large": 3.0,
    "large_airport": 3.0,
    "major": 3.0,
    "hub": 3.0,
    "international": 3.0,
    "拠点空港": 3.0,
    "国際拠点空港": 3.0,
}

_IDENTIFIER_COLUMNS = {
    "municipality_id",
    "municipality_code",
    "prefecture",
    "name",
    "latitude",
    "longitude",
}


@dataclass(frozen=True)
class FeatureSpec:
    """Auditable transform specification for one SSDSE similarity feature.

    ``per_capita`` is applied first, then signed ``log1p``.  Missing values are
    subsequently median-imputed and each feature is population-z-scored
    (``ddof=0``) before cosine similarity is calculated.
    """

    name: str
    category: str = "other"
    per_capita: bool = False
    denominator: str | None = None
    per_capita_scale: float = 1_000.0
    log1p: bool = False


FeatureSpecs = Mapping[str, FeatureSpec | Mapping[str, Any]] | Sequence[FeatureSpec]


def _plain(value: Any) -> Any:
    """Convert numpy/pandas scalars into values suitable for JSON encoders."""

    if value is None:
        return None
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        missing = False
    if isinstance(missing, (bool, np.bool_)) and bool(missing):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except (AttributeError, ValueError):
            pass
    return value


def _finite_float(value: Any, *, field: str, nonnegative: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric; got {value!r}") from exc
    if not math.isfinite(result) or (nonnegative and result < 0):
        qualifier = "finite and non-negative" if nonnegative else "finite"
        raise ValueError(f"{field} must be {qualifier}; got {value!r}")
    return result


def _positive_int_or_none(value: int | None, *, field: str) -> int | None:
    if value is not None and value <= 0:
        raise ValueError(f"{field} must be positive or None")
    return value


def _city_fact(graph: nx.Graph, municipality_id: Any) -> dict[str, Any]:
    data = graph.nodes[municipality_id]
    return {
        "municipality_id": _plain(municipality_id),
        "name": _plain(data.get("name", data.get("label", municipality_id))),
        "prefecture": _plain(data.get("prefecture")),
    }


def _validate_city(graph: nx.Graph, municipality_id: Any) -> None:
    if municipality_id not in graph:
        raise KeyError(f"unknown municipality_id: {municipality_id!r}")
    if graph.nodes[municipality_id].get("node_type") != MUNICIPALITY:
        raise ValueError(f"node {municipality_id!r} is not a Municipality")


def _flow_relation_set(relations: str | Collection[str]) -> set[str]:
    return {relations} if isinstance(relations, str) else set(relations)


def _selected_flow_graph(
    graph: nx.MultiDiGraph,
    relations: str | Collection[str],
    *,
    year: int | str | None = None,
) -> nx.DiGraph:
    """Aggregate selected flow edges, optionally for one observation year."""

    requested = _flow_relation_set(relations)
    forbidden = requested.difference(FLOW_RELATIONS)
    if not requested:
        raise ValueError("at least one flow relation is required")
    if forbidden:
        raise ValueError(
            "flow analysis accepts only COMMUTES_TO/STUDIES_IN; got " + ", ".join(sorted(forbidden))
        )

    selected = extract_relations(
        graph,
        requested,
        node_types={MUNICIPALITY},
        include_isolates=True,
    )
    result = nx.DiGraph(
        selected_relations=tuple(sorted(requested)),
        selected_year=_plain(year),
    )
    for node, data in sorted(selected.nodes(data=True), key=lambda item: str(item[0])):
        result.add_node(node, **dict(data))

    edges = sorted(
        selected.edges(keys=True, data=True),
        key=lambda edge: (str(edge[0]), str(edge[1]), str(edge[2])),
    )
    for source, target, _key, data in edges:
        edge_year = data.get("year")
        if year is not None and str(edge_year) != str(year):
            continue
        relation = str(data.get("relation", data.get("label")))
        weight = _finite_float(data.get("weight", 0.0), field="edge weight", nonnegative=True)
        if not result.has_edge(source, target):
            result.add_edge(
                source,
                target,
                weight=0.0,
                edge_count=0,
                relation_weights={},
            )
        attrs = result[source][target]
        attrs["weight"] += weight
        attrs["edge_count"] += 1
        attrs["relation_weights"][relation] = attrs["relation_weights"].get(relation, 0.0) + weight
    return result


def rank_bidirectional_flows(
    graph: nx.MultiDiGraph,
    municipality_id: Any,
    *,
    relations: str | Collection[str] = FLOW_RELATIONS,
    year: int | str | None = None,
    top_n: int | None = 10,
) -> dict[str, Any]:
    """Rank cities by ``A -> B + B -> A`` flow using only OD relations."""

    top_n = _positive_int_or_none(top_n, field="top_n")
    _validate_city(graph, municipality_id)
    selected_relations = _flow_relation_set(relations)
    flow = _selected_flow_graph(graph, selected_relations, year=year)
    records: list[dict[str, Any]] = []
    for other in sorted(flow.nodes, key=str):
        if other == municipality_id:
            continue
        forward = flow.get_edge_data(municipality_id, other, default={})
        reverse = flow.get_edge_data(other, municipality_id, default={})
        forward_total = float(forward.get("weight", 0.0))
        reverse_total = float(reverse.get("weight", 0.0))
        total = forward_total + reverse_total
        if total <= 0:
            continue
        by_relation: dict[str, dict[str, float]] = {}
        for relation in sorted(selected_relations):
            relation_forward = float(forward.get("relation_weights", {}).get(relation, 0.0))
            relation_reverse = float(reverse.get("relation_weights", {}).get(relation, 0.0))
            by_relation[relation] = {
                "forward": relation_forward,
                "reverse": relation_reverse,
                "bidirectional": relation_forward + relation_reverse,
            }
        records.append(
            {
                **_city_fact(flow, other),
                "forward_flow": forward_total,
                "reverse_flow": reverse_total,
                "bidirectional_flow": total,
                "by_relation": by_relation,
            }
        )

    records.sort(key=lambda item: (-item["bidirectional_flow"], str(item["municipality_id"])))
    for rank, record in enumerate(records, start=1):
        record["rank"] = rank
    returned = records if top_n is None else records[:top_n]
    return {
        "analysis": "bidirectional_flow",
        "target": _city_fact(graph, municipality_id),
        "parameters": {
            "relations": sorted(selected_relations),
            "year": _plain(year),
            "top_n": top_n,
        },
        "formula": "flow(A,B) = sum(A->B) + sum(B->A)",
        "candidate_count": len(records),
        "ranking": returned,
    }


def strongest_bidirectional_flow(
    graph: nx.MultiDiGraph,
    municipality_id: Any,
    *,
    relations: str | Collection[str] = FLOW_RELATIONS,
    year: int | str | None = None,
) -> dict[str, Any]:
    """Return the strongest bidirectional counterpart plus calculation facts."""

    result = rank_bidirectional_flows(
        graph,
        municipality_id,
        relations=relations,
        year=year,
        top_n=1,
    )
    result["strongest"] = result["ranking"][0] if result["ranking"] else None
    return result


def _weighted_pagerank(
    graph: nx.DiGraph,
    *,
    damping: float,
    tolerance: float,
    max_iterations: int,
) -> tuple[dict[Any, float], int, bool]:
    """Compute weighted PageRank with numpy, including dangling-node mass."""

    if not 0 < damping < 1:
        raise ValueError("damping must be between 0 and 1")
    if tolerance <= 0:
        raise ValueError("tolerance must be positive")
    if max_iterations <= 0:
        raise ValueError("max_iterations must be positive")
    nodes = sorted(graph.nodes, key=str)
    count = len(nodes)
    if count == 0:
        return {}, 0, True

    positions = {node: index for index, node in enumerate(nodes)}
    rank = np.full(count, 1.0 / count, dtype=float)
    outgoing = np.zeros(count, dtype=float)
    weighted_edges: list[tuple[int, int, float]] = []
    for source, target, data in sorted(
        graph.edges(data=True), key=lambda edge: (str(edge[0]), str(edge[1]))
    ):
        weight = _finite_float(data.get("weight", 0.0), field="edge weight", nonnegative=True)
        if weight == 0:
            continue
        source_index = positions[source]
        outgoing[source_index] += weight
        weighted_edges.append((source_index, positions[target], weight))

    teleport = (1.0 - damping) / count
    for iteration in range(1, max_iterations + 1):
        updated = np.full(count, teleport, dtype=float)
        dangling_mass = float(rank[outgoing == 0].sum())
        updated += damping * dangling_mass / count
        for source, target, weight in weighted_edges:
            updated[target] += damping * rank[source] * weight / outgoing[source]
        error = float(np.abs(updated - rank).sum())
        rank = updated
        if error < count * tolerance:
            return {node: float(rank[positions[node]]) for node in nodes}, iteration, True
    return {node: float(rank[positions[node]]) for node in nodes}, max_iterations, False


def compute_flow_centrality(
    graph: nx.MultiDiGraph,
    *,
    relations: str | Collection[str] = FLOW_RELATIONS,
    year: int | str | None = None,
    include_betweenness: bool = False,
    damping: float = 0.85,
    tolerance: float = 1.0e-12,
    max_iterations: int = 1_000,
) -> dict[str, Any]:
    """Compute weighted degrees, PageRank, and optional flow betweenness.

    Betweenness interprets larger flows as shorter effective distances by using
    ``distance = 1 / flow_weight``.  Zero-weight edges are omitted.
    """

    selected_relations = _flow_relation_set(relations)
    flow = _selected_flow_graph(graph, selected_relations, year=year)
    pagerank, iterations, converged = _weighted_pagerank(
        flow,
        damping=damping,
        tolerance=tolerance,
        max_iterations=max_iterations,
    )
    if not converged:
        raise nx.PowerIterationFailedConvergence(max_iterations)

    weighted_in = dict(flow.in_degree(weight="weight"))
    weighted_out = dict(flow.out_degree(weight="weight"))
    weighted_degree = {
        node: float(weighted_in.get(node, 0.0) + weighted_out.get(node, 0.0)) for node in flow.nodes
    }

    betweenness: dict[Any, float] | None = None
    if include_betweenness:
        distance_graph = nx.DiGraph()
        distance_graph.add_nodes_from(sorted(flow.nodes, key=str))
        for source, target, data in sorted(
            flow.edges(data=True), key=lambda edge: (str(edge[0]), str(edge[1]))
        ):
            weight = float(data.get("weight", 0.0))
            if weight > 0:
                distance_graph.add_edge(source, target, distance=1.0 / weight)
        betweenness = nx.betweenness_centrality(
            distance_graph,
            normalized=True,
            weight="distance",
        )

    metrics: dict[str, dict[Any, float]] = {
        "weighted_in_degree": {node: float(weighted_in[node]) for node in flow.nodes},
        "weighted_out_degree": {node: float(weighted_out[node]) for node in flow.nodes},
        "weighted_degree": weighted_degree,
        "weighted_pagerank": pagerank,
    }
    if betweenness is not None:
        metrics["weighted_betweenness"] = {node: float(betweenness[node]) for node in flow.nodes}

    rankings: dict[str, list[dict[str, Any]]] = {}
    rank_lookup: dict[str, dict[Any, int]] = {}
    for metric, values in metrics.items():
        ordered = sorted(values, key=lambda node: (-values[node], str(node)))
        rank_lookup[metric] = {node: rank for rank, node in enumerate(ordered, start=1)}
        rankings[metric] = [
            {
                "rank": rank,
                **_city_fact(flow, node),
                "value": float(values[node]),
            }
            for rank, node in enumerate(ordered, start=1)
        ]

    cities = []
    for node in sorted(flow.nodes, key=str):
        city_metrics = {metric: float(values[node]) for metric, values in metrics.items()}
        cities.append(
            {
                **_city_fact(flow, node),
                "metrics": city_metrics,
                "ranks": {metric: ranks[node] for metric, ranks in rank_lookup.items()},
            }
        )
    return {
        "analysis": "flow_centrality",
        "parameters": {
            "relations": sorted(selected_relations),
            "year": _plain(year),
            "include_betweenness": include_betweenness,
            "pagerank_damping": damping,
            "pagerank_tolerance": tolerance,
            "pagerank_max_iterations": max_iterations,
        },
        "edge_scope": "COMMUTES_TO/STUDIES_IN only",
        "node_count": flow.number_of_nodes(),
        "flow_edge_count": flow.number_of_edges(),
        "pagerank_iterations": iterations,
        "cities": cities,
        "rankings": rankings,
    }


def _symmetric_flow_graph(flow: nx.DiGraph, normalization: str) -> nx.Graph:
    if normalization not in {"total", "flow_share"}:
        raise ValueError("normalization must be 'total' or 'flow_share'")
    result = nx.Graph(normalization=normalization)
    for node, data in sorted(flow.nodes(data=True), key=lambda item: str(item[0])):
        result.add_node(node, **dict(data))

    outgoing = dict(flow.out_degree(weight="weight"))
    for source, target, data in sorted(
        flow.edges(data=True), key=lambda edge: (str(edge[0]), str(edge[1]))
    ):
        if source == target:
            continue
        raw_weight = float(data.get("weight", 0.0))
        if raw_weight <= 0:
            continue
        contribution = raw_weight
        if normalization == "flow_share":
            denominator = float(outgoing.get(source, 0.0))
            if denominator <= 0:
                continue
            contribution = raw_weight / denominator
        if result.has_edge(source, target):
            result[source][target]["weight"] += contribution
            result[source][target]["raw_bidirectional_flow"] += raw_weight
        else:
            result.add_edge(
                source,
                target,
                weight=contribution,
                raw_bidirectional_flow=raw_weight,
            )
    return result


def detect_flow_communities(
    graph: nx.MultiDiGraph,
    *,
    relations: str | Collection[str] = FLOW_RELATIONS,
    year: int | str | None = None,
    normalization: str = "total",
    resolution: float = 1.0,
    seed: int = 42,
    top_cross_prefecture_links: int | None = 10,
) -> dict[str, Any]:
    """Detect deterministic Louvain communities on a symmetric flow graph.

    ``total`` uses ``flow(u,v) + flow(v,u)``.  ``flow_share`` first divides
    every directed edge by its source's total outgoing flow and then adds both
    directions.  The latter reduces domination by large source populations.
    """

    top_cross_prefecture_links = _positive_int_or_none(
        top_cross_prefecture_links, field="top_cross_prefecture_links"
    )
    if resolution <= 0:
        raise ValueError("resolution must be positive")
    selected_relations = _flow_relation_set(relations)
    flow = _selected_flow_graph(graph, selected_relations, year=year)
    symmetric = _symmetric_flow_graph(flow, normalization)

    connected_nodes = [node for node, degree in symmetric.degree() if degree > 0]
    isolates = sorted(set(symmetric.nodes).difference(connected_nodes), key=str)
    communities: list[set[Any]] = []
    if connected_nodes:
        active = symmetric.subgraph(sorted(connected_nodes, key=str)).copy()
        communities.extend(
            set(group)
            for group in nx.community.louvain_communities(
                active,
                weight="weight",
                resolution=resolution,
                seed=seed,
            )
        )
    communities.extend({node} for node in isolates)
    communities.sort(
        key=lambda group: (
            -len(group),
            tuple(str(node) for node in sorted(group, key=str)),
        )
    )

    assignment: dict[Any, str] = {}
    community_records: list[dict[str, Any]] = []
    for index, members in enumerate(communities, start=1):
        community_id = f"community_{index:03d}"
        ordered_members = sorted(members, key=str)
        for member in ordered_members:
            assignment[member] = community_id
        prefectures = sorted(
            {
                str(symmetric.nodes[member].get("prefecture"))
                for member in ordered_members
                if symmetric.nodes[member].get("prefecture") is not None
            }
        )
        internal_weight = sum(
            float(data.get("weight", 0.0))
            for source, target, data in symmetric.subgraph(ordered_members).edges(data=True)
        )
        community_records.append(
            {
                "community_id": community_id,
                "size": len(ordered_members),
                "municipalities": [_city_fact(symmetric, member) for member in ordered_members],
                "prefectures": prefectures,
                "cross_prefecture": len(prefectures) > 1,
                "internal_symmetric_weight": internal_weight,
            }
        )

    cross_links: list[dict[str, Any]] = []
    for source, target, data in symmetric.edges(data=True):
        source_prefecture = symmetric.nodes[source].get("prefecture")
        target_prefecture = symmetric.nodes[target].get("prefecture")
        if source_prefecture == target_prefecture or assignment[source] != assignment[target]:
            continue
        cross_links.append(
            {
                "community_id": assignment[source],
                "source": _city_fact(symmetric, source),
                "target": _city_fact(symmetric, target),
                "bidirectional_total_flow": float(data.get("raw_bidirectional_flow", 0.0)),
                "community_weight": float(data.get("weight", 0.0)),
            }
        )
    cross_links.sort(
        key=lambda item: (
            -item["bidirectional_total_flow"],
            str(item["source"]["municipality_id"]),
            str(item["target"]["municipality_id"]),
        )
    )
    if top_cross_prefecture_links is not None:
        cross_links = cross_links[:top_cross_prefecture_links]

    modularity = None
    if symmetric.number_of_edges() > 0:
        modularity = float(
            nx.community.modularity(
                symmetric,
                communities,
                weight="weight",
                resolution=resolution,
            )
        )
    return {
        "analysis": "flow_communities",
        "algorithm": "Louvain",
        "parameters": {
            "relations": sorted(selected_relations),
            "year": _plain(year),
            "normalization": normalization,
            "resolution": resolution,
            "seed": seed,
        },
        "weight_formula": (
            "w(u,v) = flow(u->v) + flow(v->u)"
            if normalization == "total"
            else "w(u,v) = flow(u->v)/outflow(u) + flow(v->u)/outflow(v)"
        ),
        "modularity": modularity,
        "community_count": len(community_records),
        "assignment": {str(node): community for node, community in assignment.items()},
        "communities": community_records,
        "cross_prefecture_communities": [
            community for community in community_records if community["cross_prefecture"]
        ],
        "cross_prefecture_links": cross_links,
    }


def _infer_population_column(frame: pd.DataFrame) -> str | None:
    exact = (
        "population",
        "total_population",
        "総人口",
        "人口総数",
    )
    for column in exact:
        if column in frame.columns:
            return column
    lowered = {str(column).lower(): str(column) for column in frame.columns}
    for key, column in lowered.items():
        if ("population" in key and "total" in key) or "総人口" in key or "人口総数" in key:
            return column
    return None


def _infer_category(name: str) -> str:
    lowered = name.lower()
    categories = (
        ("medical", ("medical", "hospital", "doctor", "clinic", "医療", "病院", "医師")),
        ("education", ("education", "school", "student", "教育", "学校", "生徒", "学生")),
        ("economy", ("econom", "income", "employment", "worker", "経済", "所得", "就業", "労働")),
        ("welfare", ("welfare", "care", "nursery", "福祉", "介護", "保育")),
        ("population", ("population", "age", "人口", "年齢", "世帯")),
    )
    for category, keywords in categories:
        if any(keyword in lowered for keyword in keywords):
            return category
    return "other"


def _looks_like_rate(name: str) -> bool:
    lowered = name.lower()
    return any(
        token in lowered
        for token in (
            "rate",
            "ratio",
            "share",
            "percent",
            "pct",
            "density",
            "average",
            "_per_",
            "率",
            "割合",
            "比率",
            "平均",
            "密度",
        )
    )


def _resolve_feature_specs(
    frame: pd.DataFrame,
    *,
    feature_specs: FeatureSpecs | None,
    features: Sequence[str] | None,
    category_map: Mapping[str, str] | None,
    per_capita_features: Collection[str] | None,
    log_features: Collection[str] | None,
    population_column: str | None,
) -> tuple[list[FeatureSpec], str | None, str]:
    category_map = category_map or {}
    per_capita = set(per_capita_features or ())
    logarithmic = set(log_features or ())
    population_column = population_column or _infer_population_column(frame)

    specs: list[FeatureSpec] = []
    mode = "explicit"
    if feature_specs is not None:
        if isinstance(feature_specs, Mapping):
            for name in sorted(feature_specs):
                raw = feature_specs[name]
                if isinstance(raw, FeatureSpec):
                    spec = raw
                else:
                    values = dict(raw)
                    values.setdefault("name", name)
                    spec = FeatureSpec(**values)
                specs.append(spec)
        else:
            specs.extend(feature_specs)
    else:
        selected = (
            list(features)
            if features is not None
            else [
                str(column)
                for column in frame.select_dtypes(include=[np.number]).columns
                if str(column) not in _IDENTIFIER_COLUMNS
            ]
        )
        if not selected:
            # Object-typed numeric columns are common after mixed-source joins.
            selected = [
                str(column)
                for column in frame.columns
                if str(column) not in _IDENTIFIER_COLUMNS
                and pd.to_numeric(frame[column], errors="coerce").notna().any()
            ]
        mode = "explicit_columns" if features is not None else "inferred"
        for name in selected:
            is_population = name == population_column
            ratio_like = _looks_like_rate(name)
            auto_per_capita = bool(population_column) and not is_population and not ratio_like
            auto_log = is_population or auto_per_capita
            specs.append(
                FeatureSpec(
                    name=name,
                    category=category_map.get(name, _infer_category(name)),
                    per_capita=name in per_capita or (not per_capita and auto_per_capita),
                    denominator=(
                        population_column if name in per_capita or auto_per_capita else None
                    ),
                    log1p=name in logarithmic or (not logarithmic and auto_log),
                )
            )

    overridden: list[FeatureSpec] = []
    for spec in specs:
        use_per_capita = spec.per_capita or spec.name in per_capita
        overridden.append(
            FeatureSpec(
                name=spec.name,
                category=category_map.get(spec.name, spec.category),
                per_capita=use_per_capita,
                denominator=(spec.denominator or (population_column if use_per_capita else None)),
                per_capita_scale=spec.per_capita_scale,
                log1p=spec.log1p or spec.name in logarithmic,
            )
        )
    specs = overridden

    if not specs:
        raise ValueError("no similarity features were selected")
    names = [spec.name for spec in specs]
    if len(names) != len(set(names)):
        raise ValueError("feature specs contain duplicate names")
    missing = sorted(set(names).difference(frame.columns))
    if missing:
        raise ValueError(f"similarity features not found: {', '.join(missing)}")
    for spec in specs:
        if spec.per_capita:
            if not spec.denominator:
                raise ValueError(f"feature {spec.name!r} needs a per-capita denominator")
            if spec.denominator not in frame.columns:
                raise ValueError(
                    f"denominator {spec.denominator!r} for {spec.name!r} is not in the table"
                )
            if spec.per_capita_scale <= 0:
                raise ValueError(f"per_capita_scale for {spec.name!r} must be positive")
    return sorted(specs, key=lambda spec: spec.name), population_column, mode


def _prepare_similarity_matrix(
    frame: pd.DataFrame,
    specs: Sequence[FeatureSpec],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    columns: dict[str, pd.Series] = {}
    metadata: list[dict[str, Any]] = []
    for spec in specs:
        values = pd.to_numeric(frame[spec.name], errors="coerce").astype(float)
        if spec.per_capita:
            denominator = pd.to_numeric(frame[spec.denominator], errors="coerce").astype(float)
            denominator = denominator.where(denominator > 0)
            values = values / denominator * spec.per_capita_scale
        if spec.log1p:
            array = values.to_numpy(dtype=float)
            values = pd.Series(
                np.sign(array) * np.log1p(np.abs(array)),
                index=values.index,
                name=values.name,
            )
        values = values.replace([np.inf, -np.inf], np.nan)
        missing_count = int(values.isna().sum())
        median = values.median(skipna=True)
        all_missing = pd.isna(median)
        median_value = 0.0 if all_missing else float(median)
        imputed = values.fillna(median_value)
        mean = float(imputed.mean())
        std = float(imputed.std(ddof=0))
        zero_variance = bool(not math.isfinite(std) or std <= np.finfo(float).eps)
        z_score = pd.Series(0.0, index=frame.index) if zero_variance else (imputed - mean) / std
        columns[spec.name] = z_score.astype(float)
        metadata.append(
            {
                "feature": spec.name,
                "category": spec.category,
                "steps": [
                    *(
                        [
                            {
                                "operation": "per_capita",
                                "denominator": spec.denominator,
                                "scale": spec.per_capita_scale,
                            }
                        ]
                        if spec.per_capita
                        else []
                    ),
                    *([{"operation": "signed_log1p"}] if spec.log1p else []),
                    {"operation": "median_impute", "median": median_value},
                    {"operation": "z_score", "ddof": 0, "mean": mean, "std": std},
                ],
                "missing_values_imputed": missing_count,
                "all_values_missing": bool(all_missing),
                "zero_variance": zero_variance,
            }
        )
    return pd.DataFrame(columns, index=frame.index), metadata


def _cosine(left: np.ndarray, right: np.ndarray) -> float | None:
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator <= np.finfo(float).eps:
        return None
    # Floating-point round-off can otherwise produce values such as
    # 1.0000000000000002, outside cosine similarity's mathematical range.
    return float(np.clip(np.dot(left, right) / denominator, -1.0, 1.0))


def city_similarity(
    municipalities: pd.DataFrame,
    target_id: Any,
    *,
    feature_specs: FeatureSpecs | None = None,
    features: Sequence[str] | None = None,
    category_map: Mapping[str, str] | None = None,
    per_capita_features: Collection[str] | None = None,
    log_features: Collection[str] | None = None,
    population_column: str | None = None,
    top_n: int | None = 10,
) -> dict[str, Any]:
    """Rank municipalities by standardized SSDSE cosine similarity.

    For fully auditable production use, pass ``feature_specs``.  When omitted,
    numeric SSDSE columns are inferred: rate/ratio/density fields remain as-is;
    total population is log-transformed; other count-like fields are converted
    per 1,000 residents and log-transformed when a population column is found.
    The returned transform metadata records every actual choice.
    """

    top_n = _positive_int_or_none(top_n, field="top_n")
    required = {"municipality_id", "name", "prefecture"}
    missing = sorted(required.difference(municipalities.columns))
    if missing:
        raise ValueError(f"municipalities is missing required columns: {', '.join(missing)}")
    # Row labels are not part of the processed schema and may be duplicated after
    # concatenating source tables.  Positional reset keeps every vector scalar.
    municipalities = municipalities.reset_index(drop=True)
    duplicated = municipalities["municipality_id"].duplicated(keep=False)
    if duplicated.any():
        values = municipalities.loc[duplicated, "municipality_id"].astype(str).unique()
        raise ValueError(f"duplicate municipality_id values: {', '.join(sorted(values))}")
    matches = municipalities.index[municipalities["municipality_id"] == target_id].tolist()
    if not matches:
        raise KeyError(f"unknown municipality_id: {target_id!r}")
    target_index = matches[0]

    specs, resolved_population, selection_mode = _resolve_feature_specs(
        municipalities,
        feature_specs=feature_specs,
        features=features,
        category_map=category_map,
        per_capita_features=per_capita_features,
        log_features=log_features,
        population_column=population_column,
    )
    matrix, transformations = _prepare_similarity_matrix(municipalities, specs)
    target_vector = matrix.loc[target_index].to_numpy(dtype=float)
    category_columns: dict[str, list[str]] = {}
    for spec in specs:
        category_columns.setdefault(spec.category, []).append(spec.name)

    rankings: list[dict[str, Any]] = []
    for index, row in municipalities.iterrows():
        municipality_id = row["municipality_id"]
        if municipality_id == target_id:
            continue
        candidate_vector = matrix.loc[index].to_numpy(dtype=float)
        score = _cosine(target_vector, candidate_vector)
        category_scores: dict[str, float | None] = {}
        for category, columns in sorted(category_columns.items()):
            category_scores[category] = _cosine(
                matrix.loc[target_index, columns].to_numpy(dtype=float),
                matrix.loc[index, columns].to_numpy(dtype=float),
            )
        rankings.append(
            {
                "municipality_id": _plain(municipality_id),
                "name": _plain(row["name"]),
                "prefecture": _plain(row["prefecture"]),
                "similarity": score,
                "category_scores": category_scores,
            }
        )
    rankings.sort(
        key=lambda item: (
            item["similarity"] is None,
            -(item["similarity"] if item["similarity"] is not None else -math.inf),
            str(item["municipality_id"]),
        )
    )
    for rank, record in enumerate(rankings, start=1):
        record["rank"] = rank
    returned = rankings if top_n is None else rankings[:top_n]
    target_row = municipalities.loc[target_index]
    return {
        "analysis": "city_similarity",
        "target": {
            "municipality_id": _plain(target_id),
            "name": _plain(target_row["name"]),
            "prefecture": _plain(target_row["prefecture"]),
        },
        "method": "cosine_similarity_on_transformed_ssdse_features",
        "transform_pipeline": [
            "per_capita_as_configured",
            "signed_log1p_as_configured",
            "median_impute",
            "z_score_ddof_0",
            "cosine_similarity",
        ],
        "feature_selection": selection_mode,
        "population_column": resolved_population,
        "feature_count": len(specs),
        "features": transformations,
        "candidate_count": len(rankings),
        "ranking": returned,
    }


def _normalize_scale_key(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _airport_scale_score(
    value: Any,
    custom_scores: Mapping[str, float] | None,
) -> float:
    if value is not None:
        try:
            return _finite_float(value, field="airport_scale", nonnegative=True)
        except ValueError:
            pass
    scores = dict(DEFAULT_AIRPORT_SCALE_SCORES)
    if custom_scores:
        scores.update(
            {
                _normalize_scale_key(key): _finite_float(
                    score, field=f"airport scale score {key!r}", nonnegative=True
                )
                for key, score in custom_scores.items()
            }
        )
    key = _normalize_scale_key(value if value is not None else "unknown")
    return float(scores.get(key, scores["unknown"]))


def _airport_access_records(
    graph: nx.MultiDiGraph,
    *,
    municipality_ids: Collection[Any] | None,
    airport_scale_scores: Mapping[str, float] | None,
    distance_decay_km: float,
    max_access_rank: int | None,
) -> tuple[list[dict[str, Any]], list[Any]]:
    if distance_decay_km <= 0:
        raise ValueError("distance_decay_km must be positive")
    requested = (
        set(municipality_ids)
        if municipality_ids is not None
        else {
            node for node, data in graph.nodes(data=True) if data.get("node_type") == MUNICIPALITY
        }
    )
    for municipality_id in requested:
        _validate_city(graph, municipality_id)

    access = extract_relations(graph, ACCESS_TO, include_isolates=False)
    options: dict[Any, list[dict[str, Any]]] = {node: [] for node in requested}
    for source, target, _key, data in sorted(
        access.edges(keys=True, data=True),
        key=lambda edge: (str(edge[0]), str(edge[1]), str(edge[2])),
    ):
        if source not in requested:
            continue
        if graph.nodes[source].get("node_type") != MUNICIPALITY:
            continue
        if graph.nodes[target].get("node_type") != AIRPORT:
            continue
        if graph.nodes[target].get("scheduled_service") is not True:
            continue
        access_rank = data.get("rank")
        if (
            max_access_rank is not None
            and access_rank is not None
            and _finite_float(access_rank, field="ACCESS_TO.rank", nonnegative=True)
            > max_access_rank
        ):
            continue
        distance = _finite_float(
            data.get("distance_km"), field="ACCESS_TO.distance_km", nonnegative=True
        )
        airport = graph.nodes[target]
        scale = data.get("airport_scale", airport.get("airport_scale"))
        scale_score = _airport_scale_score(scale, airport_scale_scores)
        access_score = scale_score / (1.0 + distance / distance_decay_km)
        options[source].append(
            {
                "airport_id": _plain(target),
                "name": _plain(airport.get("name", airport.get("label", target))),
                "airport_type": _plain(airport.get("airport_type")),
                "airport_scale": _plain(scale),
                "airport_scale_score": scale_score,
                "scheduled_service": _plain(airport.get("scheduled_service")),
                "distance_km": distance,
                "source_rank": _plain(access_rank),
                "access_score": access_score,
            }
        )

    records: list[dict[str, Any]] = []
    missing: list[Any] = []
    for municipality_id in sorted(requested, key=str):
        choices = options[municipality_id]
        if not choices:
            missing.append(_plain(municipality_id))
            continue
        nearest = min(
            choices,
            key=lambda option: (
                option["distance_km"],
                -option["airport_scale_score"],
                str(option["airport_id"]),
            ),
        )
        best = min(
            choices,
            key=lambda option: (
                -option["access_score"],
                option["distance_km"],
                str(option["airport_id"]),
            ),
        )
        records.append(
            {
                **_city_fact(graph, municipality_id),
                "access_score": float(best["access_score"]),
                "nearest_airport": dict(nearest),
                "best_scored_airport": dict(best),
                "airports_considered": len(choices),
            }
        )
    records.sort(key=lambda item: (-item["access_score"], str(item["municipality_id"])))
    return records, missing


def rank_airport_access(
    graph: nx.MultiDiGraph,
    *,
    municipality_ids: Collection[Any] | None = None,
    airport_scale_scores: Mapping[str, float] | None = None,
    distance_decay_km: float = 50.0,
    max_access_rank: int | None = None,
    top_n: int | None = None,
) -> dict[str, Any]:
    """Rank municipalities using reproducible distance-and-scale evidence.

    Each city reports its literally nearest airport and its best scored airport.
    The ranking score is ``scale_score / (1 + distance_km / decay_km)``.
    """

    top_n = _positive_int_or_none(top_n, field="top_n")
    max_access_rank = _positive_int_or_none(max_access_rank, field="max_access_rank")
    records, missing = _airport_access_records(
        graph,
        municipality_ids=municipality_ids,
        airport_scale_scores=airport_scale_scores,
        distance_decay_km=distance_decay_km,
        max_access_rank=max_access_rank,
    )
    for rank, record in enumerate(records, start=1):
        record["rank"] = rank
    returned = records if top_n is None else records[:top_n]
    return {
        "analysis": "airport_access",
        "method": "distance_decay_with_airport_scale",
        "score_formula": "airport_scale_score / (1 + distance_km / distance_decay_km)",
        "parameters": {
            "distance_decay_km": distance_decay_km,
            "max_access_rank": max_access_rank,
            "top_n": top_n,
            "custom_airport_scale_scores": (
                dict(airport_scale_scores) if airport_scale_scores is not None else None
            ),
        },
        "ranked_city_count": len(records),
        "missing_access_city_ids": missing,
        "ranking": returned,
    }


def find_similar_cities_with_better_airport(
    municipalities: pd.DataFrame,
    graph: nx.MultiDiGraph,
    target_id: Any,
    *,
    feature_specs: FeatureSpecs | None = None,
    features: Sequence[str] | None = None,
    category_map: Mapping[str, str] | None = None,
    per_capita_features: Collection[str] | None = None,
    log_features: Collection[str] | None = None,
    population_column: str | None = None,
    airport_scale_scores: Mapping[str, float] | None = None,
    distance_decay_km: float = 50.0,
    max_access_rank: int | None = None,
    min_similarity: float = 0.0,
    min_access_score_gain: float = 0.0,
    similarity_weight: float = 0.75,
    require_nearer: bool = False,
    top_n: int | None = 10,
) -> dict[str, Any]:
    """Find cities similar to a target but with objectively better airport access.

    Evidence includes separate similarity, category similarity, target/candidate
    airport facts, access-score delta, and (optionally) literal distance
    improvement.  ``composite_score`` is only a ranking aid; the raw evidence is
    always returned alongside it.
    """

    top_n = _positive_int_or_none(top_n, field="top_n")
    if not -1.0 <= min_similarity <= 1.0:
        raise ValueError("min_similarity must be between -1 and 1")
    if min_access_score_gain < 0:
        raise ValueError("min_access_score_gain must be non-negative")
    if not 0 <= similarity_weight <= 1:
        raise ValueError("similarity_weight must be between 0 and 1")

    similarity = city_similarity(
        municipalities,
        target_id,
        feature_specs=feature_specs,
        features=features,
        category_map=category_map,
        per_capita_features=per_capita_features,
        log_features=log_features,
        population_column=population_column,
        top_n=None,
    )
    airport = rank_airport_access(
        graph,
        airport_scale_scores=airport_scale_scores,
        distance_decay_km=distance_decay_km,
        max_access_rank=max_access_rank,
        top_n=None,
    )
    access_by_id = {record["municipality_id"]: record for record in airport["ranking"]}
    if target_id not in access_by_id:
        raise ValueError(f"target municipality {target_id!r} has no ACCESS_TO evidence")
    target_access = access_by_id[target_id]
    target_score = float(target_access["access_score"])
    target_distance = float(target_access["nearest_airport"]["distance_km"])

    evidence: list[dict[str, Any]] = []
    evaluated = 0
    for similar in similarity["ranking"]:
        candidate_id = similar["municipality_id"]
        candidate_access = access_by_id.get(candidate_id)
        if candidate_access is None or similar["similarity"] is None:
            continue
        evaluated += 1
        similarity_score = float(similar["similarity"])
        candidate_score = float(candidate_access["access_score"])
        score_gain = candidate_score - target_score
        candidate_distance = float(candidate_access["nearest_airport"]["distance_km"])
        distance_gain = target_distance - candidate_distance
        better_score = score_gain > min_access_score_gain
        nearer = distance_gain > 0
        qualifies = (
            similarity_score >= min_similarity and better_score and (nearer or not require_nearer)
        )
        if not qualifies:
            continue

        gain_ratio = score_gain / max(abs(target_score), np.finfo(float).eps)
        normalized_gain = gain_ratio / (1.0 + gain_ratio) if gain_ratio > 0 else 0.0
        normalized_similarity = min(1.0, max(0.0, (similarity_score + 1.0) / 2.0))
        composite_score = (
            similarity_weight * normalized_similarity + (1.0 - similarity_weight) * normalized_gain
        )
        evidence.append(
            {
                "municipality_id": candidate_id,
                "name": similar["name"],
                "prefecture": similar["prefecture"],
                "similarity": similarity_score,
                "category_scores": similar["category_scores"],
                "candidate_airport_access": candidate_access,
                "target_airport_access": target_access,
                "access_score_gain": score_gain,
                "access_score_gain_ratio": gain_ratio,
                "nearest_distance_improvement_km": distance_gain,
                "is_nearer": nearer,
                "composite_score": float(composite_score),
            }
        )
    evidence.sort(
        key=lambda item: (
            -item["composite_score"],
            -item["similarity"],
            str(item["municipality_id"]),
        )
    )
    for rank, record in enumerate(evidence, start=1):
        record["rank"] = rank
    returned = evidence if top_n is None else evidence[:top_n]
    return {
        "analysis": "similar_cities_with_better_airport",
        "target": similarity["target"],
        "target_airport_access": target_access,
        "criteria": {
            "min_similarity": min_similarity,
            "min_access_score_gain": min_access_score_gain,
            "require_nearer": require_nearer,
            "similarity_weight": similarity_weight,
        },
        "score_formula": (
            "similarity_weight * ((cosine + 1) / 2) + "
            "(1 - similarity_weight) * bounded_relative_access_gain"
        ),
        "similarity_method": similarity["method"],
        "similarity_features": similarity["features"],
        "airport_access_method": {
            "method": airport["method"],
            "score_formula": airport["score_formula"],
            "distance_decay_km": distance_decay_km,
        },
        "evaluated_candidate_count": evaluated,
        "qualified_candidate_count": len(evidence),
        "ranking": returned,
    }


# Short aliases keep query-planner wiring readable.
flow_centrality = compute_flow_centrality
louvain_flow_communities = detect_flow_communities
rank_similar_cities = city_similarity
similar_but_better_airport = find_similar_cities_with_better_airport


__all__ = [
    "DEFAULT_AIRPORT_SCALE_SCORES",
    "FeatureSpec",
    "city_similarity",
    "compute_flow_centrality",
    "detect_flow_communities",
    "find_similar_cities_with_better_airport",
    "flow_centrality",
    "louvain_flow_communities",
    "rank_airport_access",
    "rank_bidirectional_flows",
    "rank_similar_cities",
    "similar_but_better_airport",
    "strongest_bidirectional_flow",
]
