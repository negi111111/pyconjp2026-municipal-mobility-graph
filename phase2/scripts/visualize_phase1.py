#!/usr/bin/env python3
"""Render reproducible Phase 1 evidence figures from processed Parquet data.

The renderer deliberately uses only the Python standard library plus pandas.
It writes plain, self-contained SVG so the figures remain editable in slide
software and do not depend on an installed Japanese font at generation time.

Required input files under ``--data-dir``:

* ``municipalities.parquet``
* ``flow_edges.parquet``
* ``airports.parquet``
* ``airport_access.parquet``

No fallback or demonstration data are generated.  Missing or unusable source
data therefore fail the command before any figure is written.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pandas as pd

INK = "#20252B"
MUTED = "#66717D"
GRID = "#D8DEE5"
PALE = "#F4F6F8"
BLUE = "#2563A6"
BLUE_DARK = "#17466F"
BLUE_LIGHT = "#DCEAF7"
ORANGE = "#D97706"
ORANGE_DARK = "#8C4A03"
WHITE = "#FFFFFF"

FONT_STACK = (
    "-apple-system, BlinkMacSystemFont, 'Hiragino Sans', "
    "'Yu Gothic', 'Noto Sans CJK JP', sans-serif"
)

SSDSE_SOURCE = "SSDSE-A-2026（独立行政法人統計センター）"
CENSUS_SOURCE = "2020年国勢調査 従業地・通学地集計（e-Stat）"
AIRPORT_SOURCE = "国土数値情報 C28-21・空港管理状況調書（国土交通省）"


@dataclass(frozen=True)
class Phase1Tables:
    """The four processed tables needed by every Phase 1 figure."""

    municipalities: pd.DataFrame
    flow_edges: pd.DataFrame
    airports: pd.DataFrame
    airport_access: pd.DataFrame


class Svg:
    """Small XML-based SVG builder with a single typography system."""

    def __init__(self, width: int, height: int, *, description: str) -> None:
        ET.register_namespace("", "http://www.w3.org/2000/svg")
        self.width = width
        self.height = height
        self.root = ET.Element(
            "{http://www.w3.org/2000/svg}svg",
            {
                "width": str(width),
                "height": str(height),
                "viewBox": f"0 0 {width} {height}",
                "role": "img",
                "aria-label": description,
            },
        )
        ET.SubElement(self.root, "{http://www.w3.org/2000/svg}title").text = description
        ET.SubElement(
            self.root,
            "{http://www.w3.org/2000/svg}rect",
            {"width": str(width), "height": str(height), "fill": WHITE},
        )

    @staticmethod
    def _attrs(values: dict[str, Any]) -> dict[str, str]:
        return {key.replace("_", "-"): str(value) for key, value in values.items()}

    def element(self, tag: str, **attrs: Any) -> ET.Element:
        return ET.SubElement(
            self.root,
            f"{{http://www.w3.org/2000/svg}}{tag}",
            self._attrs(attrs),
        )

    def text(
        self,
        x: float,
        y: float,
        value: Any,
        *,
        size: int = 14,
        fill: str = INK,
        weight: int = 400,
        anchor: str = "start",
        **attrs: Any,
    ) -> ET.Element:
        element = self.element(
            "text",
            x=_number(x),
            y=_number(y),
            fill=fill,
            font_family=FONT_STACK,
            font_size=size,
            font_weight=weight,
            text_anchor=anchor,
            **attrs,
        )
        element.text = str(value)
        return element

    def header(self, title: str, subtitle: str, *, note: str | None = None) -> None:
        self.text(48, 48, title, size=25, weight=700)
        self.text(48, 76, subtitle, size=13, fill=MUTED)
        if note:
            self.text(self.width - 48, 48, note, size=12, fill=MUTED, anchor="end")
        self.element("line", x1=48, y1=92, x2=self.width - 48, y2=92, stroke=GRID)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(self.root).write(path, encoding="utf-8", xml_declaration=True)


def _number(value: float) -> str:
    """Format finite coordinates compactly and reject broken geometry."""

    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"SVG coordinate must be finite; got {value!r}")
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _require_columns(frame: pd.DataFrame, required: set[str], table: str) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{table} is missing required columns: {', '.join(missing)}")


def _require_rows(frame: pd.DataFrame, table: str) -> None:
    if frame.empty:
        raise ValueError(f"{table} has no rows; real processed data are required")


def load_phase1_data(data_dir: str | Path) -> Phase1Tables:
    """Load and minimally validate the four canonical processed tables."""

    directory = Path(data_dir)
    filenames = {
        "municipalities": "municipalities.parquet",
        "flow_edges": "flow_edges.parquet",
        "airports": "airports.parquet",
        "airport_access": "airport_access.parquet",
    }
    missing = [name for name in filenames.values() if not (directory / name).is_file()]
    if missing:
        listing = ", ".join(missing)
        raise FileNotFoundError(
            f"Phase 1 visualization data are incomplete in {directory}: missing {listing}. "
            "Run the real-data preparation pipeline first."
        )

    frames = {
        key: pd.read_parquet(directory / filename) for key, filename in filenames.items()
    }
    tables = Phase1Tables(**frames)
    _validate_tables(tables)
    return tables


def _validate_tables(tables: Phase1Tables) -> None:
    _require_columns(
        tables.municipalities,
        {"municipality_id", "name", "prefecture", "latitude", "longitude"},
        "municipalities",
    )
    _require_columns(tables.flow_edges, {"source", "target"}, "flow_edges")
    _require_columns(
        tables.airports,
        {"airport_id", "name", "latitude", "longitude"},
        "airports",
    )
    _require_columns(
        tables.airport_access,
        {"source", "target", "distance_km", "rank"},
        "airport_access",
    )
    for name, frame in (
        ("municipalities", tables.municipalities),
        ("flow_edges", tables.flow_edges),
        ("airports", tables.airports),
        ("airport_access", tables.airport_access),
    ):
        _require_rows(frame, name)

    if not ({"total"} <= set(tables.flow_edges.columns)) and not (
        {"commuters", "students"} <= set(tables.flow_edges.columns)
    ):
        raise ValueError(
            "flow_edges must contain total or both commuters and students for quantitative width"
        )


def _flow_values(frame: pd.DataFrame) -> pd.Series:
    if "total" in frame.columns:
        values = pd.to_numeric(frame["total"], errors="coerce")
    else:
        commuters = pd.to_numeric(frame["commuters"], errors="coerce").fillna(0)
        students = pd.to_numeric(frame["students"], errors="coerce").fillna(0)
        values = commuters + students
    return values.fillna(0).clip(lower=0).astype(float)


def _prepared_flows(frame: pd.DataFrame) -> pd.DataFrame:
    flows = frame.copy()
    flows["flow"] = _flow_values(flows)
    flows = flows.loc[
        (flows["source"].astype(str) != flows["target"].astype(str)) & (flows["flow"] > 0)
    ].copy()
    if flows.empty:
        raise ValueError("flow_edges has no positive intercity flow after excluding self-flows")
    grouping = ["source", "target"]
    columns = {"flow": "sum"}
    for optional in ("source_name", "target_name", "source_prefecture", "target_prefecture"):
        if optional in flows.columns:
            columns[optional] = "first"
    return flows.groupby(grouping, as_index=False, sort=True).agg(columns)


def _year_label(frame: pd.DataFrame) -> str:
    if "year" not in frame.columns:
        return "2020年"
    years = sorted({str(value) for value in frame["year"].dropna().tolist()})
    return "・".join(years) + "年" if years else "年次不明"


def _geographic_positions(
    municipalities: pd.DataFrame,
    *,
    left: float,
    top: float,
    width: float,
    height: float,
) -> dict[str, tuple[float, float]]:
    longitude = pd.to_numeric(municipalities["longitude"], errors="coerce")
    latitude = pd.to_numeric(municipalities["latitude"], errors="coerce")
    if longitude.isna().any() or latitude.isna().any():
        raise ValueError("municipalities contains missing or non-numeric latitude/longitude")
    if longitude.nunique() < 2 or latitude.nunique() < 2:
        raise ValueError("municipality coordinates do not span a drawable geographic extent")

    lon_min, lon_max = float(longitude.min()), float(longitude.max())
    lat_min, lat_max = float(latitude.min()), float(latitude.max())
    lon_pad = (lon_max - lon_min) * 0.05
    lat_pad = (lat_max - lat_min) * 0.05
    lon_min -= lon_pad
    lon_max += lon_pad
    lat_min -= lat_pad
    lat_max += lat_pad

    positions: dict[str, tuple[float, float]] = {}
    for index, row in municipalities.iterrows():
        x = left + (float(longitude.loc[index]) - lon_min) / (lon_max - lon_min) * width
        y = top + (lat_max - float(latitude.loc[index])) / (lat_max - lat_min) * height
        positions[str(row["municipality_id"])] = (x, y)
    return positions


def _city_lookup(municipalities: pd.DataFrame) -> dict[str, dict[str, str]]:
    return {
        str(row["municipality_id"]): {
            "name": str(row["name"]),
            "prefecture": str(row["prefecture"]),
        }
        for row in municipalities.to_dict(orient="records")
    }


def _text_width(value: str, size: int) -> float:
    """Estimate SVG text width for collision avoidance without a local font."""

    units = sum(0.58 if ord(character) < 128 else 1.0 for character in value)
    return max(size, units * size)


def _overlap_area(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    return max(0.0, right - left) * max(0.0, bottom - top)


def _draw_map_nodes(
    svg: Svg,
    municipalities: pd.DataFrame,
    positions: dict[str, tuple[float, float]],
    *,
    label_all: bool = True,
) -> list[tuple[float, float, float, float]]:
    rows = municipalities.to_dict(orient="records")
    rows.sort(key=lambda row: (positions[str(row["municipality_id"])][1], str(row["name"])))
    occupied = [
        (x - 5.5, y - 5.5, x + 5.5, y + 5.5) for x, y in positions.values()
    ]
    candidates = (
        (8, 4, "start"),
        (-8, 4, "end"),
        (8, -9, "start"),
        (-8, -9, "end"),
        (0, -11, "middle"),
        (0, 18, "middle"),
    )
    for row in rows:
        node = str(row["municipality_id"])
        x, y = positions[node]
        svg.element(
            "circle",
            cx=_number(x),
            cy=_number(y),
            r=4.2,
            fill=WHITE,
            stroke=INK,
            stroke_width=1.5,
        )
        if label_all:
            name = str(row["name"])
            width = _text_width(name, 11)
            choices: list[tuple[float, int, float, float, str, tuple[float, ...]]] = []
            for priority, (dx, dy, anchor) in enumerate(candidates):
                label_x, baseline = x + dx, y + dy
                left = label_x if anchor == "start" else label_x - width
                if anchor == "middle":
                    left = label_x - width / 2
                box = (left - 2, baseline - 11, left + width + 2, baseline + 3)
                collision = sum(_overlap_area(box, prior) for prior in occupied)
                overflow = max(0.0, 42 - box[0]) + max(0.0, box[2] - 1068)
                choices.append(
                    (collision + overflow * 100, priority, label_x, baseline, anchor, box)
                )
            _score, _priority, label_x, baseline, anchor, box = min(choices)
            occupied.append(box)
            svg.text(
                label_x,
                baseline,
                name,
                size=11,
                weight=600,
                anchor=anchor,
                paint_order="stroke",
                stroke=WHITE,
                stroke_width=2.5,
            )
    return occupied


def render_administrative_membership(municipalities: pd.DataFrame, path: Path) -> None:
    """Render the fixed Phase 1 municipalities grouped by prefecture."""

    _require_rows(municipalities, "municipalities")
    _require_columns(
        municipalities,
        {"municipality_id", "name", "prefecture"},
        "municipalities",
    )
    groups = [
        (str(prefecture), group.sort_values(["name", "municipality_id"]))
        for prefecture, group in municipalities.groupby("prefecture", sort=True)
    ]
    if not groups:
        raise ValueError("municipalities has no prefecture memberships")

    svg = Svg(1280, 760, description="Phase 1自治体の行政所属")
    svg.header(
        "Phase 1自治体の行政所属",
        f"{len(municipalities)}自治体・{len(groups)}県｜Municipality → Prefecture（IS_IN）",
        note=f"出典: {SSDSE_SOURCE}",
    )

    columns = 3
    card_width = 370
    card_height = 275
    x_gap = 36
    y_gap = 32
    start_x = 48
    start_y = 120
    for index, (prefecture, group) in enumerate(groups):
        row_index, column_index = divmod(index, columns)
        x = start_x + column_index * (card_width + x_gap)
        y = start_y + row_index * (card_height + y_gap)
        svg.element(
            "rect",
            x=x,
            y=y,
            width=card_width,
            height=card_height,
            rx=7,
            fill=PALE,
            stroke=GRID,
        )
        svg.text(x + 20, y + 34, prefecture, size=18, weight=700)
        svg.text(
            x + card_width - 20,
            y + 34,
            f"{len(group)}市",
            size=12,
            fill=MUTED,
            anchor="end",
        )
        svg.element(
            "line",
            x1=x + 20,
            y1=y + 48,
            x2=x + card_width - 20,
            y2=y + 48,
            stroke=GRID,
        )
        for city_index, city in enumerate(group.to_dict(orient="records")):
            item_column, item_row = divmod(city_index, 5)
            item_x = x + 22 + item_column * 172
            item_y = y + 82 + item_row * 34
            svg.element(
                "circle",
                cx=item_x,
                cy=item_y - 4,
                r=4,
                fill=WHITE,
                stroke=BLUE_DARK,
                stroke_width=1.5,
            )
            svg.text(item_x + 12, item_y, city["name"], size=13, weight=600)
            svg.text(
                item_x + 12,
                item_y + 15,
                city["municipality_id"],
                size=9,
                fill=MUTED,
            )
    svg.text(
        48,
        735,
        "注: 位置ではなく、行政所属だけを示す。後続の実フロー図との比較用。",
        size=11,
        fill=MUTED,
    )
    svg.write(path)


def _edge_width(value: float, minimum: float, maximum: float) -> float:
    if maximum <= minimum:
        return 4.0
    normalized = (math.sqrt(value) - math.sqrt(minimum)) / (
        math.sqrt(maximum) - math.sqrt(minimum)
    )
    return 1.2 + normalized * 3.8


def render_top_intercity_flows(
    municipalities: pd.DataFrame,
    flow_edges: pd.DataFrame,
    path: Path,
    *,
    top_n: int = 15,
) -> None:
    """Render top directed OD flows with width proportional to people."""

    if top_n <= 0:
        raise ValueError("top_n must be positive")
    all_flows = _prepared_flows(flow_edges)
    lookup = _city_lookup(municipalities)
    valid = set(lookup)
    unknown = sorted(
        (set(all_flows["source"].astype(str)) | set(all_flows["target"].astype(str))) - valid
    )
    if unknown:
        raise ValueError(f"flow_edges references unknown municipalities: {', '.join(unknown)}")
    all_flows["cross_prefecture"] = [
        lookup[str(row.source)]["prefecture"] != lookup[str(row.target)]["prefecture"]
        for row in all_flows.itertuples(index=False)
    ]
    cross_quota = min(3, top_n, int(all_flows["cross_prefecture"].sum()))
    cross = all_flows.loc[all_flows["cross_prefecture"]].nlargest(cross_quota, "flow")
    cross_keys = set(zip(cross["source"].astype(str), cross["target"].astype(str), strict=True))
    remaining = all_flows.loc[
        [
            (str(row.source), str(row.target)) not in cross_keys
            for row in all_flows.itertuples(index=False)
        ]
    ].nlargest(top_n - cross_quota, "flow")
    flows = pd.concat([remaining, cross], ignore_index=True).sort_values(
        ["flow", "source", "target"],
        ascending=[False, True, True],
    )

    positions = _geographic_positions(
        municipalities,
        left=100,
        top=130,
        width=980,
        height=520,
    )
    svg = Svg(1280, 760, description="実データによる都市間フロー上位")
    svg.header(
        "実データによる都市間フロー上位",
        f"{_year_label(flow_edges)}｜就業者＋通学者、人｜総合上位{len(flows) - cross_quota} + "
        f"跨県上位{cross_quota}有向OD（自己流動は除外）",
        note=f"出典: {CENSUS_SOURCE}",
    )

    marker = svg.element("defs")
    arrow = ET.SubElement(
        marker,
        "{http://www.w3.org/2000/svg}marker",
        {
            "id": "arrow-blue",
            "viewBox": "0 0 10 10",
            "refX": "8",
            "refY": "5",
            "markerWidth": "9",
            "markerHeight": "9",
            "markerUnits": "userSpaceOnUse",
            "orient": "auto-start-reverse",
        },
    )
    ET.SubElement(
        arrow,
        "{http://www.w3.org/2000/svg}path",
        {"d": "M 0 0 L 10 5 L 0 10 z", "fill": BLUE_DARK},
    )
    arrow_cross = ET.SubElement(marker, "{http://www.w3.org/2000/svg}marker", {
        "id": "arrow-orange", "viewBox": "0 0 10 10", "refX": "8", "refY": "5",
        "markerWidth": "9", "markerHeight": "9", "markerUnits": "userSpaceOnUse",
        "orient": "auto-start-reverse",
    })
    ET.SubElement(
        arrow_cross,
        "{http://www.w3.org/2000/svg}path",
        {"d": "M 0 0 L 10 5 L 0 10 z", "fill": ORANGE_DARK},
    )

    minimum = float(flows["flow"].min())
    maximum = float(flows["flow"].max())
    ordered = flows.sort_values("flow", ascending=True).to_dict(orient="records")
    directed_pairs = {(str(row["source"]), str(row["target"])) for row in ordered}
    for row in ordered:
        source = str(row["source"])
        target = str(row["target"])
        x1, y1 = positions[source]
        x2, y2 = positions[target]
        cross = lookup[source]["prefecture"] != lookup[target]["prefecture"]
        color = ORANGE_DARK if cross else BLUE_DARK
        reverse_is_visible = (target, source) in directed_pairs
        midpoint_x, midpoint_y = (x1 + x2) / 2, (y1 + y2) / 2
        if reverse_is_visible:
            length = max(math.hypot(x2 - x1, y2 - y1), 1.0)
            control_x = midpoint_x - (y2 - y1) / length * 18
            control_y = midpoint_y + (x2 - x1) / length * 18
            path_data = (
                f"M {_number(x1)} {_number(y1)} Q {_number(control_x)} "
                f"{_number(control_y)} {_number(x2)} {_number(y2)}"
            )
        else:
            path_data = f"M {_number(x1)} {_number(y1)} L {_number(x2)} {_number(y2)}"
        attrs: dict[str, Any] = {
            "d": path_data,
            "fill": "none",
            "stroke": color,
            "stroke_width": _edge_width(float(row["flow"]), minimum, maximum),
            "stroke_opacity": 0.72,
            "marker_end": f"url(#{'arrow-orange' if cross else 'arrow-blue'})",
        }
        if cross:
            attrs["stroke_dasharray"] = "9 5"
        svg.element("path", **attrs)

    _draw_map_nodes(svg, municipalities, positions)
    legend_x = 1090
    svg.text(legend_x, 135, "線の読み方", size=14, weight=700)
    svg.element("line", x1=legend_x, y1=165, x2=legend_x + 54, y2=165, stroke=BLUE_DARK,
                stroke_width=3)
    svg.text(legend_x + 66, 169, "同一県内", size=12)
    svg.element("line", x1=legend_x, y1=198, x2=legend_x + 54, y2=198,
                stroke=ORANGE_DARK, stroke_width=3, stroke_dasharray="9 5")
    svg.text(legend_x + 66, 202, "跨県", size=12)
    svg.text(legend_x, 238, "線幅 ∝ 人数の平方根", size=11, fill=MUTED)
    svg.text(legend_x, 260, "矢印 = 居住地 → 従業・通学地", size=11, fill=MUTED)
    svg.text(legend_x, 310, "表示内の上位5本", size=13, weight=700)
    for rank, row in enumerate(flows.nlargest(5, "flow").itertuples(index=False), start=1):
        source_name = lookup[str(row.source)]["name"]
        target_name = lookup[str(row.target)]["name"]
        y = 338 + (rank - 1) * 48
        svg.text(legend_x, y, f"{rank}  {source_name} → {target_name}", size=10, weight=600)
        svg.text(
            legend_x + 16,
            y + 17,
            f"{int(round(float(row.flow))):,}人",
            size=10,
            fill=MUTED,
        )
    svg.text(
        48,
        735,
        "計算: total = 15歳以上就業者 + 15歳未満を含む通学者。線幅は表示上位内でスケール。",
        size=11,
        fill=MUTED,
    )
    svg.write(path)


def _nearest_access(airport_access: pd.DataFrame) -> pd.DataFrame:
    access = airport_access.copy()
    access["distance_km"] = pd.to_numeric(access["distance_km"], errors="coerce")
    access["rank_numeric"] = pd.to_numeric(access["rank"], errors="coerce")
    access = access.dropna(subset=["distance_km"])
    access = access.loc[access["distance_km"] >= 0].copy()
    if access.empty:
        raise ValueError("airport_access has no non-negative distance_km values")

    nearest = (
        access.sort_values(["source", "distance_km", "target"])
        .groupby("source", as_index=False)
        .first()
    )
    rank_one = (
        access.loc[access["rank_numeric"] == 1]
        .sort_values(["source", "distance_km", "target"])
        .groupby("source", as_index=False)
        .first()
    )
    rank_one_distance = {
        str(row["source"]): float(row["distance_km"])
        for row in rank_one.to_dict(orient="records")
    }
    inconsistent = [
        str(row["source"])
        for row in nearest.to_dict(orient="records")
        if str(row["source"]) in rank_one_distance
        and rank_one_distance[str(row["source"])] > float(row["distance_km"]) + 1.0e-9
    ]
    if inconsistent:
        raise ValueError(
            "airport_access rank=1 is not the minimum distance for: "
            + ", ".join(sorted(inconsistent))
        )
    return nearest


def _combined_geographic_positions(
    municipalities: pd.DataFrame,
    airports: pd.DataFrame,
    *,
    left: float,
    top: float,
    width: float,
    height: float,
) -> tuple[dict[str, tuple[float, float]], dict[str, tuple[float, float]]]:
    municipality_points = municipalities[
        ["municipality_id", "latitude", "longitude"]
    ].rename(columns={"municipality_id": "point_id"})
    airport_points = airports[["airport_id", "latitude", "longitude"]].rename(
        columns={"airport_id": "point_id"}
    )
    combined = pd.concat([municipality_points, airport_points], ignore_index=True)
    positions = _geographic_positions(
        combined.rename(columns={"point_id": "municipality_id"}),
        left=left,
        top=top,
        width=width,
        height=height,
    )
    city_ids = set(municipalities["municipality_id"].astype(str))
    airport_ids = set(airports["airport_id"].astype(str))
    return (
        {node: position for node, position in positions.items() if node in city_ids},
        {node: position for node, position in positions.items() if node in airport_ids},
    )


def _airport_scale(value: Any) -> int:
    """Return a small ordinal used only for airport marker sizing."""

    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        labels = {
            "local": 1,
            "small": 1,
            "regional": 2,
            "medium": 2,
            "large": 3,
            "major": 3,
        }
        number = labels.get(str(value).strip().lower(), 1)
    return min(4, max(1, number))


def render_mobility_and_airports(
    municipalities: pd.DataFrame,
    flow_edges: pd.DataFrame,
    airports: pd.DataFrame,
    airport_access: pd.DataFrame,
    path: Path,
    *,
    top_flows: int = 10,
) -> None:
    """Render top OD links and each municipality's nearest airport."""

    if top_flows <= 0:
        raise ValueError("top_flows must be positive")
    flows = _prepared_flows(flow_edges).nlargest(top_flows, "flow").copy()
    nearest = _nearest_access(airport_access)
    city_ids = set(municipalities["municipality_id"].astype(str))
    if not city_ids.issubset(set(nearest["source"].astype(str))):
        missing = sorted(city_ids - set(nearest["source"].astype(str)))
        raise ValueError(f"nearest-airport relation is missing for: {', '.join(missing)}")

    referenced_airports = set(nearest["target"].astype(str))
    airport_subset = airports.loc[airports["airport_id"].astype(str).isin(referenced_airports)]
    missing_airports = sorted(referenced_airports - set(airport_subset["airport_id"].astype(str)))
    if missing_airports:
        raise ValueError(
            f"airport_access references unknown airports: {', '.join(missing_airports)}"
        )

    city_positions, airport_positions = _combined_geographic_positions(
        municipalities,
        airport_subset,
        left=95,
        top=125,
        width=980,
        height=535,
    )
    svg = Svg(1280, 760, description="都市間モビリティと最寄り空港")
    svg.header(
        "都市間モビリティと最寄り空港",
        f"{_year_label(flow_edges)}｜実フロー上位{len(flows)}本 + 直線距離最小空港（km）"
        "｜△サイズ=旅客数規模1–4",
        note="出典: e-Stat・国土交通省",
    )

    for row in flows.sort_values("flow").to_dict(orient="records"):
        source, target = str(row["source"]), str(row["target"])
        if source not in city_positions or target not in city_positions:
            continue
        x1, y1 = city_positions[source]
        x2, y2 = city_positions[target]
        svg.element(
            "line",
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            stroke=BLUE_DARK,
            stroke_width=2.2,
            stroke_opacity=0.38,
        )

    distance_label_boxes: list[tuple[float, float, float, float]] = []
    for row in nearest.sort_values(["source", "target"]).to_dict(orient="records"):
        source, target = str(row["source"]), str(row["target"])
        x1, y1 = city_positions[source]
        x2, y2 = airport_positions[target]
        svg.element(
            "line",
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            stroke=ORANGE_DARK,
            stroke_width=1.4,
            stroke_dasharray="5 5",
            stroke_opacity=0.72,
        )
        line_length = max(math.hypot(x2 - x1, y2 - y1), 1.0)
        label_offset = 12 if line_length < 35 else 7
        label_x = (x1 + x2) / 2 - (y2 - y1) / line_length * label_offset
        label_y = (y1 + y2) / 2 + (x2 - x1) / line_length * label_offset
        distance_label = f"{float(row['distance_km']):.0f}"
        label_width = _text_width(distance_label, 8)
        distance_label_boxes.append(
            (
                label_x - label_width / 2 - 2,
                label_y - 8,
                label_x + label_width / 2 + 2,
                label_y + 2,
            )
        )
        svg.text(
            label_x,
            label_y,
            distance_label,
            size=8,
            fill=ORANGE_DARK,
            anchor="middle",
            paint_order="stroke",
            stroke=WHITE,
            stroke_width=2.5,
        )

    occupied = _draw_map_nodes(svg, municipalities, city_positions)
    occupied.extend(distance_label_boxes)
    airport_lookup = {
        str(row["airport_id"]): {
            "name": str(row["name"]),
            "scale": _airport_scale(row.get("airport_scale", 1)),
        }
        for row in airport_subset.to_dict(orient="records")
    }
    for airport_id in sorted(airport_positions):
        x, y = airport_positions[airport_id]
        radius = 5 + airport_lookup[airport_id]["scale"] * 2
        occupied.append((x - radius - 1, y - radius - 1, x + radius + 1, y + radius + 1))
        svg.element(
            "path",
            d=f"M {_number(x)} {_number(y - radius)} "
            f"L {_number(x - radius)} {_number(y + radius * 0.86)} "
            f"L {_number(x + radius)} {_number(y + radius * 0.86)} Z",
            fill=WHITE,
            stroke=ORANGE_DARK,
            stroke_width=2,
        )

    airport_candidates = (
        (0, 21, "middle"),
        (0, -12, "middle"),
        (11, 4, "start"),
        (-11, 4, "end"),
        (10, -9, "start"),
        (-10, -9, "end"),
    )
    ordered_airports = sorted(
        airport_positions,
        key=lambda airport_id: (airport_positions[airport_id][1], airport_id),
    )
    for airport_id in ordered_airports:
        x, y = airport_positions[airport_id]
        airport = airport_lookup[airport_id]
        name = f"{airport['name']} [{airport['scale']}]"
        width = _text_width(name, 10)
        choices = []
        for priority, (dx, dy, anchor) in enumerate(airport_candidates):
            label_x, baseline = x + dx, y + dy
            left = label_x if anchor == "start" else label_x - width
            if anchor == "middle":
                left = label_x - width / 2
            box = (left - 2, baseline - 10, left + width + 2, baseline + 3)
            collision = sum(_overlap_area(box, prior) for prior in occupied)
            overflow = (
                max(0.0, 42 - box[0])
                + max(0.0, box[2] - 1068)
                + max(0.0, 108 - box[1])
                + max(0.0, box[3] - 690)
            )
            choices.append(
                (collision + overflow * 100, priority, label_x, baseline, anchor, box)
            )
        _score, _priority, label_x, baseline, anchor, box = min(choices)
        occupied.append(box)
        svg.text(
            label_x,
            baseline,
            name,
            size=10,
            fill=ORANGE_DARK,
            weight=700,
            anchor=anchor,
            paint_order="stroke",
            stroke=WHITE,
            stroke_width=3,
        )

    legend_x = 1085
    svg.text(legend_x, 135, "関係の読み方", size=14, weight=700)
    svg.element("line", x1=legend_x, y1=166, x2=legend_x + 55, y2=166,
                stroke=BLUE_DARK, stroke_width=2.2, stroke_opacity=0.6)
    svg.text(legend_x + 66, 170, "実フロー", size=12)
    svg.element("line", x1=legend_x, y1=199, x2=legend_x + 55, y2=199,
                stroke=ORANGE_DARK, stroke_width=1.4, stroke_dasharray="5 5")
    svg.text(legend_x + 66, 203, "最寄り空港", size=12)
    svg.element("path", d=f"M {legend_x + 7} 231 L {legend_x} 244 L {legend_x + 14} 244 Z",
                fill=WHITE, stroke=ORANGE_DARK, stroke_width=2)
    svg.text(legend_x + 66, 243, "空港 [旅客数規模]", size=12)
    svg.text(legend_x, 278, "破線上の数字 = km", size=11, fill=MUTED)
    svg.text(
        48,
        727,
        f"フロー: {CENSUS_SOURCE} / 空港位置・規模: {AIRPORT_SOURCE}",
        size=10,
        fill=MUTED,
    )
    svg.write(path)


