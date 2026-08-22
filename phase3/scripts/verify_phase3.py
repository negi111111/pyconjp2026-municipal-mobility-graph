#!/usr/bin/env python3
# ruff: noqa: E501
"""Verify Phase 3 acceptance and write deterministic JSON/HTML evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROCESSED = ROOT / "data" / "processed"
DEFAULT_JSON = DEFAULT_PROCESSED / "phase3_acceptance_results.json"
DEFAULT_HTML = ROOT / "docs" / "phase3_acceptance.html"
DEFAULT_SOURCES = ROOT / "data" / "provenance" / "phase3_sources.yml"

from app.executor import QueryExecutor, execution_is_finite  # noqa: E402
from app.llm import AzureOpenAIChatClient, AzureOpenAIPlanner, AzureOpenAIResponse  # noqa: E402
from app.response import attach_response_supplement  # noqa: E402


class AcceptanceFailure(AssertionError):
    """A human-readable Phase 3 acceptance failure."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _jsonable(value: Any) -> Any:
    if value is pd.NA:
        return None
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"cannot encode {type(value).__name__}")


def validate_structure(processed_dir: Path) -> dict[str, Any]:
    processing_path = processed_dir / "phase3_processing_report.json"
    catalog_path = processed_dir / "phase3_feature_catalog.json"
    quality_path = processed_dir / "quality_report.json"
    require(processing_path.exists(), "Phase 3 processing report is missing")
    require(catalog_path.exists(), "Phase 3 feature catalog is missing")
    require(quality_path.exists(), "Phase 2 quality report is missing")

    processing = json.loads(processing_path.read_text(encoding="utf-8"))
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    sources = yaml.safe_load(DEFAULT_SOURCES.read_text(encoding="utf-8"))

    require(processing.get("phase") == 3, "processing report is not Phase 3")
    require(processing.get("search_city_count") == 100, "Phase 3 search count mismatch")
    coverage = processing.get("coverage") or {}
    require(coverage.get("expected_city_count") == 100, "coverage expected count mismatch")
    climate_coverage = coverage.get("climate") or {}
    require(climate_coverage.get("city_count") == 100, "climate coverage statistics mismatch")
    require(climate_coverage.get("feature_count") == 6, "climate feature statistics mismatch")
    require(climate_coverage.get("missing_value_count") == 0, "climate missing values detected")
    weather_coverage = coverage.get("weather_station_access") or {}
    require(weather_coverage.get("city_count") == 100, "weather station coverage statistics mismatch")
    require(weather_coverage.get("missing_distance_count") == 0, "weather distance missing")
    require(weather_coverage.get("p95_km") is not None, "weather distance p95 is missing")
    rail_coverage = coverage.get("shinkansen_access") or {}
    require(rail_coverage.get("city_count") == 100, "Shinkansen coverage statistics mismatch")
    require(rail_coverage.get("missing_distance_count") == 0, "Shinkansen distance missing")
    require(rail_coverage.get("p95_km") is not None, "Shinkansen distance p95 is missing")
    require(
        rail_coverage.get("source_station_catalog_count") == 92,
        "Shinkansen source station catalog count mismatch",
    )
    require(processing.get("checks", {}).get("climate_coverage") is True, "climate coverage failed")
    require(
        processing.get("checks", {}).get("shinkansen_coverage") is True,
        "Shinkansen coverage failed",
    )
    require(processing.get("checks", {}).get("housing_adopted") is False, "housing was adopted unexpectedly")
    require(processing.get("checks", {}).get("disaster_adopted") is False, "disaster was adopted unexpectedly")
    require(processing.get("checks", {}).get("nature_adopted") is False, "nature was adopted unexpectedly")
    require(quality.get("overall_status") == "pass", "Phase 2 quality report is not pass")
    require(quality.get("failed_check_count") == 0, "Phase 2 quality report contains failures")
    require(quality.get("analysis_universe", {}).get("count") == 1719, "analysis count mismatch")
    require(quality.get("search_universe", {}).get("count") == 100, "search count mismatch")
    require(sources.get("phase") == 3, "Phase 3 provenance file has the wrong phase")
    require(len(sources.get("datasets", [])) == 2, "Phase 3 adopted source count mismatch")

    metrics = pd.read_parquet(processed_dir / "environmental_metrics.parquet")
    weather = pd.read_parquet(processed_dir / "weather_station_access.parquet")
    rail = pd.read_parquet(processed_dir / "shinkansen_access.parquet")
    stations = pd.read_parquet(processed_dir / "shinkansen_stations.parquet")
    required_metrics = {
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
    require(required_metrics <= set(metrics.columns), "environmental feature provenance columns are incomplete")
    require(metrics["municipality_id"].nunique() == 100, "environmental metrics do not cover 100 cities")
    require(metrics["feature_name"].nunique() == 7, "unexpected Phase 3 feature count")
    require(
        metrics.loc[metrics["category"].eq("climate"), "municipality_id"].nunique() == 100,
        "climate feature coverage is not 100 cities",
    )
    require(
        metrics.loc[
            metrics["feature_name"].eq("transport.nearest_shinkansen_distance"),
            "municipality_id",
        ].nunique()
        == 100,
        "Shinkansen feature coverage is not 100 cities",
    )
    require(metrics["value"].notna().all(), "adopted Phase 3 metrics contain missing values")
    require(weather["municipality_id"].nunique() == 100, "weather station access coverage mismatch")
    require(rail["municipality_id"].nunique() == 100, "Shinkansen access coverage mismatch")
    require(stations["station_id"].nunique() == 92, "Shinkansen station count mismatch")
    require(pd.to_numeric(metrics["value"], errors="coerce").notna().all(), "non-numeric metric value")
    require((pd.to_numeric(rail["distance_km"], errors="coerce") >= 0).all(), "negative rail distance")
    require((pd.to_numeric(weather["distance_km"], errors="coerce") >= 0).all(), "negative weather distance")
    require(
        set(rail["station_in_municipality_status"]) == {"not_spatially_joined"},
        "station membership status is overstated",
    )
    manifest_path = ROOT / "data" / "provenance" / "phase3_download_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(
        len(manifest.get("files", [])) == 2
        and all(item.get("checksum_verified") is True for item in manifest["files"]),
        "Phase 3 source checksum verification is incomplete",
    )
    expected_features = {
        "climate.annual_mean_temperature",
        "climate.january_mean_temperature",
        "climate.august_mean_temperature",
        "climate.annual_precipitation",
        "climate.annual_sunshine_hours",
        "climate.annual_snowfall",
        "transport.nearest_shinkansen_distance",
    }
    require(set(catalog.get("features", [])) == expected_features, "feature catalog mismatch")
    return {
        "quality_checks": len(quality.get("checks", [])),
        "analysis_municipality_count": 1719,
        "search_city_count": 100,
        "environmental_metric_rows": len(metrics),
        "climate_city_count": int(
            metrics.loc[metrics["category"].eq("climate"), "municipality_id"].nunique()
        ),
        "shinkansen_city_count": int(
            metrics.loc[
                metrics["feature_name"].eq("transport.nearest_shinkansen_distance"),
                "municipality_id",
            ].nunique()
        ),
        "shinkansen_station_count": int(stations["station_id"].nunique()),
        "housing_status": catalog.get("housing_status"),
        "disaster_status": catalog.get("disaster_status"),
        "nature_status": catalog.get("nature_status"),
        "coverage": coverage,
    }


