"""Render structured evidence while keeping hard facts and soft knowledge apart."""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .planner import (
    INTENT_AIRPORT_BETTER,
    INTENT_AIRPORT_RANK,
    INTENT_BIDIRECTIONAL_FLOW,
    INTENT_CATEGORY_SIMILARITY,
    INTENT_CITY_SIMILARITY,
    INTENT_CROSS_PREFECTURE_COMMUNITIES,
    INTENT_FLOW_HUB,
    INTENT_MULTI_CRITERIA,
    INTENT_SIMILAR_AIRPORT,
)

_CATEGORY_LABELS = {
    "overall": "都市特性全体",
    "population": "人口・世帯",
    "medical": "医療",
    "education": "教育",
    "economy": "経済・労働",
    "welfare": "福祉",
}
_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9_.])-?\d[\d,]*(?:\.\d+)?")


def _numeric_values(value: Any) -> set[float]:
    if isinstance(value, bool):
        return set()
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return {float(value)}
    if isinstance(value, Mapping):
        values: set[float] = set()
        for item in value.values():
            values.update(_numeric_values(item))
        return values
    if isinstance(value, (list, tuple)):
        values: set[float] = set()
        for item in value:
            values.update(_numeric_values(item))
        return values
    return set()


def _numeric_claim_check(
    text: str | None,
    hard_facts: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not text:
        return {"status": "pass", "unverified_numbers": []}
    facts = _numeric_values(hard_facts or {})
    unverified = []
    for token in _NUMBER_PATTERN.findall(text):
        value = float(token.replace(",", ""))
        if "." not in token and "," not in token and abs(value) <= 20:
            continue
        if 1900 <= abs(value) <= 2100:
            continue
        tolerance = max(1.0e-4, abs(value) * 1.0e-4)
        if not any(abs(value - fact) <= tolerance for fact in facts):
            unverified.append(token)
    return {
        "status": "pass" if not unverified else "warning",
        "unverified_numbers": unverified,
    }


@dataclass(frozen=True)
class ResponseSupplement:
    """Optional prose from an LLM; neither field is machine evidence."""

    evidence_explanation: str | None = None
    soft_knowledge: str | None = None


@runtime_checkable
class ResponseProvider(Protocol):
    """Optional LLM response boundary.

    The provider receives already-computed evidence. It may explain or add
    general background, but its output is placed outside ``hard_facts`` and is
    never fed back into ranking or scoring.
    """

    name: str

    def generate(
        self,
        query: str,
        plan: Mapping[str, Any],
        hard_facts: Mapping[str, Any] | None,
    ) -> ResponseSupplement | Mapping[str, Any]:
        """Return explanation-only text and optional soft knowledge."""


def attach_response_supplement(
    execution: Mapping[str, Any],
    provider: ResponseProvider,
) -> dict[str, Any]:
    """Add explicitly labelled, non-computational LLM prose to a result copy."""

    result = copy.deepcopy(dict(execution))
    raw = provider.generate(
        str(result.get("query", "")),
        dict(result.get("plan") or {}),
        result.get("hard_facts"),
    )
    if isinstance(raw, ResponseSupplement):
        supplement = raw
    else:
        supplement = ResponseSupplement(
            evidence_explanation=(
                str(raw["evidence_explanation"])
                if raw.get("evidence_explanation") is not None
                else None
            ),
            soft_knowledge=(
                str(raw["soft_knowledge"]) if raw.get("soft_knowledge") is not None else None
            ),
        )
    result["llm_response"] = {
        "provider": provider.name,
        "role": "explanation_only",
        "used_for_ranking_or_numbers": False,
        "evidence_explanation": supplement.evidence_explanation,
        "numeric_claim_check": _numeric_claim_check(
            supplement.evidence_explanation,
            result.get("hard_facts"),
        ),
    }
    boundary = result.setdefault("provenance_boundary", {})
    execution_path = list(boundary.get("execution_path") or [])
    if "llm_response" not in execution_path:
        execution_path.append("llm_response")
    boundary["execution_path"] = execution_path
    boundary.setdefault("retrievers_used", [])
    result["soft_knowledge"] = supplement.soft_knowledge
    return result


def _number(value: Any, digits: int = 3) -> str:
    if value is None:
        return "データなし"
    number = float(value)
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.{digits}f}"