def _bidirectional_pairs(flow_edges: pd.DataFrame) -> pd.DataFrame:
    directed = _prepared_flows(flow_edges)
    directed["a"] = directed[["source", "target"]].astype(str).min(axis=1)
    directed["b"] = directed[["source", "target"]].astype(str).max(axis=1)
    return (
        directed.groupby(["a", "b"], as_index=False, sort=True)["flow"]
        .sum()
        .sort_values(["flow", "a", "b"], ascending=[False, True, True])
    )


def render_bidirectional_flow_ranking(
    municipalities: pd.DataFrame,
    flow_edges: pd.DataFrame,
    path: Path,
    *,
    top_n: int = 10,
) -> None:
    """Render a zero-based ranking of pairwise bidirectional flows."""

    if top_n <= 0:
        raise ValueError("top_n must be positive")
    ranking = _bidirectional_pairs(flow_edges).head(top_n).copy()
    if ranking.empty:
        raise ValueError("no bidirectional flow pairs are available")
    lookup = _city_lookup(municipalities)
    unknown = sorted((set(ranking["a"]) | set(ranking["b"])) - set(lookup))
    if unknown:
        raise ValueError(f"flow ranking references unknown municipalities: {', '.join(unknown)}")

    svg = Svg(1280, 760, description="都市間の双方向フロー上位")
    svg.header(
        "都市間の双方向フロー上位",
        f"{_year_label(flow_edges)}｜A→B + B→A、人｜上位{len(ranking)}組（零起点）",
        note=f"出典: {CENSUS_SOURCE}",
    )
    plot_left = 320
    plot_right = 1165
    plot_top = 126
    row_height = 54
    maximum = float(ranking["flow"].max())
    axis_y = plot_top + len(ranking) * row_height + 8

    for tick in range(5):
        value = maximum * tick / 4
        x = plot_left + (plot_right - plot_left) * tick / 4
        svg.element(
            "line",
            x1=x,
            y1=plot_top - 12,
            x2=x,
            y2=axis_y,
            stroke=GRID,
            stroke_width=1,
        )
        svg.text(x, axis_y + 22, f"{int(round(value)):,}", size=10, fill=MUTED,
                 anchor="middle")

    for index, row in enumerate(ranking.to_dict(orient="records"), start=1):
        y = plot_top + (index - 1) * row_height
        label = f"{lookup[str(row['a'])]['name']} ↔ {lookup[str(row['b'])]['name']}"
        svg.text(48, y + 26, str(index), size=12, fill=MUTED, anchor="middle")
        svg.text(76, y + 26, label, size=13, weight=600)
        bar_width = float(row["flow"]) / maximum * (plot_right - plot_left)
        svg.element(
            "rect",
            x=plot_left,
            y=y + 8,
            width=bar_width,
            height=25,
            fill=BLUE,
            stroke=BLUE_DARK,
            stroke_width=1,
        )
        value_x = min(plot_left + bar_width + 9, svg.width - 55)
        svg.text(
            value_x,
            y + 27,
            f"{int(round(float(row['flow']))):,}",
            size=12,
            weight=700,
        )
    svg.text(
        48,
        735,
        "計算は有向ODを無向ペアにまとめた決定的集計。説明生成モデルは順位計算に使用しない。",
        size=11,
        fill=MUTED,
    )
    svg.write(path)