def _common(result: dict[str, Any]) -> dict[str, Any]:
    require(result.get("status") in {"ok", "partial"}, f"unexpected status={result.get('status')!r}")
    facts = result.get("hard_facts")
    require(isinstance(facts, dict), "hard_facts is missing")
    metadata = facts.get("evidence_metadata") or {}
    universe = metadata.get("universe") or {}
    require(universe.get("actual_municipality_count") == 100, "search universe is not 100")
    require(universe.get("analysis_universe_count") == 1719, "analysis universe is not national")
    coverage = metadata.get("phase3_feature_coverage") or {}
    require(coverage.get("weather_station_access_count") == 100, "weather coverage evidence is missing")
    require(coverage.get("shinkansen_access_count") == 100, "Shinkansen coverage evidence is missing")
    require(execution_is_finite(result), "result contains a non-finite number")
    json.dumps(result, ensure_ascii=False, allow_nan=False)
    require(facts.get("evidence_metadata", {}).get("datasets"), "datasets are missing")
    require(facts.get("evidence_metadata", {}).get("metrics"), "metrics are missing")
    return facts


def _top_city(facts: dict[str, Any]) -> str | None:
    ranking = facts.get("ranking") or []
    return ranking[0].get("name") if ranking else None


def _rent_similarity(result: dict[str, Any]) -> dict[str, Any]:
    facts = _common(result)
    require(result["status"] == "partial", "unsupported housing condition was not marked partial")
    require(facts["target"]["name"] == "福岡市", "housing query target mismatch")
    missing = {item["condition"] for item in result["missing_structured_conditions"]}
    require("rent" in missing, "rent condition was not separated")
    require(bool(facts.get("ranking")), "similarity fallback ranking is empty")
    require(
        not any("rent" in key for key in facts["ranking"][0]),
        "rent was silently included in hard facts",
    )
    return {"top_city": _top_city(facts), "missing_conditions": sorted(missing)}