def _city(record: Mapping[str, Any] | None) -> str:
    if not record:
        return "該当なし"
    return str(record.get("name", record.get("municipality_id", "該当なし")))


def _airport_line(record: Mapping[str, Any], *, include_access_score: bool = True) -> str:
    airport = record.get("nearest_airport") or {}
    line = (
        f"{_city(record)}: 最寄り{airport.get('name', '不明')} "
        f"{_number(airport.get('distance_km'), 1)} km"
    )
    if include_access_score:
        line += f"、アクセススコア {_number(record.get('access_score'))}"
    return line


def _summary_lines(intent: str, facts: Mapping[str, Any]) -> list[str]:
    if intent == INTENT_BIDIRECTIONAL_FLOW:
        target = _city(facts.get("target"))
        strongest = facts.get("strongest")
        if not strongest:
            return [f"{target}との双方向人流は見つかりませんでした。"]
        return [
            f"{target}との双方向人流が最も多いのは{_city(strongest)}です。",
            (
                f"{target}→{_city(strongest)} {_number(strongest.get('forward_flow'))}人、"
                f"{_city(strongest)}→{target} {_number(strongest.get('reverse_flow'))}人、"
                f"合計 {_number(strongest.get('bidirectional_flow'))}人。"
            ),
        ]

    if intent == INTENT_FLOW_HUB:
        rankings = facts.get("rankings") or {}
        pagerank = (rankings.get("weighted_pagerank") or [None])[0]
        degree = (rankings.get("weighted_degree") or [None])[0]
        weighted_in = (rankings.get("weighted_in_degree") or [None])[0]
        weighted_out = (rankings.get("weighted_out_degree") or [None])[0]
        lines = []
        if pagerank:
            lines.append(
                f"重み付きPageRank 1位は{_city(pagerank)}"
                f"（{_number(pagerank.get('value'), 6)}）です。"
            )
        if degree:
            lines.append(
                f"重み付きdegree 1位は{_city(degree)}"
                f"（{_number(degree.get('value'))}）です。"
            )
        if weighted_in:
            lines.append(
                f"重み付きin-degree 1位は{_city(weighted_in)}"
                f"（{_number(weighted_in.get('value'))}）です。"
            )
        if weighted_out:
            lines.append(
                f"重み付きout-degree 1位は{_city(weighted_out)}"
                f"（{_number(weighted_out.get('value'))}）です。"
            )
        return lines or ["人流ハブを判定できるODエッジがありません。"]

    if intent == INTENT_CROSS_PREFECTURE_COMMUNITIES:
        communities = facts.get("cross_prefecture_communities") or []
        lines = [f"県境をまたぐ人流コミュニティは{len(communities)}件です。"]
        for community in communities[:5]:
            names = "、".join(_city(item) for item in community.get("municipalities", []))
            prefectures = "・".join(str(item) for item in community.get("prefectures", []))
            lines.append(
                f"{community.get('community_id')}: {names}（{prefectures}）、"
                f"内部人流重み {_number(community.get('internal_symmetric_weight'))}"
            )
        return lines

    if intent == INTENT_MULTI_CRITERIA:
        ranking = facts.get("ranking") or []
        if facts.get("analysis") == "phase3_environmental_multi_criteria_search":
            if not ranking:
                return ["指定されたPhase 3の条件に合う候補は見つかりませんでした。"]
            lines = ["Phase 3の構造化条件を個別に適用し、候補を順位付けします。"]
            for criterion in facts.get("criteria") or []:
                feature = criterion.get("feature", criterion.get("criterion", "不明"))
                rule = criterion.get("rule", "不明")
                reference = criterion.get("reference_value", criterion.get("threshold"))
                unit = criterion.get("unit", "")
                suffix = f"（基準 {_number(reference)} {unit}）" if reference is not None else ""
                lines.append(f"- {feature}: {rule}{suffix}")
            for item in ranking:
                values = []
                if item.get("core_similarity") is not None:
                    values.append(f"類似度 {_number(item['core_similarity'], 4)}")
                if item.get("climate.january_mean_temperature") is not None:
                    values.append(
                        "1月平均気温 "
                        f"{_number(item['climate.january_mean_temperature'], 1)} degC"
                    )
                if item.get("climate.annual_snowfall") is not None:
                    values.append(f"年降雪量 {_number(item['climate.annual_snowfall'], 1)} cm")
                if item.get("transport.nearest_shinkansen_distance") is not None:
                    values.append(
                        "最寄り新幹線駅 "
                        f"{_number(item['transport.nearest_shinkansen_distance'], 1)} km"
                    )
                if item.get("nearest_airport"):
                    values.append(
                        "最寄り空港 "
                        f"{_number(item['nearest_airport'].get('distance_km'), 1)} km"
                    )
                if item.get("weighted_degree") is not None:
                    values.append(f"weighted degree {_number(item['weighted_degree'])}")
                lines.append(f"{item.get('rank')}位 {_city(item)}: {'、'.join(values)}")
            return lines
        if not ranking:
            return ["指定された人口規模と都市機能の条件に合う候補は見つかりませんでした。"]
        lines = [
            "指定人口規模の範囲で、人流ハブ性を都市機能の明示的な代理指標として順位付けします。",
        ]
        for item in ranking:
            lines.append(
                f"{item.get('rank')}位 {_city(item)}: 人口 {_number(item.get('population'))}人、"
                f"weighted degree {_number(item.get('weighted_degree'))}人"
            )
        return lines

    if intent in {INTENT_CITY_SIMILARITY, INTENT_CATEGORY_SIMILARITY}:
        target = _city(facts.get("target"))
        ranking = facts.get("ranking") or []
        category = str(facts.get("requested_category", "overall"))
        label = _CATEGORY_LABELS.get(category, category)
        if not ranking:
            return [f"{target}と{label}が似た候補は見つかりませんでした。"]
        lines = [f"{target}と{label}が最も似ている候補は{_city(ranking[0])}です。"]
        for item in ranking:
            lines.append(
                f"{item.get('rank')}位 {_city(item)}: cosine類似度 "
                f"{_number(item.get('similarity'), 4)}"
            )
        lines.append(f"使用指標数: {_number(facts.get('feature_count'))}")
        return lines

    if intent == INTENT_AIRPORT_RANK:
        ranking = facts.get("ranking") or []
        if not ranking:
            return ["空港アクセスデータは見つかりませんでした。"]
        metric_label = (
            "最寄り空港距離が短い順"
            if facts.get("requested_metric") == "nearest_distance"
            else "距離・空港規模スコア順"
        )
        include_score = facts.get("requested_metric") == "access_score"
        return [f"{metric_label}の1位は{_city(ranking[0])}です。"] + [
            _airport_line(item, include_access_score=include_score) for item in ranking
        ]

    if intent == INTENT_AIRPORT_BETTER:
        reference = facts.get("reference") or {}
        ranking = facts.get("ranking") or []
        metric = facts.get("requested_metric")
        label = (
            "最寄り空港距離（短いほど良い）"
            if metric == "nearest_distance"
            else "距離・空港規模スコア"
        )
        include_score = metric == "access_score"
        lines = [
            f"基準は{_airport_line(reference, include_access_score=include_score)}です。"
        ]
        lines.append(f"{label}が基準より良い都市は{len(ranking)}件表示します。")
        lines.extend(_airport_line(item, include_access_score=include_score) for item in ranking)
        return lines

    if intent == INTENT_SIMILAR_AIRPORT:
        target = _city(facts.get("target"))
        ranking = facts.get("ranking") or []
        distance_requested = facts.get("requested_airport_metric") == "nearest_distance"
        if not ranking:
            return [f"{target}と似ていて空港アクセスも良い候補は見つかりませんでした。"]
        lines = [f"{target}と似ていて空港アクセスも良い最上位候補は{_city(ranking[0])}です。"]
        for item in ranking:
            access = item.get("candidate_airport_access") or {}
            airport = access.get("nearest_airport") or {}
            lines.append(
                f"{item.get('rank')}位 {_city(item)}: 類似度 {_number(item.get('similarity'), 4)}、"
                f"最寄り{airport.get('name', '不明')} {_number(airport.get('distance_km'), 1)} km、"
                + (
                    "基準より "
                    f"{_number(item.get('nearest_distance_improvement_km'), 1)} km近い"
                    if distance_requested
                    else f"アクセススコア改善 {_number(item.get('access_score_gain'), 4)}"
                )
            )
        return lines

    return ["構造化された回答はありません。"]


