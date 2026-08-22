#!/usr/bin/env python3
"""Run one query against Phase 1-3 and optionally ask the LLM to compare results."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PHASES = ("phase1", "phase2", "phase3")
DEFAULT_OUTPUT_DIR = Path("/tmp/pyconjp2026-mobility-kg-phase-comparison")

CHILD_CODE = r"""
import json
import sys

from app.query import run_query
from app.response import render_response

query = json.loads(__QUERY__)
use_llm = __USE_LLM__
result = run_query(query, use_llm=use_llm)
print(json.dumps({
    "result": result,
    "rendered_response": render_response(result),
}, ensure_ascii=False, allow_nan=False))
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value: Any, key: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return "\n".join(item for item in value if item)
    raise ValueError(f"comparison LLM field {key!r} must be a string, string list, or null")


def _run_phase(phase: str, query: str, *, use_llm: bool) -> dict[str, Any]:
    phase_dir = ROOT / phase
    environment = os.environ.copy()
    environment["PYTHONPATH"] = "."
    code = (
        CHILD_CODE.replace("__QUERY__", repr(json.dumps(query, ensure_ascii=False)))
        .replace("__USE_LLM__", "True" if use_llm else "False")
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=phase_dir,
        env=environment,
        capture_output=True,
        text=True,
    )
    if not completed.stdout.strip():
        raise RuntimeError(
            f"{phase} query failed with exit code {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{phase} returned invalid JSON: {completed.stdout[:400]}"
        ) from exc
    if completed.returncode != 0:
        payload["process_returncode"] = completed.returncode
        payload["process_stderr"] = completed.stderr.strip()
    return payload


def run_single_phase(
    phase: str,
    query: str,
    *,
    use_llm: bool = False,
) -> dict[str, Any]:
    """Run one Phase while keeping the same subprocess boundary as comparisons."""

    if phase not in PHASES:
        raise ValueError(f"unsupported phase: {phase}")
    return _run_phase(phase, query, use_llm=use_llm)


def _top_names(result: Mapping[str, Any]) -> list[str]:
    facts = result.get("hard_facts") or {}
    ranking = facts.get("ranking") or []
    if ranking:
        return [str(item.get("name", item.get("municipality_id"))) for item in ranking[:5]]
    rankings = facts.get("rankings") or {}
    pagerank = rankings.get("weighted_pagerank") or []
    return [str(item.get("name", item.get("municipality_id"))) for item in pagerank[:5]]


