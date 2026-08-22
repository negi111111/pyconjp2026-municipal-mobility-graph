"""Relation-aware NetworkX graph construction for the mobility project.

The full knowledge graph is intentionally a :class:`networkx.MultiDiGraph`:
the same pair of municipalities may have both ``COMMUTES_TO`` and
``STUDIES_IN`` edges.  Analysis code must call :func:`extract_flow_graph`
instead of running flow algorithms on the full graph.  That boundary keeps
``IS_IN`` and ``ACCESS_TO`` edges out of centrality and community detection.

Node identifiers remain compatible with the original project: municipality
IDs are the processed ``municipality_id`` values (for example ``R34100``) and
prefecture IDs are prefecture names.  ``IS_IN`` follows the original graph's
direction, ``Municipality -> Prefecture``.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Iterable, Mapping
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd

MUNICIPALITY = "Municipality"
PREFECTURE = "Prefecture"
AIRPORT = "Airport"

IS_IN = "IS_IN"
COMMUTES_TO = "COMMUTES_TO"
STUDIES_IN = "STUDIES_IN"
ACCESS_TO = "ACCESS_TO"

FLOW_RELATIONS = frozenset({COMMUTES_TO, STUDIES_IN})
ALL_RELATIONS = frozenset({IS_IN, COMMUTES_TO, STUDIES_IN, ACCESS_TO})


def _is_missing(value: Any) -> bool:
    """Return whether *value* is a scalar missing value."""

    if value is None:
        return True
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(missing) if isinstance(missing, (bool, type(pd.NA))) else False


def _python_value(value: Any) -> Any:
    """Convert common pandas/numpy scalar values into plain Python values."""

    if _is_missing(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except (AttributeError, ValueError):
            pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _clean_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a table record while omitting missing values."""

    return {
        str(key): _python_value(value) for key, value in record.items() if not _is_missing(value)
    }


def _require_columns(frame: pd.DataFrame, columns: Collection[str], table: str) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise ValueError(f"{table} is missing required columns: {', '.join(missing)}")


def _records(frame: pd.DataFrame, sort_columns: Iterable[str]) -> list[dict[str, Any]]:
    """Return records in a stable order without mutating the input frame."""

    records = frame.to_dict(orient="records")
    columns = tuple(column for column in sort_columns if column in frame.columns)
    return sorted(records, key=lambda row: tuple(str(row.get(column, "")) for column in columns))


def _identifier(value: Any, *, table: str, column: str) -> Any:
    value = _python_value(value)
    if value is None or str(value).strip() == "":
        raise ValueError(f"{table}.{column} contains an empty identifier")
    return value


def _nonnegative_number(value: Any, *, table: str, column: str) -> float:
    if _is_missing(value):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{table}.{column} must be numeric; got {value!r}") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{table}.{column} must be finite and non-negative; got {value!r}")
    return number


def _edge_key(
    graph: nx.MultiDiGraph,
    source: Any,
    target: Any,
    relation: str,
    year: Any = None,
) -> str:
    """Create a deterministic, non-overwriting key for a parallel edge."""

    # Keep the common one-row case ergonomic: callers can address
    # graph[u][v]["COMMUTES_TO"] directly.  A year/suffix is introduced only
    # when the same relation has multiple observations for the same pair.
    if not graph.has_edge(source, target, key=relation):
        return relation
    base = relation if year is None else f"{relation}:{year}"
    if base != relation and not graph.has_edge(source, target, key=base):
        return base
    suffix = 2
    while graph.has_edge(source, target, key=f"{base}:{suffix}"):
        suffix += 1
    return f"{base}:{suffix}"


def _ensure_endpoint(
    graph: nx.MultiDiGraph,
    node_id: Any,
    node_type: str,
    *,
    strict: bool,
    row: Mapping[str, Any],
    side: str,
) -> None:
    """Validate an endpoint or add a labelled placeholder in non-strict mode."""

    if node_id in graph:
        actual = graph.nodes[node_id].get("node_type")
        if actual != node_type:
            raise ValueError(
                f"edge endpoint {node_id!r} has node_type={actual!r}, expected {node_type!r}"
            )
        return
    if strict:
        raise ValueError(f"edge references unknown {node_type} node {node_id!r}")

    name = row.get(f"{side}_name", node_id)
    prefecture = row.get(f"{side}_prefecture")
    attrs: dict[str, Any] = {
        "node_type": node_type,
        "type": node_type,
        "name": _python_value(name),
        "label": _python_value(name),
        "placeholder": True,
    }
    if prefecture is not None and not _is_missing(prefecture):
        attrs["prefecture"] = _python_value(prefecture)
    graph.add_node(node_id, **attrs)


