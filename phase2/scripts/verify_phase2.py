#!/usr/bin/env python3
# ruff: noqa: E501
"""Verify Phase 2 national search acceptance and write JSON/HTML evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROCESSED = ROOT / "data" / "processed"
DEFAULT_JSON = DEFAULT_PROCESSED / "phase2_acceptance_results.json"
DEFAULT_HTML = ROOT / "docs" / "phase2_acceptance.html"
DEFAULT_CONFIG = ROOT / "configs" / "phase2_cities.yml"

from app.executor import QueryExecutor, execution_is_finite  # noqa: E402
from app.llm import AzureOpenAIChatClient, AzureOpenAIPlanner, AzureOpenAIResponse  # noqa: E402
from app.response import attach_response_supplement  # noqa: E402


class AcceptanceFailure(AssertionError):
    """A human-readable Phase 2 acceptance failure."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _common(result: dict[str, Any]) -> dict[str, Any]:
    require(
        result.get("status") in {"ok", "partial"},
        f"unexpected status={result.get('status')!r}",
    )
    facts = result.get("hard_facts")
    require(isinstance(facts, dict), "hard_facts is missing")
    metadata = facts.get("evidence_metadata") or {}
    universe = metadata.get("universe") or {}
    require(universe.get("actual_municipality_count") == 100, "search universe is not 100")
    require(universe.get("analysis_universe_count") == 1719, "analysis universe is not national")
    require(execution_is_finite(result), "result contains a non-finite number")
    json.dumps(result, ensure_ascii=False, allow_nan=False)
    return facts


