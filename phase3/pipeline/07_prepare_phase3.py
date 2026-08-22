"""Prepare Phase 3 climate and Shinkansen access features for 100 cities."""

from __future__ import annotations

import argparse
import json
import math
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"
CLIMATE_ARCHIVE = RAW / "climate" / "jma_normal_surface.zip"
RAIL_ARCHIVE = RAW / "rail" / "N02-20_GML.zip"
MANIFEST = ROOT / "data" / "provenance" / "phase3_download_manifest.json"

JMA_SOURCE_URL = "https://www.data.jma.go.jp/obd/stats/data/mdrr/normal/"
RAIL_SOURCE_URL = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-v2_3.html"


def _source_metadata(dataset_key: str) -> dict[str, str | None]:
    """Return reproducibility metadata recorded by the download step."""

    metadata: dict[str, str | None] = {
        "retrieved_at": None,
        "license": None,
        "redistribution": None,
    }
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for record in manifest.get("files", []):
            if record.get("dataset_key") == dataset_key:
                metadata["retrieved_at"] = str(record.get("retrieved_at"))
                break
    if dataset_key == "jma_normal_surface":
        metadata["license"] = "JMA public data terms; attribution and source notice retained"
        metadata["redistribution"] = "processed_features_with_attribution"
    elif dataset_key == "mlit_railway_n02_20":
        metadata["license"] = (
            "MLIT National Land Numerical Information terms; dataset notices retained"
        )
        metadata["redistribution"] = "processed_features_with_attribution"
    return metadata


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _json_default(value: Any) -> Any:
    if value is pd.NA:
        return None
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"cannot encode {type(value).__name__}")


def _distance_summary(frame: pd.DataFrame) -> dict[str, Any]:
    values = pd.to_numeric(frame["distance_km"], errors="coerce")
    valid = values.dropna()
    return {
        "city_count": int(frame["municipality_id"].nunique()),
        "missing_distance_count": int(values.isna().sum()),
        "median_km": float(valid.median()) if not valid.empty else None,
        "p95_km": float(valid.quantile(0.95)) if not valid.empty else None,
        "max_km": float(valid.max()) if not valid.empty else None,
    }


def _coverage_summary(
    metrics: pd.DataFrame,
    weather_access: pd.DataFrame,
    shinkansen_access: pd.DataFrame,
    shinkansen_stations: pd.DataFrame,
) -> dict[str, Any]:
    climate = metrics.loc[metrics["category"].eq("climate")]
    climate_features = []
    for feature_name, feature_frame in climate.groupby("feature_name", sort=True):
        climate_features.append(
            {
                "feature_name": feature_name,
                "city_count": int(feature_frame["municipality_id"].nunique()),
                "missing_value_count": int(feature_frame["value"].isna().sum()),
                "units": sorted(feature_frame["unit"].dropna().unique().tolist()),
                "periods": sorted(feature_frame["year"].dropna().unique().tolist()),
                "source_datasets": sorted(
                    feature_frame["source_dataset"].dropna().unique().tolist()
                ),
            }
        )
    return {
        "expected_city_count": 100,
        "climate": {
            "city_count": int(climate["municipality_id"].nunique()),
            "feature_count": len(climate_features),
            "missing_value_count": int(climate["value"].isna().sum()),
            "features": climate_features,
        },
        "weather_station_access": {
            **_distance_summary(weather_access),
            "periods": sorted(weather_access["period"].dropna().unique().tolist()),
            "source_datasets": sorted(
                weather_access["source_dataset"].dropna().unique().tolist()
            ),
        },
        "shinkansen_access": {
            **_distance_summary(shinkansen_access),
            "nearest_station_unique_count": int(shinkansen_access["station_id"].nunique()),
            "source_station_catalog_count": int(shinkansen_stations["station_id"].nunique()),
            "station_in_municipality_status": sorted(
                shinkansen_access["station_in_municipality_status"]
                .dropna()
                .unique()
                .tolist()
            ),
            "source_datasets": sorted(
                shinkansen_access["source_dataset"].dropna().unique().tolist()
            ),
        },
    }


def _haversine_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    radius_km = 6_371.0088
    lat_a, lon_a, lat_b, lon_b = map(
        math.radians, (latitude_a, longitude_a, latitude_b, longitude_b)
    )
    delta_lat = lat_b - lat_a
    delta_lon = lon_b - lon_a
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * radius_km * math.asin(math.sqrt(value))


def _read_station_index(archive: zipfile.ZipFile) -> pd.DataFrame:
    payload = archive.read("normal_surface/surface_station_index.csv")
    index = pd.read_csv(
        __import__("io").BytesIO(payload),
        header=None,
        encoding="cp932",
        dtype=str,
    ).iloc[2:].copy()
    index.columns = [
        "station_id",
        "station_name",
        "station_name_kana",
        "station_name_en",
        "latitude_degree",
        "latitude_minute",
        "longitude_degree",
        "longitude_minute",
        "altitude",
    ]
    index["station_id"] = index["station_id"].str.strip()
    index["latitude"] = pd.to_numeric(index["latitude_degree"]) + (
        pd.to_numeric(index["latitude_minute"]) / 60
    )
    index["longitude"] = pd.to_numeric(index["longitude_degree"]) + (
        pd.to_numeric(index["longitude_minute"]) / 60
    )
    return index[["station_id", "station_name", "latitude", "longitude"]]