def _add_flow_edges(
    graph: nx.MultiDiGraph,
    frame: pd.DataFrame | None,
    *,
    relation: str,
    value_column: str,
    table: str,
    strict: bool,
) -> None:
    if frame is None or frame.empty:
        return
    _require_columns(frame, {"source", "target", value_column}, table)

    for row in _records(frame, ("source", "target", "year", value_column)):
        source = _identifier(row["source"], table=table, column="source")
        target = _identifier(row["target"], table=table, column="target")
        _ensure_endpoint(graph, source, MUNICIPALITY, strict=strict, row=row, side="source")
        _ensure_endpoint(graph, target, MUNICIPALITY, strict=strict, row=row, side="target")

        weight = _nonnegative_number(row[value_column], table=table, column=value_column)
        attrs = _clean_record(row)
        attrs.update({"relation": relation, "label": relation, "weight": weight})
        attrs[value_column] = weight
        key = _edge_key(graph, source, target, relation, attrs.get("year"))
        graph.add_edge(source, target, key=key, **attrs)


def build_mobility_graph(
    municipalities: pd.DataFrame,
    flow_edges: pd.DataFrame | None = None,
    commute_edges: pd.DataFrame | None = None,
    study_edges: pd.DataFrame | None = None,
    airports: pd.DataFrame | None = None,
    airport_access: pd.DataFrame | None = None,
    *,
    strict: bool = True,
) -> nx.MultiDiGraph:
    """Build the project's layered knowledge graph from processed tables.

    Parameters
    ----------
    municipalities:
        Table with ``municipality_id``, ``municipality_code``, ``prefecture``,
        ``name``, ``latitude`` and ``longitude`` plus any SSDSE attributes.
    flow_edges:
        Combined OD table.  It is used to derive missing commute/study layers.
        If a non-empty ``commute_edges`` or ``study_edges`` table is supplied,
        that table takes precedence for its relation and avoids double counting.
    strict:
        In strict mode (the default), every edge endpoint must be present in its
        node table.  Non-strict mode adds clearly marked municipality/airport
        placeholders, which can be useful during source-data diagnosis.

    Returns
    -------
    networkx.MultiDiGraph
        A graph whose edges always carry both ``relation`` and ``weight``.
    """

    _require_columns(
        municipalities,
        {
            "municipality_id",
            "municipality_code",
            "prefecture",
            "name",
            "latitude",
            "longitude",
        },
        "municipalities",
    )

    graph = nx.MultiDiGraph(
        name="PyConJP2026 mobility knowledge graph",
        schema_version="1",
        flow_relations=tuple(sorted(FLOW_RELATIONS)),
    )

    for row in _records(municipalities, ("municipality_id",)):
        municipality_id = _identifier(
            row["municipality_id"], table="municipalities", column="municipality_id"
        )
        if municipality_id in graph:
            raise ValueError(f"duplicate municipality_id: {municipality_id!r}")
        attrs = _clean_record(row)
        attrs.update(
            {
                "node_type": MUNICIPALITY,
                "type": MUNICIPALITY,
                "name": _python_value(row["name"]),
                "label": _python_value(row["name"]),
            }
        )
        graph.add_node(municipality_id, **attrs)

    prefectures = sorted(
        {
            _identifier(value, table="municipalities", column="prefecture")
            for value in municipalities["prefecture"].tolist()
        },
        key=str,
    )
    for prefecture in prefectures:
        if prefecture in graph:
            raise ValueError(f"prefecture ID collides with another node: {prefecture!r}")
        graph.add_node(
            prefecture,
            node_type=PREFECTURE,
            type=PREFECTURE,
            name=prefecture,
            label=prefecture,
        )

    for row in _records(municipalities, ("municipality_id",)):
        municipality_id = _identifier(
            row["municipality_id"], table="municipalities", column="municipality_id"
        )
        prefecture = _identifier(row["prefecture"], table="municipalities", column="prefecture")
        graph.add_edge(
            municipality_id,
            prefecture,
            key=IS_IN,
            relation=IS_IN,
            label=IS_IN,
            weight=1.0,
        )

    if airports is not None and not airports.empty:
        _require_columns(
            airports,
            {
                "airport_id",
                "name",
                "latitude",
                "longitude",
                "airport_type",
                "airport_scale",
                "scheduled_service",
                "source_url",
            },
            "airports",
        )
        for row in _records(airports, ("airport_id",)):
            airport_id = _identifier(row["airport_id"], table="airports", column="airport_id")
            if airport_id in graph:
                raise ValueError(f"airport_id collides with another node: {airport_id!r}")
            attrs = _clean_record(row)
            attrs.update(
                {
                    "node_type": AIRPORT,
                    "type": AIRPORT,
                    "name": _python_value(row["name"]),
                    "label": _python_value(row["name"]),
                }
            )
            graph.add_node(airport_id, **attrs)

    if airport_access is not None and not airport_access.empty:
        _require_columns(
            airport_access,
            {"source", "target", "distance_km", "airport_scale", "rank"},
            "airport_access",
        )
        for row in _records(airport_access, ("source", "rank", "target")):
            source = _identifier(row["source"], table="airport_access", column="source")
            target = _identifier(row["target"], table="airport_access", column="target")
            _ensure_endpoint(graph, source, MUNICIPALITY, strict=strict, row=row, side="source")
            _ensure_endpoint(graph, target, AIRPORT, strict=strict, row=row, side="target")
            distance = _nonnegative_number(
                row["distance_km"], table="airport_access", column="distance_km"
            )
            attrs = _clean_record(row)
            attrs.update(
                {
                    "relation": ACCESS_TO,
                    "label": ACCESS_TO,
                    "distance_km": distance,
                    # A graph weight must increase with connection strength.
                    "weight": 1.0 / (1.0 + distance),
                }
            )
            key = _edge_key(graph, source, target, ACCESS_TO)
            graph.add_edge(source, target, key=key, **attrs)

    commute_source = (
        commute_edges if commute_edges is not None and not commute_edges.empty else flow_edges
    )
    study_source = study_edges if study_edges is not None and not study_edges.empty else flow_edges
    _add_flow_edges(
        graph,
        commute_source,
        relation=COMMUTES_TO,
        value_column="commuters",
        table="commute_edges" if commute_source is commute_edges else "flow_edges",
        strict=strict,
    )
    _add_flow_edges(
        graph,
        study_source,
        relation=STUDIES_IN,
        value_column="students",
        table="study_edges" if study_source is study_edges else "flow_edges",
        strict=strict,
    )
    return graph