def validate_structure(processed_dir: Path) -> dict[str, Any]:
    quality = json.loads((processed_dir / "quality_report.json").read_text(encoding="utf-8"))
    processing = json.loads((processed_dir / "processing_report.json").read_text(encoding="utf-8"))
    config = yaml.safe_load(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    require(quality.get("overall_status") == "pass", "national quality report is not pass")
    require(quality.get("failed_check_count") == 0, "national quality report has failures")
    require(processing.get("phase") == 2, "processing report is not Phase 2")
    require(processing.get("analysis_municipality_count") == 1719, "analysis count mismatch")
    require(processing.get("search_city_count") == 100, "search count mismatch")
    require(config.get("status") == "approved_by_user", "Phase 2 city config is not approved")
    require(len(config.get("cities", [])) == 100, "Phase 2 city config does not contain 100 cities")
    return {
        "quality_checks": len(quality.get("checks", [])),
        "analysis_municipality_count": processing["analysis_municipality_count"],
        "search_city_count": processing["search_city_count"],
        "graph_facts": quality.get("graph_facts"),
    }


def _top_city(facts: dict[str, Any]) -> str | None:
    ranking = facts.get("ranking") or []
    if ranking:
        return ranking[0].get("name")
    rankings = facts.get("rankings") or {}
    rows = rankings.get("weighted_pagerank") or []
    return rows[0].get("name") if rows else None


def query_cases() -> tuple[tuple[str, str, Callable[[dict[str, Any]], dict[str, Any]]], ...]:
    return (
        ("P2-1", "福岡市に都市特性が似ている都市は？", lambda result: _similar(result, "福岡市")),
        (
            "P2-2",
            "福岡市のように空港アクセスが良く、都市機能もある都市は？",
            lambda result: _similar_airport(result, "福岡市"),
        ),
        (
            "P2-3",
            "広島市に似ている都市を全国から探して",
            lambda result: _similar(result, "広島市"),
        ),
        (
            "P2-4",
            "医療面で仙台市と似ている都市は？",
            lambda result: _category_similar(result, "仙台市", "medical"),
        ),
        ("P2-5", "全国主要都市で人流ハブ性が高い都市は？", _hub),
        (
            "P2-6",
            "九州で福岡市に似ている都市は？",
            lambda result: _region(result, "九州"),
        ),
        (
            "P2-7",
            "九州以外で福岡市に似ていて空港アクセスが良い都市は？",
            lambda result: _excluded_region(result, "九州"),
        ),
        (
            "P2-8",
            "人口規模を抑えながら、都市機能が比較的充実した都市は？",
            _multi_criteria,
        ),
        (
            "P2-9",
            "福岡市に似ていて空港アクセスも良い都市の根拠を示して",
            lambda result: _evidence(result, "福岡市"),
        ),
        (
            "P2-10",
            "家賃が安く自然が豊かな都市は？",
            _unsupported,
        ),
    )


def _similar(result: dict[str, Any], target: str) -> dict[str, Any]:
    facts = _common(result)
    require(facts["target"]["name"] == target, "similarity target mismatch")
    require(bool(facts.get("ranking")), "similarity ranking is empty")
    return {
        "target": target,
        "top_city": _top_city(facts),
        "similarity": facts["ranking"][0]["similarity"],
    }


def _similar_airport(result: dict[str, Any], target: str) -> dict[str, Any]:
    facts = _common(result)
    require(facts["target"]["name"] == target, "combined target mismatch")
    require(
        facts["analysis"] == "similar_cities_with_better_airport",
        "combined analysis mismatch",
    )
    require(bool(facts.get("ranking")), "combined ranking is empty")
    return {
        "target": target,
        "top_city": _top_city(facts),
        "qualified": facts["qualified_candidate_count"],
    }


def _category_similar(result: dict[str, Any], target: str, category: str) -> dict[str, Any]:
    facts = _common(result)
    require(facts["target"]["name"] == target, "category target mismatch")
    require(facts.get("requested_category") == category, "category mismatch")
    require(bool(facts.get("ranking")), "category ranking is empty")
    return {"target": target, "category": category, "top_city": _top_city(facts)}


def _hub(result: dict[str, Any]) -> dict[str, Any]:
    facts = _common(result)
    require(facts["analysis"] == "flow_centrality", "hub analysis mismatch")
    rankings = facts.get("rankings") or {}
    require(bool(rankings.get("weighted_pagerank")), "PageRank ranking is empty")
    require(
        rankings["weighted_pagerank"][0]["name"] == "東京都区部",
        "national hub leader mismatch",
    )
    return {
        "analysis_universe": facts["evidence_metadata"]["universe"]["analysis_universe_count"],
        "search_top_pagerank": rankings["weighted_pagerank"][0]["name"],
    }


def _region(result: dict[str, Any], region: str) -> dict[str, Any]:
    facts = _common(result)
    require(result["plan"].get("region") == region, "region plan mismatch")
    require(bool(facts.get("ranking")), "regional ranking is empty")
    prefectures = {item["prefecture"] for item in facts["ranking"]}
    kyushu_prefectures = {
        "福岡県",
        "佐賀県",
        "長崎県",
        "熊本県",
        "大分県",
        "宮崎県",
        "鹿児島県",
    }
    require(prefectures <= kyushu_prefectures, "regional filter leaked")
    return {
        "region": region,
        "top_city": _top_city(facts),
        "candidate_count": len(facts["ranking"]),
    }


def _excluded_region(result: dict[str, Any], region: str) -> dict[str, Any]:
    facts = _common(result)
    require(
        region in result["plan"].get("exclude_regions", []),
        "excluded region missing from plan",
    )
    excluded = {
        "福岡県",
        "佐賀県",
        "長崎県",
        "熊本県",
        "大分県",
        "宮崎県",
        "鹿児島県",
    }
    require(
        all(item["prefecture"] not in excluded for item in facts.get("ranking", [])),
        "excluded region leaked",
    )
    return {"excluded_region": region, "candidate_count": len(facts.get("ranking", []))}


def _multi_criteria(result: dict[str, Any]) -> dict[str, Any]:
    facts = _common(result)
    require(facts["analysis"] == "multi_criteria_search", "multi-criteria analysis mismatch")
    require(facts["criteria"]["urban_function_proxy"] == "weighted_degree", "proxy not explicit")
    require(
        all(item["population"] < 1_000_000 for item in facts["ranking"]),
        "population filter failed",
    )
    return {
        "top_city": _top_city(facts),
        "population_max": facts["criteria"]["population_max"],
    }


def _evidence(result: dict[str, Any], target: str) -> dict[str, Any]:
    facts = _common(result)
    require(facts["target"]["name"] == target, "evidence target mismatch")
    require(facts["evidence_metadata"]["datasets"], "datasets missing")
    require(facts["evidence_metadata"]["metrics"], "metrics missing")
    return {
        "top_city": _top_city(facts),
        "dataset_count": len(facts["evidence_metadata"]["datasets"]),
    }


def _unsupported(result: dict[str, Any]) -> dict[str, Any]:
    require(result["status"] == "unsupported", "unsupported query was executed")
    conditions = {item["condition"] for item in result["missing_structured_conditions"]}
    require({"rent", "nature"} <= conditions, "missing conditions were not separated")
    return {"missing_conditions": sorted(conditions)}


def _run_check(name: str, operation: Callable[[], Any]) -> dict[str, Any]:
    try:
        return {"name": name, "status": "pass", "evidence": operation()}
    except Exception as exc:
        return {"name": name, "status": "fail", "error": f"{type(exc).__name__}: {exc}"}


def write_html(report: dict[str, Any], path: Path) -> None:
    rows = []
    for item in report["queries"]:
        status = item["status"]
        evidence = item.get("evidence") or item.get("error", "")
        rows.append(
            "<tr>"
            f"<td>{escape(item['id'])}</td>"
            f"<td>{escape(item['query'])}</td>"
            f'<td><span class="status {escape(status)}">{escape(status.upper())}</span></td>'
            f"<td>{escape(json.dumps(evidence, ensure_ascii=False))}</td>"
            "</tr>"
        )
    check_rows = []
    for item in report["checks"]:
        check_rows.append(
            "<tr>"
            f"<td>{escape(item['name'])}</td>"
            f'<td><span class="status {escape(item["status"])}">{escape(item["status"].upper())}</span></td>'
            f"<td>{escape(item.get('error', json.dumps(item.get('evidence', ''), ensure_ascii=False)))}</td>"
            "</tr>"
        )
    html = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Phase 2 Acceptance</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", sans-serif; background:#f4f6f8; color:#1f2933; line-height:1.6; }}
main {{ max-width:1200px; margin:auto; padding:2rem 1rem; }} section,header {{ background:#fff; border:1px solid #d9e2ec; border-radius:10px; margin:1rem 0; padding:1.25rem; }}
h1,h2 {{ color:#102a43; }} table {{ border-collapse:collapse; width:100%; }} th,td {{ border-bottom:1px solid #d9e2ec; padding:.55rem; text-align:left; vertical-align:top; }}
th {{ background:#f0f4f8; }} .status {{ border-radius:999px; padding:.1rem .5rem; font-weight:700; }} .status.pass {{ background:#d9f2e6; color:#0b6b3a; }} .status.fail {{ background:#ffe3e3; color:#a61b1b; }}
a {{ color:#0b69a3; }} code {{ background:#f0f4f8; padding:.1rem .3rem; }}
</style></head><body><main>
<header><h1>Phase 2 Acceptance Report</h1><p><strong>Overall: {escape(report["overall_status"].upper())}</strong></p>
<p>全国分析空間: 1,719自治体（東京都区部集約） / 検索空間: 承認済み100都市</p>
<p>生成日時: {escape(report["generated_at"])} / LLM mode: {escape(str(report["llm_mode"]))}</p></header>
<section><h2>Acceptance Queries</h2><table><thead><tr><th>ID</th><th>質問</th><th>状態</th><th>証拠</th></tr></thead><tbody>{"".join(rows)}</tbody></table></section>
<section><h2>Independent Checks</h2><table><thead><tr><th>Check</th><th>状態</th><th>詳細</th></tr></thead><tbody>{"".join(check_rows)}</tbody></table></section>
<section><h2>Scope</h2><ul><li>全国ODで指標を計算してから、検索結果を100都市へ投影。</li><li>都市類似度の標準化母集団は承認済み100都市。</li><li>LLMは意図理解・説明のみで、数値計算・ランキングには使用しない。</li><li>性能・メモリ測定は後段ゲートとして未実施。</li></ul></section>
<section><h2>Evidence</h2><ul><li><a href="../data/processed/phase2_analysis.json">phase2_analysis.json</a></li><li><a href="../data/processed/quality_report.json">quality_report.json</a></li><li><a href="phase2_implementation_report.html">実装・検証報告書</a></li></ul></section>
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
        _run_check("Phase 2 structure and quality", lambda: validate_structure(processed_dir))
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
        "phase": 2,
        "analysis_universe_count": 1719,
        "search_universe_count": 100,
        "checks": checks,
        "queries": queries,
        "failed_count": len(failed),
        "llm_mode": use_llm,
        "performance_benchmark_status": "deferred",
    }
    json_report.parent.mkdir(parents=True, exist_ok=True)
    json_report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
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
            indent=2,
        )
    )
    return 0 if report["overall_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