def _climate_similarity(result: dict[str, Any]) -> dict[str, Any]:
    facts = _common(result)
    require(facts["analysis"] == "phase3_environmental_multi_criteria_search", "climate analysis mismatch")
    require(facts["target"]["name"] == "福岡市", "climate target mismatch")
    require(any(item["feature"] == "climate.january_mean_temperature" for item in facts["criteria"]), "January temperature criterion missing")
    require(bool(facts.get("ranking")), "climate ranking is empty")
    require(
        all(item.get("climate.january_mean_temperature") is not None for item in facts["ranking"]),
        "climate value missing from ranking",
    )
    return {"top_city": _top_city(facts), "criterion_count": len(facts["criteria"])}


def _airport_and_shinkansen(result: dict[str, Any]) -> dict[str, Any]:
    facts = _common(result)
    require(facts["target"] is None, "reference-free transport query has a target")
    require(facts["analysis"] == "phase3_environmental_multi_criteria_search", "transport analysis mismatch")
    require(bool(facts.get("ranking")), "airport and Shinkansen ranking is empty")
    require(
        all(
            item.get("nearest_airport", {}).get("distance_km") is not None
            and item.get("transport.nearest_shinkansen_distance") is not None
            for item in facts["ranking"]
        ),
        "combined transport evidence is incomplete",
    )
    return {"top_city": _top_city(facts), "criterion_count": len(facts["criteria"])}


def _population_transport(result: dict[str, Any]) -> dict[str, Any]:
    facts = _common(result)
    require(facts["target"] is None, "population transport query has a target")
    require(bool(facts.get("ranking")), "population transport ranking is empty")
    require(result["plan"].get("population_max") == 1_000_000, "population cap is missing")
    require(
        all(item.get("population", 0) < 1_000_000 for item in facts["ranking"]),
        "population cap failed",
    )
    require(
        all(item.get("transport.nearest_shinkansen_distance") is not None for item in facts["ranking"]),
        "Shinkansen evidence is incomplete",
    )
    require(all(item.get("weighted_degree") is not None for item in facts["ranking"]), "flow proxy missing")
    return {"top_city": _top_city(facts), "population_max": result["plan"]["population_max"]}


def _chugoku_shikoku(result: dict[str, Any]) -> dict[str, Any]:
    facts = _common(result)
    require(result["plan"].get("region") == "中国・四国", "combined region was not preserved")
    require(bool(facts.get("ranking")), "China/Shikoku ranking is empty")
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
    require(all(item["prefecture"] in allowed for item in facts["ranking"]), "region filter leaked")
    require(all(item.get("climate.january_mean_temperature") is not None for item in facts["ranking"]), "regional climate evidence missing")
    require(all(item.get("weighted_degree") is not None for item in facts["ranking"]), "regional flow proxy missing")
    return {"top_city": _top_city(facts), "region": result["plan"]["region"]}