def extract_relations(
    graph: nx.MultiDiGraph,
    relations: str | Collection[str],
    *,
    node_types: Collection[str] | None = None,
    include_isolates: bool = False,
) -> nx.MultiDiGraph:
    """Copy only the requested relations into a new ``MultiDiGraph``.

    ``node_types`` applies to both endpoints.  Set ``include_isolates`` to keep
    all matching nodes even when they have no selected edge.
    """

    requested = {relations} if isinstance(relations, str) else set(relations)
    if not requested:
        raise ValueError("at least one relation is required")
    unknown = requested.difference(ALL_RELATIONS)
    if unknown:
        raise ValueError(f"unknown relations: {', '.join(sorted(unknown))}")
    allowed_types = set(node_types) if node_types is not None else None

    result = nx.MultiDiGraph(**graph.graph)
    result.graph["selected_relations"] = tuple(sorted(requested))

    if include_isolates:
        for node, data in sorted(graph.nodes(data=True), key=lambda item: str(item[0])):
            if allowed_types is None or data.get("node_type") in allowed_types:
                result.add_node(node, **dict(data))

    edges = sorted(
        graph.edges(keys=True, data=True),
        key=lambda edge: (str(edge[0]), str(edge[1]), str(edge[2])),
    )
    for source, target, key, data in edges:
        relation = data.get("relation", data.get("label"))
        if relation not in requested:
            continue
        if allowed_types is not None and (
            graph.nodes[source].get("node_type") not in allowed_types
            or graph.nodes[target].get("node_type") not in allowed_types
        ):
            continue
        if source not in result:
            result.add_node(source, **dict(graph.nodes[source]))
        if target not in result:
            result.add_node(target, **dict(graph.nodes[target]))
        result.add_edge(source, target, key=key, **dict(data))
    return result