def _monthly_values(
    archive: zipfile.ZipFile,
    station_id: str,
) -> dict[str, float | None]:
    path = f"normal_surface/monthly/nml_sfc_m_{station_id}.csv"
    try:
        payload = archive.read(path)
    except KeyError:
        return {}
    rows = pd.read_csv(
        __import__("io").BytesIO(payload),
        header=None,
        encoding="cp932",
        dtype=str,
    )
    values: dict[str, float | None] = {}
    element_names = {
        "0500": ("annual_mean_temperature", "temperature"),
        "4000": ("annual_precipitation", "mm"),
        "3500": ("annual_sunshine_hours", "hours"),
        "6000": ("annual_snowfall", "cm"),
    }
    for row in rows.itertuples(index=False, name=None):
        element = str(row[2]).strip()
        if element not in element_names:
            continue
        feature, unit = element_names[element]
        raw_values = list(row[6:32:2]) if len(row) > 30 else []
        try:
            divisor = 10 if unit in {"temperature", "mm", "hours"} else 1
            parsed = [
                float(str(value).strip()) / divisor
                for value in raw_values
                if str(value).strip() not in {"", "-", "///"}
            ]
            values[feature] = parsed[-1] if len(parsed) == 13 else None
            if feature == "annual_mean_temperature" and len(parsed) == 13:
                values["january_mean_temperature"] = parsed[0]
                values["august_mean_temperature"] = parsed[7]
        except (TypeError, ValueError):
            values[feature] = None
    return values