def _non_kyushu_rent(result: dict[str, Any]) -> dict[str, Any]:
    facts = _common(result)
    require(result["status"] == "partial", "non-Kyushu housing condition was not marked partial")
    require("九州" in result["plan"].get("exclude_regions", []), "Kyushu exclusion missing")
    require(facts["target"]["name"] == "福岡市", "non-Kyushu target mismatch")
    kyushu = {"福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県"}
    require(all(item["prefecture"] not in kyushu for item in facts["ranking"]), "Kyushu candidate leaked")
    require("rent" in {item["condition"] for item in result["missing_structured_conditions"]}, "rent gap missing")
    return {"top_city": _top_city(facts), "excluded_region": "九州"}


def query_cases() -> tuple[tuple[str, str, Callable[[dict[str, Any]], dict[str, Any]]], ...]:
    return (
        ("P3-1", "福岡市に似ていて住居費が比較的安い都市は？", _rent_similarity),
        ("P3-2", "福岡市に似ていて冬が比較的暖かい都市は？", _climate_similarity),
        ("P3-3", "空港と新幹線の両方へのアクセスが良い都市は？", _airport_and_shinkansen),
        ("P3-4", "人口規模を抑えつつ、広域交通が便利な都市は？", _population_transport),
        ("P3-5", "中国・四国で冬が比較的暖かく、都市機能もある都市は？", _chugoku_shikoku),
        (
            "P3-6",
            "九州以外で福岡市に似ていて住居費を抑えやすい都市は？",
            _non_kyushu_rent,
        ),
    )


def _run_check(name: str, operation: Callable[[], Any]) -> dict[str, Any]:
    try:
        return {"name": name, "status": "pass", "evidence": operation()}
    except Exception as exc:
        return {"name": name, "status": "fail", "error": f"{type(exc).__name__}: {exc}"}


def write_html(report: dict[str, Any], path: Path) -> None:
    query_rows = []
    for item in report["queries"]:
        detail = item.get("evidence") or item.get("error", "")
        query_rows.append(
            "<tr>"
            f"<td>{escape(item['id'])}</td>"
            f"<td>{escape(item['query'])}</td>"
            f'<td><span class="status {escape(item["status"])}">{escape(item["status"].upper())}</span></td>'
            f"<td><pre>{escape(json.dumps(detail, ensure_ascii=False, indent=2, default=_jsonable))}</pre></td>"
            "</tr>"
        )
    check_rows = []
    for item in report["checks"]:
        detail = item.get("evidence") or item.get("error", "")
        check_rows.append(
            "<tr>"
            f"<td>{escape(item['name'])}</td>"
            f'<td><span class="status {escape(item["status"])}">{escape(item["status"].upper())}</span></td>'
            f"<td><pre>{escape(json.dumps(detail, ensure_ascii=False, indent=2, default=_jsonable))}</pre></td>"
            "</tr>"
        )
    html = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Phase 3 Acceptance Report</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", sans-serif; background:#f4f6f8; color:#1f2933; line-height:1.6; }}