def relation_graph(
    graph: nx.MultiDiGraph,
    relations: str | Collection[str],
    *,
    node_types: Collection[str] | None = None,
    include_isolates: bool = True,
    weight: str = "weight",
    aggregate: str = "sum",
) -> nx.DiGraph:
    """Project selected parallel relations into a weighted ``DiGraph``.

    The projected edge stores ``weight``, ``edge_count``, ``relations`` and a
    per-relation ``relation_weights`` mapping.  Supported aggregation rules are
    ``sum``, ``max`` and ``min``.
    """

    if aggregate not in {"sum", "max", "min"}:
        raise ValueError("aggregate must be one of: sum, max, min")
    selected = extract_relations(
        graph,
        relations,
        node_types=node_types,
        include_isolates=include_isolates,
    )
    result = nx.DiGraph(**selected.graph)
    result.graph.update({"edge_aggregation": aggregate, "weight_attribute": weight})
    for node, data in sorted(selected.nodes(data=True), key=lambda item: str(item[0])):
        result.add_node(node, **dict(data))

    for source, target, _key, data in sorted(
        selected.edges(keys=True, data=True),
        key=lambda edge: (str(edge[0]), str(edge[1]), str(edge[2])),
    ):
        relation = str(data.get("relation", data.get("label")))
        edge_weight = _nonnegative_number(data.get(weight, 0.0), table="graph edge", column=weight)
        if not result.has_edge(source, target):
            result.add_edge(
                source,
                target,
                weight=edge_weight,
                edge_count=1,
                relations=(relation,),
                relation_weights={relation: edge_weight},
            )
            continue

        attrs = result[source][target]
        if aggregate == "sum":
            attrs["weight"] += edge_weight
        elif aggregate == "max":
            attrs["weight"] = max(attrs["weight"], edge_weight)
        else:
            attrs["weight"] = min(attrs["weight"], edge_weight)
        attrs["edge_count"] += 1
        relation_weights = attrs["relation_weights"]
        relation_weights[relation] = relation_weights.get(relation, 0.0) + edge_weight
        attrs["relations"] = tuple(sorted(relation_weights))
    return result


def extract_flow_graph(
    graph: nx.MultiDiGraph,
    relations: str | Collection[str] = FLOW_RELATIONS,
    *,
    include_isolates: bool = True,
    weight: str = "weight",
) -> nx.DiGraph:
    """Return a municipality-only graph containing flow relations exclusively."""

    requested = {relations} if isinstance(relations, str) else set(relations)
    if not requested:
        raise ValueError("at least one flow relation is required")
    forbidden = requested.difference(FLOW_RELATIONS)
    if forbidden:
        raise ValueError(
            "flow algorithms accept only COMMUTES_TO/STUDIES_IN; got "
            + ", ".join(sorted(forbidden))
        )
    return relation_graph(
        graph,
        requested,
        node_types={MUNICIPALITY},
        include_isolates=include_isolates,
        weight=weight,
        aggregate="sum",
    )


def build_graph_from_parquet(
    processed_dir: str | Path,
    *,
    strict: bool = True,
) -> nx.MultiDiGraph:
    """Read the standard ``data/processed`` Parquet files and build the graph."""

    directory = Path(processed_dir)

    def read(name: str, *, required: bool = False) -> pd.DataFrame | None:
        path = directory / name
        if not path.exists():
            if required:
                raise FileNotFoundError(path)
            return None
        return pd.read_parquet(path)

    municipalities = read("municipalities.parquet", required=True)
    assert municipalities is not None  # Narrowed for type checkers by required=True.
    return build_mobility_graph(
        municipalities,
        flow_edges=read("flow_edges.parquet"),
        commute_edges=read("commute_edges.parquet"),
        study_edges=read("study_edges.parquet"),
        airports=read("airports.parquet"),
        airport_access=read("airport_access.parquet"),
        strict=strict,
    )


def graph_facts(graph: nx.MultiDiGraph) -> dict[str, Any]:
    """Return JSON-friendly counts that describe the layered graph."""

    node_counts = {node_type: 0 for node_type in (MUNICIPALITY, PREFECTURE, AIRPORT)}
    for _node, data in graph.nodes(data=True):
        node_type = data.get("node_type")
        node_counts[node_type] = node_counts.get(node_type, 0) + 1

    relation_counts = {relation: 0 for relation in sorted(ALL_RELATIONS)}
    for _source, _target, data in graph.edges(data=True):
        relation = data.get("relation", data.get("label"))
        relation_counts[relation] = relation_counts.get(relation, 0) + 1
    return {
        "graph_type": type(graph).__name__,
        "directed": graph.is_directed(),
        "multigraph": graph.is_multigraph(),
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "node_counts": dict(sorted(node_counts.items(), key=lambda item: str(item[0]))),
        "relation_counts": dict(sorted(relation_counts.items(), key=lambda item: str(item[0]))),
    }


# Compatibility-friendly aliases for callers that prefer verb-oriented names.
build_graph = build_mobility_graph
extract_relation_graph = relation_graph
project_relations = relation_graph
relation_subgraph = extract_relations


__all__ = [
    "ACCESS_TO",
    "AIRPORT",
    "ALL_RELATIONS",
    "COMMUTES_TO",
    "FLOW_RELATIONS",
    "IS_IN",
    "MUNICIPALITY",
    "PREFECTURE",
    "STUDIES_IN",
    "build_graph",
    "build_graph_from_parquet",
    "build_mobility_graph",
    "extract_flow_graph",
    "extract_relation_graph",
    "extract_relations",
    "graph_facts",
    "project_relations",
    "relation_graph",
    "relation_subgraph",
]