def prepare_climate(municipalities: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    stations = []
    metric_rows = []
    source = _source_metadata("jma_normal_surface")
    with zipfile.ZipFile(CLIMATE_ARCHIVE) as archive:
        index = _read_station_index(archive)
        for station in index.to_dict(orient="records"):
            values = _monthly_values(archive, station["station_id"])
            if not values:
                continue
            stations.append({**station, **values})
    station_frame = pd.DataFrame(stations)
    if station_frame.empty:
        raise ValueError("JMA climate archive contains no usable station normals")
    access_rows = []
    for city in municipalities.loc[municipalities["search_universe"]].to_dict(orient="records"):
        choices = [
            (
                _haversine_km(
                    float(city["latitude"]),
                    float(city["longitude"]),
                    float(station["latitude"]),
                    float(station["longitude"]),
                ),
                station,
            )
            for station in station_frame.to_dict(orient="records")
        ]
        distance, station = min(choices, key=lambda item: (item[0], item[1]["station_id"]))
        access_rows.append(
            {
                "municipality_id": city["municipality_id"],
                "weather_station_id": station["station_id"],
                "weather_station_name": station["station_name"],
                "distance_km": distance,
                "period": "1991-2020",
                "source_dataset": "JMA 2020 normals, surface station",
                "source_url": JMA_SOURCE_URL,
                **source,
            }
        )
        for feature_name in (
            "annual_mean_temperature",
            "january_mean_temperature",
            "august_mean_temperature",
            "annual_precipitation",
            "annual_sunshine_hours",
            "annual_snowfall",
        ):
            value = station.get(feature_name)
            metric_rows.append(
                {
                    "municipality_id": city["municipality_id"],
                    "feature_name": f"climate.{feature_name}",
                    "category": "climate",
                    "value": value,
                    "unit": {
                        "annual_mean_temperature": "degC",
                        "january_mean_temperature": "degC",
                        "august_mean_temperature": "degC",
                        "annual_precipitation": "mm",
                        "annual_sunshine_hours": "hours",
                        "annual_snowfall": "cm",
                    }[feature_name],
                    "year": "1991-2020",
                    "period": "JMA 2020 normals",
                    "source_dataset": "JMA normal_surface",
                    "source_url": JMA_SOURCE_URL,
                    **source,
                    "geographic_granularity": "weather_station_mapped_to_municipality",
                    "direction": "neutral",
                    "normalization": "station_value_unchanged",
                    "missing_reason": None if value is not None else "station_value_missing",
                }
            )
    return pd.DataFrame(metric_rows), pd.DataFrame(access_rows)


def _rail_stations() -> pd.DataFrame:
    with zipfile.ZipFile(RAIL_ARCHIVE) as archive:
        payload = json.loads(
            archive.read("N02-20_GML/N02-20_Station.geojson")
        )
    rows = []
    for feature in payload["features"]:
        properties = feature["properties"]
        line_name = str(properties.get("N02_003") or "")
        if "新幹線" not in line_name:
            continue
        coordinates = [
            point
            for line in feature["geometry"]["coordinates"]
            for point in line
        ]
        if not coordinates:
            continue
        rows.append(
            {
                "station_id": f"N02_{properties.get('N02_005')}_{line_name}",
                "station_name": str(properties["N02_005"]),
                "line_name": line_name,
                "longitude": sum(point[0] for point in coordinates) / len(coordinates),
                "latitude": sum(point[1] for point in coordinates) / len(coordinates),
            }
        )
    stations = pd.DataFrame(rows)
    if stations.empty:
        raise ValueError("N02 railway archive contains no Shinkansen station features")
    return stations.drop_duplicates("station_name").reset_index(drop=True)


def prepare_shinkansen(
    municipalities: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    stations = _rail_stations()
    source = _source_metadata("mlit_railway_n02_20")
    access_rows = []
    metric_rows = []
    for city in municipalities.loc[municipalities["search_universe"]].to_dict(orient="records"):
        choices = [
            (
                _haversine_km(
                    float(city["latitude"]),
                    float(city["longitude"]),
                    float(station["latitude"]),
                    float(station["longitude"]),
                ),
                station,
            )
            for station in stations.to_dict(orient="records")
        ]
        distance, station = min(choices, key=lambda item: (item[0], item[1]["station_id"]))
        access_rows.append(
            {
                "municipality_id": city["municipality_id"],
                "station_id": station["station_id"],
                "station_name": station["station_name"],
                "line_name": station["line_name"],
                "distance_km": distance,
                "station_in_municipality": pd.NA,
                "station_in_municipality_status": "not_spatially_joined",
                "source_dataset": "MLIT National Land Numerical Information N02-20",
                "source_url": RAIL_SOURCE_URL,
                **source,
            }
        )
        metric_rows.append(
            {
                "municipality_id": city["municipality_id"],
                "feature_name": "transport.nearest_shinkansen_distance",
                "category": "transport",
                "value": distance,
                "unit": "km",
                "year": "2020",
                "period": "N02-20",
                "source_dataset": "MLIT N02-20 railway data",
                "source_url": RAIL_SOURCE_URL,
                **source,
                "geographic_granularity": "station_mapped_to_municipality",
                "direction": "lower_is_better_for_distance_only",
                "normalization": "Haversine_straight_line",
                "missing_reason": None,
            }
        )
    return pd.DataFrame(metric_rows), pd.DataFrame(access_rows)


def run(processed_dir: Path = PROCESSED) -> dict[str, Any]:
    municipalities = pd.read_parquet(processed_dir / "municipalities.parquet")
    if int(municipalities["search_universe"].sum()) != 100:
        raise ValueError("Phase 3 expects the approved 100-city Phase 2 search universe")
    climate_metrics, weather_access = prepare_climate(municipalities)
    rail_metrics, shinkansen_access = prepare_shinkansen(municipalities)
    metrics = pd.concat([climate_metrics, rail_metrics], ignore_index=True)
    metrics.to_parquet(processed_dir / "environmental_metrics.parquet", index=False)
    weather_access.to_parquet(processed_dir / "weather_station_access.parquet", index=False)
    shinkansen_access.to_parquet(processed_dir / "shinkansen_access.parquet", index=False)
    stations = _rail_stations()
    stations.to_parquet(processed_dir / "shinkansen_stations.parquet", index=False)
    catalog = {
        "generated_at": utc_now(),
        "features": sorted(metrics["feature_name"].unique().tolist()),
        "climate_period": "1991-2020",
        "rail_edition": "N02-20 (2020)",
        "housing_status": "not_adopted_coverage_unverified",
        "disaster_status": "feasibility_deferred",
        "nature_status": "feasibility_deferred",
    }
    write_json(processed_dir / "phase3_feature_catalog.json", catalog)
    report = {
        "generated_at": utc_now(),
        "phase": 3,
        "pipeline": "pipeline/07_prepare_phase3.py",
        "search_city_count": 100,
        "outputs": {
            "environmental_metrics.parquet": len(metrics),
            "weather_station_access.parquet": len(weather_access),
            "shinkansen_access.parquet": len(shinkansen_access),
            "shinkansen_stations.parquet": len(stations),
        },
        "coverage": _coverage_summary(
            metrics,
            weather_access,
            shinkansen_access,
            stations,
        ),
        "checks": {
            "climate_coverage": len(weather_access) == 100,
            "shinkansen_coverage": len(shinkansen_access) == 100,
            "housing_adopted": False,
            "disaster_adopted": False,
            "nature_adopted": False,
        },
        "limitations": [
            (
                "Housing cost is not included because a complete same-definition "
                "100-city table was not verified."
            ),
            (
                "Shinkansen station-in-municipality is not polygon-joined; "
                "nearest station distance is the adopted feature."
            ),
            "Disaster and nature data remain feasibility gaps.",
        ],
    }
    write_json(processed_dir / "phase3_processing_report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed-dir", type=Path, default=PROCESSED)
    args = parser.parse_args()
    report = run(args.processed_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