def _preflight_visualizations(
    tables: Phase1Tables,
    *,
    top_flows: int,
    top_ranking: int,
) -> None:
    """Reject inconsistent evidence before the first output file is written."""

    if top_flows <= 0:
        raise ValueError("top_flows must be positive")
    if top_ranking <= 0:
        raise ValueError("top_ranking must be positive")
    _validate_tables(tables)

    flows = _prepared_flows(tables.flow_edges)
    city_ids = set(tables.municipalities["municipality_id"].astype(str))
    flow_ids = set(flows["source"].astype(str)) | set(flows["target"].astype(str))
    unknown_cities = sorted(flow_ids - city_ids)
    if unknown_cities:
        raise ValueError(
            f"flow_edges references unknown municipalities: {', '.join(unknown_cities)}"
        )
    _bidirectional_pairs(tables.flow_edges)
    _geographic_positions(
        tables.municipalities,
        left=0,
        top=0,
        width=1,
        height=1,
    )

    nearest = _nearest_access(tables.airport_access)
    nearest_sources = set(nearest["source"].astype(str))
    unknown_sources = sorted(nearest_sources - city_ids)
    if unknown_sources:
        raise ValueError(
            f"airport_access references unknown municipalities: {', '.join(unknown_sources)}"
        )
    if not city_ids.issubset(nearest_sources):
        missing = sorted(city_ids - nearest_sources)
        raise ValueError(f"nearest-airport relation is missing for: {', '.join(missing)}")
    airport_ids = set(tables.airports["airport_id"].astype(str))
    referenced_airports = set(nearest["target"].astype(str))
    unknown_airports = sorted(referenced_airports - airport_ids)
    if unknown_airports:
        raise ValueError(
            f"airport_access references unknown airports: {', '.join(unknown_airports)}"
        )
    airport_subset = tables.airports.loc[
        tables.airports["airport_id"].astype(str).isin(referenced_airports)
    ]
    _combined_geographic_positions(
        tables.municipalities,
        airport_subset,
        left=0,
        top=0,
        width=1,
        height=1,
    )


