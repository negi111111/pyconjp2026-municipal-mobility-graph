"""Thin adapters over the existing Phase processed data and Graph snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PHASES = ("phase1", "phase2", "phase3")
RELATIONS = ("IS_IN", "COMMUTES_TO", "STUDIES_IN", "ACCESS_TO")
NODE_TYPES = ("Municipality", "Prefecture", "Airport")


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _plain(value: Any) -> Any:
    if value is pd.NA:
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


@dataclass(frozen=True)
class PhaseRepository:
    """Describe one Phase without importing its ``app`` package."""

    phase: str

    def __post_init__(self) -> None:
        if self.phase not in PHASES:
            raise ValueError(f"unsupported phase: {self.phase}")

    @property
    def root(self) -> Path:
        return REPOSITORY_ROOT / self.phase

    @property
    def processed(self) -> Path:
        return self.root / "data" / "processed"

    def search_ids(self) -> set[str]:
        path = self.processed / "search_universe.json"
        if path.exists():
            return set(_json(path).get("municipality_ids", []))
        frame = pd.read_parquet(
            self.processed / "municipalities.parquet",
            columns=["municipality_id"],
        )
        return set(frame["municipality_id"].astype(str))

    def summary(self) -> dict[str, Any]:
        quality = _json(self.processed / "quality_report.json")
        graph_facts = quality.get("graph_facts") or {}
        processing_path = (
            self.processed / "phase3_processing_report.json"
            if self.phase == "phase3"
            else self.processed / "processing_report.json"
        )
        processing = _json(processing_path)
        search_ids = self.search_ids()
        if self.phase == "phase3":
            catalog = _json(self.processed / "phase3_feature_catalog.json")
            features = catalog.get("features", [])
            coverage = processing.get("coverage", {})
        else:
            features = [
                "SSDSE: population / medical / education / economy / welfare",
                "Census OD: commute / study / centrality",
                "Airport: nearest scheduled-service distance",
            ]
            coverage = {}
        analysis_count = (quality.get("analysis_universe") or {}).get("count")
        if analysis_count is None:
            analysis_count = processing.get("analysis_municipality_count")
        if analysis_count is None:
            analysis_count = processing.get("seed_city_count")
        if analysis_count is None:
            analysis_count = len(search_ids)
        return {
            "phase": self.phase,
            "analysis_universe_count": int(analysis_count),
            "search_universe_count": len(search_ids),
            "graph_node_count": graph_facts.get("node_count"),
            "graph_edge_count": graph_facts.get("edge_count"),
            "node_counts": graph_facts.get("node_counts", {}),
            "relation_counts": graph_facts.get("relation_counts", {}),
            "features": features,
            "coverage": coverage,
            "capabilities": self._capabilities(),
        }

    def _capabilities(self) -> list[str]:
        base = [
            "city similarity",
            "category similarity",
            "bidirectional flow",
            "flow centrality",
            "airport distance",
        ]
        if self.phase in {"phase2", "phase3"}:
            base.extend(["national analysis projection", "region filter", "population filter"])
        if self.phase == "phase3":
            base.extend(
                ["climate condition", "Shinkansen distance", "environmental composite query"]
            )
        return base

    def load_graph(self) -> nx.MultiDiGraph:
        payload = _json(self.processed / "knowledge_graph.json")
        graph = nx.node_link_graph(
            payload,
            directed=True,
            multigraph=True,
            edges="edges",
            source="source",
            target="target",
            key="key",
        )
        if not isinstance(graph, nx.MultiDiGraph):
            raise TypeError(f"{self.phase} Graph snapshot is not a MultiDiGraph")
        return graph

    def load_municipalities(self) -> pd.DataFrame:
        return pd.read_parquet(self.processed / "municipalities.parquet")

    def load_flow_metrics(self) -> pd.DataFrame:
        path = self.processed / "national_flow_metrics.parquet"
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    def load_ssdse_metrics(self) -> pd.DataFrame:
        path = self.processed / "ssdse_metrics.parquet"
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    def load_environmental_metrics(self) -> pd.DataFrame:
        path = self.processed / "environmental_metrics.parquet"
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    def load_weather_access(self) -> pd.DataFrame:
        path = self.processed / "weather_station_access.parquet"
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    def load_shinkansen_access(self) -> pd.DataFrame:
        path = self.processed / "shinkansen_access.parquet"
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    def _inspect_non_municipality(
        self,
        node_id: str,
        graph: nx.MultiDiGraph,
    ) -> dict[str, Any]:
        node = graph.nodes[node_id]
        node_type = node.get("node_type", node.get("type", "Unknown"))
        basic = {
            key: _plain(value)
            for key, value in node.items()
            if key not in {"label", "type"} and not isinstance(value, (list, dict))
        }
        basic.update({"node_id": node_id, "node_type": node_type})
        connections = []
        for source, _target, key, data in graph.in_edges(node_id, keys=True, data=True):
            connections.append(
                {
                    "direction": "in",
                    "other_node_id": source,
                    "other_node_name": graph.nodes[source].get("name", source),
                    "relation": data.get("relation", data.get("label")),
                    "weight": _plain(data.get("weight")),
                    "key": key,
                }
            )
        for _source, target, key, data in graph.out_edges(node_id, keys=True, data=True):
            connections.append(
                {
                    "direction": "out",
                    "other_node_id": target,
                    "other_node_name": graph.nodes[target].get("name", target),
                    "relation": data.get("relation", data.get("label")),
                    "weight": _plain(data.get("weight")),
                    "key": key,
                }
            )
        connections.sort(
            key=lambda item: (
                str(item.get("relation")),
                -float(item.get("weight") or 0),
                str(item["other_node_id"]),
            )
        )
        return {
            "basic": basic,
            "connections": connections,
            "demographics": {},
            "features": {},
            "ssdse": [],
            "mobility": {},
            "airport": {},
            "phase3_features": [],
            "weather_station": {},
            "shinkansen": {},
        }

    def inspector(self, municipality_id: str) -> dict[str, Any]:
        graph = self.load_graph()
        if municipality_id not in graph:
            raise KeyError(f"unknown graph node: {municipality_id}")
        node_type = graph.nodes[municipality_id].get(
            "node_type", graph.nodes[municipality_id].get("type", "Unknown")
        )
        if node_type != "Municipality":
            return self._inspect_non_municipality(municipality_id, graph)
        municipalities = self.load_municipalities()
        matches = municipalities.loc[
            municipalities["municipality_id"].astype(str).eq(str(municipality_id))
        ]
        if matches.empty:
            raise KeyError(f"unknown municipality: {municipality_id}")
        row = matches.iloc[0].to_dict()
        node = dict(graph.nodes.get(municipality_id, {}))
        basic = {
            key: _plain(row.get(key, node.get(key)))
            for key in ("municipality_id", "municipality_code", "name", "prefecture", "node_type")
        }
        basic["node_type"] = node.get("node_type", node.get("type", "Municipality"))
        result: dict[str, Any] = {"basic": basic}
        result["demographics"] = {
            key: _plain(value)
            for key, value in row.items()
            if str(key).startswith(("2020_", "2024_総面積", "2024_可住地"))
            and pd.notna(value)
        }
        result["features"] = {
            key: _plain(value)
            for key, value in row.items()
            if str(key).startswith("feature_") and pd.notna(value)
        }
        ssdse = self.load_ssdse_metrics()
        result["ssdse"] = (
            ssdse.loc[
                ssdse["municipality_id"].astype(str).eq(str(municipality_id)),
                [
                    "indicator_code",
                    "reference_year",
                    "label",
                    "value",
                    "source_url",
                ],
            ]
            .dropna(subset=["value"])
            .to_dict(orient="records")
            if not ssdse.empty
            else []
        )
        flow = self.load_flow_metrics()
        if not flow.empty:
            flow_row = flow.loc[
                flow["municipality_id"].astype(str).eq(str(municipality_id))
            ]
            result["mobility"] = (
                flow_row.iloc[0].dropna().map(_plain).to_dict()
                if not flow_row.empty
                else {}
            )
        airport = pd.read_parquet(self.processed / "airport_access.parquet")
        airport_city_column = (
            "municipality_id" if "municipality_id" in airport.columns else "source"
        )
        airport_row = airport.loc[
            airport[airport_city_column].astype(str).eq(str(municipality_id))
        ]
        result["airport"] = (
            airport_row.iloc[0].dropna().map(_plain).to_dict()
            if not airport_row.empty
            else {}
        )
        environmental = self.load_environmental_metrics()
        result["phase3_features"] = (
            environmental.loc[
                environmental["municipality_id"].astype(str).eq(str(municipality_id))
            ]
            .dropna(axis=1, how="all")
            .to_dict(orient="records")
            if not environmental.empty
            else []
        )
        weather = self.load_weather_access()
        weather_row = (
            weather.loc[weather["municipality_id"].astype(str).eq(str(municipality_id))]
            if not weather.empty and "municipality_id" in weather.columns
            else pd.DataFrame()
        )
        result["weather_station"] = (
            weather_row.iloc[0].dropna().map(_plain).to_dict()
            if not weather_row.empty
            else {}
        )
        rail = self.load_shinkansen_access()
        rail_row = (
            rail.loc[rail["municipality_id"].astype(str).eq(str(municipality_id))]
            if not rail.empty and "municipality_id" in rail.columns
            else pd.DataFrame()
        )
        result["shinkansen"] = (
            rail_row.iloc[0].dropna().map(_plain).to_dict()
            if not rail.empty
            and "municipality_id" in rail.columns
            and not rail_row.empty
            else {}
        )
        return result

    def graph_view(
        self,
        *,
        relation_filter: set[str],
        node_type_filter: set[str],
        selected_id: str | None = None,
        region: str | None = None,
        max_nodes: int = 250,
        top_edges: int = 300,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        graph = self.load_graph()
        municipalities = self.load_municipalities()
        search_ids = self.search_ids()
        if region and "region" in municipalities.columns:
            region_ids = set(
                municipalities.loc[municipalities["region"].eq(region), "municipality_id"]
                .astype(str)
            )
            search_ids &= region_ids
        selected_municipalities = set(search_ids)
        if selected_id and selected_id in graph and selected_id in search_ids:
            selected_municipalities.add(selected_id)
        if selected_id and selected_id in graph and selected_id in search_ids:
            frontier = {selected_id}
            for _ in range(2):
                neighbors = set()
                for node in frontier:
                    for source, target, data in graph.edges(node, data=True):
                        if data.get("relation") in relation_filter:
                            neighbors.update((source, target))
                    for source, target, data in graph.in_edges(node, data=True):
                        if data.get("relation") in relation_filter:
                            neighbors.update((source, target))
                frontier = {
                    node
                    for node in neighbors.difference(selected_municipalities)
                    if graph.nodes[node].get("node_type", graph.nodes[node].get("type"))
                    == "Municipality"
                    and node in search_ids
                }
                selected_municipalities.update(frontier)
        selected_municipalities = set(
            sorted(selected_municipalities, key=lambda node: (node != selected_id, str(node)))[
                :max_nodes
            ]
        )
        selected_ids = set(selected_municipalities)
        # Keep every real administrative/airport edge for visible municipalities.
        # Municipality-to-municipality flow edges are bounded separately below.
        for source, target, data in graph.edges(data=True):
            relation = data.get("relation", data.get("label", ""))
            if relation not in relation_filter:
                continue
            source_type = graph.nodes[source].get(
                "node_type", graph.nodes[source].get("type")
            )
            target_type = graph.nodes[target].get(
                "node_type", graph.nodes[target].get("type")
            )
            if source in selected_municipalities and target_type != "Municipality":
                selected_ids.add(target)
            if target in selected_municipalities and source_type != "Municipality":
                selected_ids.add(source)
        selected_ids = {
            node
            for node in selected_ids
            if graph.nodes[node].get("node_type", graph.nodes[node].get("type")) in node_type_filter
        }
        edge_rows = []
        for source, target, key, data in graph.edges(keys=True, data=True):
            relation = str(data.get("relation", data.get("label", "")))
            if (
                relation not in relation_filter
                or source not in selected_ids
                or target not in selected_ids
            ):
                continue
            edge_rows.append(
                {
                    "source": source,
                    "target": target,
                    "key": key,
                    "relation": relation,
                    "weight": float(data.get("weight", 0) or 0),
                    "label": relation,
                }
            )
        structural_edges = [
            row
            for row in edge_rows
            if graph.nodes[row["source"]].get(
                "node_type", graph.nodes[row["source"]].get("type")
            )
            != "Municipality"
            or graph.nodes[row["target"]].get(
                "node_type", graph.nodes[row["target"]].get("type")
            )
            != "Municipality"
        ]
        flow_edges = [
            row for row in edge_rows if row not in structural_edges
        ]
        flow_edges.sort(key=lambda row: (-row["weight"], row["relation"], str(row["source"])))
        edge_rows = structural_edges + flow_edges[:top_edges]
        actual_nodes = set()
        for edge in edge_rows:
            actual_nodes.update((edge["source"], edge["target"]))
        actual_nodes.update(selected_ids)
        node_rows = []
        for node_id in sorted(actual_nodes, key=str):
            data = graph.nodes[node_id]
            node_type = data.get("node_type", data.get("type", "Unknown"))
            if node_type not in node_type_filter:
                continue
            node_rows.append(
                {
                    "id": str(node_id),
                    "label": str(data.get("name", data.get("label", node_id))),
                    "node_type": node_type,
                    "prefecture": data.get("prefecture"),
                }
            )
        allowed = {row["id"] for row in node_rows}
        edge_rows = [
            row for row in edge_rows if row["source"] in allowed and row["target"] in allowed
        ]
        return node_rows, edge_rows