def render_response(
    execution: Mapping[str, Any],
    *,
    response_provider: ResponseProvider | None = None,
) -> str:
    """Return a Japanese answer with an explicit evidence boundary."""

    result = (
        attach_response_supplement(execution, response_provider)
        if response_provider is not None
        else dict(execution)
    )
    plan = result.get("plan") or {}
    facts = result.get("hard_facts")
    errors = result.get("errors") or []
    missing = result.get("missing_structured_conditions") or []

    lines = ["回答"]
    if errors:
        lines.extend(str(error) for error in errors)
    elif facts:
        lines.extend(_summary_lines(str(plan.get("intent", "")), facts))
    else:
        lines.append("Phase 3の構造化データで実行できる部分はありません。")

    lines.extend(["", "実データに基づく根拠"])
    if facts:
        lines.append(f"- 分析: {facts.get('analysis', '不明')}")
        lines.append(f"- 根拠: {facts.get('evidence_source', '構造化データ')}")
        formula = facts.get("formula") or facts.get("score_formula") or facts.get("weight_formula")
        if formula:
            lines.append(f"- 計算式: {formula}")
        metadata = facts.get("evidence_metadata") or {}
        datasets = metadata.get("datasets") or []
        if datasets:
            editions = "、".join(
                f"{item.get('dataset')}（{item.get('edition')}）" for item in datasets
            )
            lines.append(f"- データセット/版: {editions}")
        metrics = metadata.get("metrics") or []
        if metrics:
            units = "、".join(f"{item.get('name')} [{item.get('unit')}]" for item in metrics)
            lines.append(f"- 指標/単位: {units}")
        universe = metadata.get("universe") or {}
        if universe:
            lines.append(
                f"- 比較範囲: {universe.get('label')} "
                f"({universe.get('actual_municipality_count')}都市)"
            )
        limitations = metadata.get("limitations") or []
        if limitations:
            lines.append(f"- 主な制約: {limitations[0]}")
    else:
        lines.append("- 該当する構造化分析なし")
    lines.append("- ランキング・数値計算にLLMは使用していません。")

    if missing:
        lines.extend(["", "現在の構造化データにない条件"])
        for item in missing:
            lines.append(f"- {item.get('label', item.get('condition'))}: {item.get('reason')}")

    llm_response = result.get("llm_response") or {}
    if llm_response.get("evidence_explanation"):
        lines.extend(
            [
                "",
                "LLMによる説明（Structured Evidenceの説明のみ）",
                str(llm_response["evidence_explanation"]),
            ]
        )
    if result.get("soft_knowledge"):
        lines.extend(
            [
                "",
                "Soft Knowledge（参考。ランキング未使用）",
                str(result["soft_knowledge"]),
            ]
        )
    return "\n".join(lines)


__all__ = [
    "ResponseProvider",
    "ResponseSupplement",
    "attach_response_supplement",
    "render_response",
]