main {{ max-width:1240px; margin:auto; padding:2rem 1rem; }} section,header {{ background:#fff; border:1px solid #d9e2ec; border-radius:10px; margin:1rem 0; padding:1.25rem; }}
h1,h2 {{ color:#102a43; }} table {{ border-collapse:collapse; width:100%; }} th,td {{ border-bottom:1px solid #d9e2ec; padding:.55rem; text-align:left; vertical-align:top; }}
th {{ background:#f0f4f8; }} .status {{ border-radius:999px; padding:.1rem .5rem; font-weight:700; }} .status.pass {{ background:#d9f2e6; color:#0b6b3a; }} .status.fail {{ background:#ffe3e3; color:#a61b1b; }}
pre {{ white-space:pre-wrap; overflow-wrap:anywhere; margin:0; }} a {{ color:#0b69a3; }} code {{ background:#f0f4f8; padding:.1rem .3rem; }}
</style></head><body><main>
<header><h1>Phase 3 Acceptance Report</h1>
<p><strong>総合結果: {escape(report["overall_status"].upper())}</strong></p>
<p>全国分析空間: 1,719自治体 / 検索空間: 承認済み100都市 / LLM mode: {escape(str(report["llm_mode"]))}</p>
<p>生成日時: {escape(report["generated_at"])}</p></header>
<section><h2>Acceptance Queries</h2><table><thead><tr><th>ID</th><th>質問</th><th>状態</th><th>検証証拠</th></tr></thead><tbody>{"".join(query_rows)}</tbody></table></section>
<section><h2>Independent Checks</h2><table><thead><tr><th>Check</th><th>状態</th><th>詳細</th></tr></thead><tbody>{"".join(check_rows)}</tbody></table></section>
<section><h2>Phase 3の境界</h2><ul>
<li>気候はJMA 1991-2020平年値を最近傍観測所へ対応付けた値です。</li>
<li>新幹線アクセスはMLIT N02-20の最近傍駅までのHaversine直線距離です。所要時間ではありません。</li>
<li>住居費、災害、自然はcoverage・定義・集約方法が未確定のためランキングへ追加していません。</li>
<li>数値、順位、フィルタ、証拠はpandas / NetworkXで計算し、LLMは意図理解・説明だけに限定しています。</li>
</ul></section>
<section><h2>証跡</h2><ul>
<li><a href="../data/processed/phase3_processing_report.json">phase3_processing_report.json</a></li>
<li><a href="../data/processed/phase3_feature_catalog.json">phase3_feature_catalog.json</a></li>
<li><a href="../data/provenance/phase3_sources.yml">phase3_sources.yml</a></li>
<li><a href="../data/provenance/phase3_download_manifest.json">phase3_download_manifest.json</a></li>
<li><a href="phase3_implementation_report.html">Phase 3実装・検証報告書</a></li>
</ul></section>
</main></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def run(
    processed_dir: Path = DEFAULT_PROCESSED,
    json_report: Path = DEFAULT_JSON,
    html_report: Path = DEFAULT_HTML,
    use_llm: bool = False,
) -> dict[str, Any]:
    checks = [
        _run_check("Phase 3 structure, coverage, and provenance", lambda: validate_structure(processed_dir))
    ]
    executor = QueryExecutor.from_processed_dir(processed_dir)
    planner = None
    response = None
    if use_llm:
        client = AzureOpenAIChatClient.from_environment()
        planner = AzureOpenAIPlanner(client)
        response = AzureOpenAIResponse(client)
    queries = []
    for case_id, query, validator in query_cases():
        result = executor.execute(query, planner_provider=planner)
        if response is not None and result.get("hard_facts") is not None:
            result = attach_response_supplement(result, response)
        checked = _run_check(case_id, lambda result=result, validator=validator: validator(result))
        queries.append({"id": case_id, "query": query, **checked})
    failed = [item for item in [*checks, *queries] if item["status"] != "pass"]
    report = {
        "generated_at": utc_now(),
        "overall_status": "pass" if not failed else "fail",
        "phase": 3,
        "analysis_universe_count": 1719,
        "search_universe_count": 100,
        "checks": checks,
        "queries": queries,
        "failed_count": len(failed),
        "llm_mode": use_llm,
        "housing_status": "not_adopted_coverage_unverified",
        "disaster_status": "feasibility_deferred",
        "nature_status": "feasibility_deferred",
    }
    json_report.parent.mkdir(parents=True, exist_ok=True)
    json_report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=_jsonable, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    write_html(report, html_report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed-data", type=Path, default=DEFAULT_PROCESSED)
    parser.add_argument("--json-report", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--html-report", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--llm", action="store_true")
    args = parser.parse_args()
    report = run(args.processed_data, args.json_report, args.html_report, args.llm)
    print(
        json.dumps(
            {
                "overall_status": report["overall_status"],
                "passed_queries": sum(item["status"] == "pass" for item in report["queries"]),
                "failed_count": report["failed_count"],
                "llm_mode": report["llm_mode"],
                "json_report": str(args.json_report),
                "html_report": str(args.html_report),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["overall_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