def build_visualizations(
    tables: Phase1Tables,
    output_dir: str | Path,
    *,
    top_flows: int = 15,
    top_ranking: int = 10,
) -> list[Path]:
    """Validate the evidence tables and write the four canonical SVG files."""

    _preflight_visualizations(
        tables,
        top_flows=top_flows,
        top_ranking=top_ranking,
    )
    output = Path(output_dir)
    paths = [
        output / "administrative_membership.svg",
        output / "top_intercity_flows.svg",
        output / "mobility_nearest_airport.svg",
        output / "bidirectional_flow_ranking.svg",
    ]
    render_administrative_membership(tables.municipalities, paths[0])
    render_top_intercity_flows(
        tables.municipalities,
        tables.flow_edges,
        paths[1],
        top_n=top_flows,
    )
    render_mobility_and_airports(
        tables.municipalities,
        tables.flow_edges,
        tables.airports,
        tables.airport_access,
        paths[2],
        top_flows=min(top_flows, 10),
    )
    render_bidirectional_flow_ranking(
        tables.municipalities,
        tables.flow_edges,
        paths[3],
        top_n=top_ranking,
    )
    return paths


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render Phase 1 evidence SVGs from real processed Parquet data."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/processed"),
        help="directory containing the four processed Parquet files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/figures"),
        help="directory where the four SVG files are written",
    )
    parser.add_argument("--top-flows", type=int, default=15)
    parser.add_argument("--top-ranking", type=int, default=10)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    tables = load_phase1_data(args.data_dir)
    paths = build_visualizations(
        tables,
        args.output_dir,
        top_flows=args.top_flows,
        top_ranking=args.top_ranking,
    )
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