def _deterministic_comparison(phase_results: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    observations = {}
    for phase, payload in phase_results.items():
        result = payload["result"]
        facts = result.get("hard_facts") or {}
        observations[phase] = {
            "status": result.get("status"),
            "intent": (result.get("plan") or {}).get("intent"),
            "analysis": facts.get("analysis"),
            "top_cities": _top_names(result),
            "missing_conditions": [
                item.get("condition")
                for item in result.get("missing_structured_conditions") or []
            ],
        }
    return {"method": "deterministic_result_metadata_comparison", "observations": observations}


def _run_llm_analysis(query: str, phase_results: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    phase3_path = str(ROOT / "phase3")
    sys.path.insert(0, phase3_path)
    from app.llm import AzureOpenAIChatClient  # noqa: PLC0415

    client = AzureOpenAIChatClient.from_environment()
    system = (
        "あなたはPhase比較レビュー担当です。入力された同一QueryのPhase 1/2/3結果だけを "
        "根拠に、実装差分による結果差を日本語で考察してください。数値を再計算したり、 "
        "入力にない都市・順位・原因を推測したりしないでください。LLMの考察は説明用であり、 "
        "ランキングやHard Factsを変更しません。次のJSONだけを返してください: "
        '{"overall_comparison":"string","phase_observations":{"phase1":"string","phase2":"string","phase3":"string"},'
        '"differences":["string"],"caveats":["string"]}'
    )
    user = json.dumps(
        {
            "query": query,
            "phase_results": {
                phase: {
                    "result": payload["result"],
                    "rendered_response": payload["rendered_response"],
                }
                for phase, payload in phase_results.items()
            },
        },
        ensure_ascii=False,
    )
    raw = client.complete_json(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_completion_tokens=client.settings.comparison_max_completion_tokens,
        reasoning_effort=client.settings.comparison_reasoning_effort,
    )
    allowed = {"overall_comparison", "phase_observations", "differences", "caveats"}
    unknown = set(raw).difference(allowed)
    if unknown:
        raise ValueError(f"comparison LLM returned unknown fields: {', '.join(sorted(unknown))}")
    observations = raw.get("phase_observations")
    if not isinstance(observations, Mapping):
        raise ValueError("comparison LLM phase_observations must be an object")
    normalized_observations = {
        phase: _text(observations.get(phase), f"phase_observations.{phase}") or ""
        for phase in PHASES
    }
    return {
        "provider": "azure_openai_chat_comparison_v1",
        "model_deployment": client.settings.chat_deployment,
        "reasoning_effort": client.settings.reasoning_effort,
        "used_for_ranking_or_numbers": False,
        "overall_comparison": _text(raw.get("overall_comparison"), "overall_comparison") or "",
        "phase_observations": normalized_observations,
        "differences": [
            _text(item, "differences") or "" for item in (raw.get("differences") or [])
        ],
        "caveats": [_text(item, "caveats") or "" for item in (raw.get("caveats") or [])],
    }


def _markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Phase 1〜3 同一Query比較",
        "",
        f"- Query: `{report['query']}`",
        f"- 生成日時: {report['generated_at']}",
        f"- Phase Query LLM mode: `{report['phase_llm_mode']}`",
        f"- LLM考察: `{report['llm_analysis'] is not None}`",
        "",
        "## Phase別の回答結果",
        "",
    ]
    for phase in PHASES:
        payload = report["phase_results"][phase]
        result = payload["result"]
        lines.extend(
            [
                f"### {phase}",
                "",
                f"- status: `{result.get('status')}`",
                f"- intent: `{(result.get('plan') or {}).get('intent')}`",
                "",
                "```text",
                payload["rendered_response"].rstrip(),
                "```",
                "",
                "Structured Resultの上位候補："
                + "、".join(_top_names(result) or ["該当なし"]),
                "",
            ]
        )
    lines.extend(["## 機械的な差分要約", "", "```json"])
    lines.append(json.dumps(report["deterministic_comparison"], ensure_ascii=False, indent=2))
    lines.extend(["```", ""])
    if report["llm_analysis"] is not None:
        analysis = report["llm_analysis"]
        lines.extend(
            [
                "## LLMによる比較考察",
                "",
                f"使用Deployment: `{analysis['model_deployment']}`",
                f"Reasoning Effort: `{analysis['reasoning_effort']}`",
                "",
                analysis["overall_comparison"],
                "",
            ]
        )
        for phase in PHASES:
            lines.extend([f"### {phase}の考察", "", analysis["phase_observations"][phase], ""])
        if analysis["differences"]:
            lines.append("### 差分")
            lines.extend(f"- {item}" for item in analysis["differences"])
            lines.append("")
        if analysis["caveats"]:
            lines.append("### 注意点")
            lines.extend(f"- {item}" for item in analysis["caveats"])
            lines.append("")
    lines.extend(
        [
            "## 解釈上の注意",
            "",
            "- LLM考察は説明専用であり、Phase別のHard Factsや順位を変更しない。",
            (
                "- Phase 1/2/3で検索集合・特徴量・Graph範囲が異なるため、"
                "順位差を単純な品質差と解釈しない。"
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def run(
    query: str,
    *,
    phase_llm: bool,
    llm_analysis: bool,
    output_dir: Path | None,
) -> dict[str, Any]:
    if llm_analysis:
        phase_llm = True
    phase_results = {
        phase: _run_phase(phase, query, use_llm=phase_llm)
        for phase in PHASES
    }
    report: dict[str, Any] = {
        "generated_at": utc_now(),
        "query": query,
        "phase_llm_mode": phase_llm,
        "phase_results": phase_results,
        "deterministic_comparison": _deterministic_comparison(phase_results),
        "llm_analysis": None,
    }
    if llm_analysis:
        report["llm_analysis"] = _run_llm_analysis(query, phase_results)
    markdown = _markdown(report)
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "comparison.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        (output_dir / "comparison.md").write_text(markdown, encoding="utf-8")
    print(markdown, end="")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Phase 1〜3へ同一に渡す日本語Query")
    parser.add_argument(
        "--llm",
        action="store_true",
        help="各PhaseのQuery Planner/ResponseにもAzure OpenAIを使用する",
    )
    parser.add_argument(
        "--llm-analysis",
        action="store_true",
        help="3Phaseの結果をAzure OpenAIへ渡して比較考察する（--llmを含む）",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"comparison.json / comparison.mdの保存先（既定: {DEFAULT_OUTPUT_DIR}）",
    )
    args = parser.parse_args()
    run(
        args.query,
        phase_llm=args.llm,
        llm_analysis=args.llm_analysis,
        output_dir=args.output_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
