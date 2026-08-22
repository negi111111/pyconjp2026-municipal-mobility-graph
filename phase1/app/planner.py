"""Natural-language query planning without numerical reasoning.

The default planner is deliberately deterministic and offline. A caller may
inject an LLM-backed :class:`PlannerProvider`, but a provider can only select a
validated intent, entity, and criteria. It cannot supply ranks, scores, or any
other computed fact.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol, runtime_checkable

PHASE1_CITY_NAMES = (
    "広島市",
    "呉市",
    "東広島市",
    "廿日市市",
    "大竹市",
    "三原市",
    "尾道市",
    "福山市",
    "安芸高田市",
    "岩国市",
    "周南市",
    "山口市",
    "岡山市",
    "倉敷市",
    "笠岡市",
    "松江市",
    "浜田市",
    "松山市",
    "今治市",
    "高松市",
)

INTENT_BIDIRECTIONAL_FLOW = "bidirectional_flow_rank"
INTENT_FLOW_HUB = "flow_hub"
INTENT_CROSS_PREFECTURE_COMMUNITIES = "cross_prefecture_communities"
INTENT_CITY_SIMILARITY = "city_similarity"
INTENT_AIRPORT_BETTER = "airport_better_than_reference"
INTENT_SIMILAR_AIRPORT = "similar_city_search"
INTENT_CATEGORY_SIMILARITY = "category_similarity"
INTENT_AIRPORT_RANK = "airport_access_rank"
INTENT_UNSUPPORTED = "unsupported_query"

SUPPORTED_INTENTS = frozenset(
    {
        INTENT_BIDIRECTIONAL_FLOW,
        INTENT_FLOW_HUB,
        INTENT_CROSS_PREFECTURE_COMMUNITIES,
        INTENT_CITY_SIMILARITY,
        INTENT_AIRPORT_BETTER,
        INTENT_SIMILAR_AIRPORT,
        INTENT_CATEGORY_SIMILARITY,
        INTENT_AIRPORT_RANK,
        INTENT_UNSUPPORTED,
    }
)

SUPPORTED_CRITERIA = frozenset(
    {
        "city_similarity",
        "airport_access",
        "nearest_airport_distance",
        "population",
        "medical",
        "education",
        "economy",
        "welfare",
        "human_flow",
    }
)

_CONDITION_LABELS = {
    "nature": "自然の豊かさ",
    "hot_springs": "温泉",
    "rent": "家賃",
    "climate": "気候",
    "forest": "森林",
    "ocean": "海の近さ",
    "tourism": "観光資源",
    "rail_access": "鉄道・新幹線アクセス",
    "livability": "住みやすさの定義",
    "airport_polarity": "空港アクセスの向き",
    "query_intent": "解析意図",
}

_PLANNER_INTERNAL_CONDITIONS = frozenset(
    {"intent", "city", "criteria", "category", "airport_metric", "top_n"}
)

_UNSUPPORTED_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("nature", ("自然が豊か", "自然豊か", "自然環境")),
    ("hot_springs", ("温泉", "露天風呂")),
    ("rent", ("家賃", "賃料", "住宅コスト")),
    ("climate", ("気候", "積雪", "降水", "気温")),
    ("forest", ("森林", "緑被")),
    ("ocean", ("海が近", "海辺", "海岸")),
    ("tourism", ("観光", "名所")),
    ("rail_access", ("新幹線", "鉄道アクセス")),
    ("livability", ("住みやす", "暮らしやす")),
)

_CATEGORY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("medical", ("医療", "病院", "医師", "診療")),
    ("education", ("教育", "学校", "生徒", "学生")),
    ("economy", ("経済", "所得", "就業", "労働")),
    ("welfare", ("福祉", "介護", "保育")),
    ("population", ("人口", "年齢構成", "世帯")),
)

_AIRPORT_SCALE_PATTERNS = (
    "空港規模",
    "規模",
    "旅客",
    "利用者",
    "利用客",
    "乗降客",
    "大きい空港",
    "大規模空港",
    "アクセススコア",
    "スコア",
)

_AIRPORT_NEGATIVE_PATTERNS = (
    "悪い",
    "遠い",
    "遠く",
    "長い",
    "低い",
    "劣る",
    "不便",
    "離れ",
)


@dataclass(frozen=True)
class MissingCondition:
    """A requested condition not present in the Phase 1 structured data."""

    condition: str
    label: str
    reason: str = "Phase 1の構造化データには収録されていません。"

    def to_dict(self) -> dict[str, str]:
        return {
            "condition": self.condition,
            "label": self.label,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class QueryPlan:
    """Validated operations requested by a natural-language question."""

    query: str
    intent: str
    city: str | None = None
    criteria: tuple[str, ...] = ()
    category: str | None = None
    airport_metric: str = "nearest_distance"
    top_n: int = 5
    missing_conditions: tuple[MissingCondition, ...] = ()
    planner: str = "rules"

    def __post_init__(self) -> None:
        if self.intent not in SUPPORTED_INTENTS:
            raise ValueError(f"unsupported intent: {self.intent!r}")
        if self.top_n <= 0:
            raise ValueError("top_n must be positive")
        if self.airport_metric not in {"access_score", "nearest_distance"}:
            raise ValueError("airport_metric must be 'access_score' or 'nearest_distance'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "intent": self.intent,
            "city": self.city,
            "criteria": list(self.criteria),
            "category": self.category,
            "airport_metric": self.airport_metric,
            "top_n": self.top_n,
            "missing_conditions": [item.to_dict() for item in self.missing_conditions],
            "planner": self.planner,
        }


@runtime_checkable
class PlannerProvider(Protocol):
    """Optional LLM planner boundary.

    Implementations may interpret language and return a plan mapping. Numeric
    analytical outputs are intentionally absent from both arguments and the
    accepted schema; all numbers are computed later by :class:`QueryExecutor`.
    """

    name: str

    def plan(self, query: str, available_cities: Sequence[str]) -> QueryPlan | Mapping[str, Any]:
        """Select an intent, city, criteria, and display limit."""


def _compact(text: str) -> str:
    return re.sub(r"[\s　]+", "", text)


def _city_aliases(city_names: Sequence[str]) -> list[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for raw_name in city_names:
        name = str(raw_name).strip()
        if not name:
            continue
        pairs.add((_compact(name), name))
        if name.endswith("市") and len(name) > 1:
            pairs.add((_compact(name[:-1]), name))
    return sorted(pairs, key=lambda item: (-len(item[0]), item[0], item[1]))


def _extract_city(query: str, city_names: Sequence[str]) -> str | None:
    compact = _compact(query)
    matches: list[tuple[int, int, str]] = []
    for alias, canonical in _city_aliases(city_names):
        position = compact.find(alias)
        if position >= 0:
            matches.append((position, -len(alias), canonical))
    if not matches:
        return None
    return min(matches)[2]


def _top_n(query: str, *, default: int = 5) -> int:
    if any(token in query for token in ("一番", "最も", "最大", "1位")):
        return 1
    match = re.search(r"(?:上位)?\s*([1-9][0-9]?)\s*(?:件|都市|市|位)", query)
    return int(match.group(1)) if match else default


def _missing_conditions(query: str) -> tuple[MissingCondition, ...]:
    found: list[MissingCondition] = []
    for key, patterns in _UNSUPPORTED_PATTERNS:
        if any(pattern in query for pattern in patterns):
            found.append(MissingCondition(key, _CONDITION_LABELS[key]))
    return tuple(found)


def _category(query: str) -> str | None:
    for category, patterns in _CATEGORY_PATTERNS:
        if any(pattern in query for pattern in patterns):
            return category
    return None


def _requests_airport_scale(query: str) -> bool:
    """Return whether the wording explicitly requests airport size/passenger scale."""

    return "空港" in query and any(pattern in query for pattern in _AIRPORT_SCALE_PATTERNS)


def _requests_negative_airport_access(query: str) -> bool:
    """Return whether a query asks for worse, farther, or less convenient access."""

    compact = _compact(query)
    if "悪くない" in compact:
        return False
    negative = "|".join(re.escape(pattern) for pattern in _AIRPORT_NEGATIVE_PATTERNS)
    return bool(
        re.search(rf"空港[^。！？、,]{{0,8}}(?:{negative})", compact)
        or re.search(rf"(?:{negative})[^。！？、,]{{0,8}}空港", compact)
    )


class RuleBasedPlanner:
    """Deterministic Japanese planner covering the Phase 1 question families."""

    name = "offline_japanese_rules_v1"

    def __init__(self, city_names: Sequence[str] = PHASE1_CITY_NAMES):
        self.city_names = tuple(dict.fromkeys(str(name) for name in city_names))

    def plan(
        self,
        query: str,
        available_cities: Sequence[str] | None = None,
    ) -> QueryPlan:
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        cities = tuple(available_cities or self.city_names)
        city = _extract_city(query, cities)
        missing = _missing_conditions(query)
        top_n = _top_n(query)
        category = _category(query)
        similarity_words = (
            "似て",
            "似た",
            "似ている",
            "みたいな",
            "のような",
            "同じよう",
            "近い特性",
        )
        has_similarity = any(word in query for word in similarity_words)
        has_airport = "空港" in query
        # Phase 1 defines generic airport accessibility as straight-line distance
        # to the nearest scheduled airport. The distance-and-scale score is an
        # explicit opt-in for questions that mention scale or passengers.
        airport_metric = "access_score" if _requests_airport_scale(query) else "nearest_distance"

        if has_airport and _requests_negative_airport_access(query):
            intent = INTENT_UNSUPPORTED
            criteria = ()
            missing = (
                *missing,
                MissingCondition(
                    "airport_polarity",
                    _CONDITION_LABELS["airport_polarity"],
                    "Phase 1は「近い」「良い」方向の空港アクセス比較だけを定義しています。",
                ),
            )
        elif category is not None and has_similarity:
            intent = INTENT_CATEGORY_SIMILARITY
            criteria = (category,)
        elif has_similarity and has_airport:
            intent = INTENT_SIMILAR_AIRPORT
            criteria = (
                "city_similarity",
                (
                    "nearest_airport_distance"
                    if airport_metric == "nearest_distance"
                    else "airport_access"
                ),
            )
        elif has_airport and city is not None and any(
            word in query for word in ("より", "比べ", "上回", "良い", "優れ")
        ):
            intent = INTENT_AIRPORT_BETTER
            criteria = (
                (
                    "nearest_airport_distance"
                    if airport_metric == "nearest_distance"
                    else "airport_access"
                ),
            )
        elif has_airport:
            intent = INTENT_AIRPORT_RANK
            criteria = (
                (
                    "nearest_airport_distance"
                    if airport_metric == "nearest_distance"
                    else "airport_access"
                ),
            )
        elif any(word in query for word in ("生活圏", "コミュニティ", "地域圏")) and any(
            word in query for word in ("県境", "行政境界", "人流", "実質")
        ):
            intent = INTENT_CROSS_PREFECTURE_COMMUNITIES
            criteria = ("human_flow",)
        elif any(word in query for word in ("人流ハブ", "ハブ", "人流の拠点", "中心性")):
            intent = INTENT_FLOW_HUB
            criteria = ("human_flow",)
        elif has_similarity:
            intent = INTENT_CITY_SIMILARITY
            criteria = ("city_similarity",)
        elif any(
            word in query
            for word in ("行き来", "人の移動", "人流が多", "交流が多", "通勤通学")
        ):
            intent = INTENT_BIDIRECTIONAL_FLOW
            criteria = ("human_flow",)
        else:
            intent = INTENT_UNSUPPORTED
            criteria = ()
            if not missing:
                missing = (
                    MissingCondition(
                        "query_intent",
                        _CONDITION_LABELS["query_intent"],
                        "Phase 1の7種類の分析意図に分類できませんでした。",
                    ),
                )

        return QueryPlan(
            query=query.strip(),
            intent=intent,
            city=city,
            criteria=criteria,
            category=category if intent == INTENT_CATEGORY_SIMILARITY else None,
            airport_metric=airport_metric,
            top_n=top_n,
            missing_conditions=missing,
            planner=self.name,
        )


def _coerce_missing(value: Any) -> MissingCondition:
    if isinstance(value, MissingCondition):
        return value
    if isinstance(value, Mapping):
        key = str(value.get("condition", value.get("key", "unknown")))
        return MissingCondition(
            condition=key,
            label=str(value.get("label", _CONDITION_LABELS.get(key, key))),
            reason=str(
                value.get("reason", "Phase 1の構造化データには収録されていません。")
            ),
        )
    key = str(value)
    return MissingCondition(key, _CONDITION_LABELS.get(key, key))


def validate_provider_plan(
    query: str,
    raw: QueryPlan | Mapping[str, Any],
    *,
    provider_name: str,
) -> QueryPlan:
    """Discard non-plan fields and move unknown criteria to missing data."""

    if isinstance(raw, QueryPlan):
        candidate = replace(raw, query=query, planner=provider_name)
    else:
        if not isinstance(raw, Mapping):
            raise ValueError("planner provider must return a QueryPlan or mapping")
        intent = str(raw.get("intent") or INTENT_UNSUPPORTED)
        criteria_raw = raw.get("criteria") or ()
        if isinstance(criteria_raw, str):
            criteria_raw = (criteria_raw,)
        top_n_raw = raw.get("top_n")
        candidate = QueryPlan(
            query=query,
            intent=intent,
            city=str(raw["city"]) if raw.get("city") is not None else None,
            criteria=tuple(str(item) for item in criteria_raw),
            category=str(raw["category"]) if raw.get("category") is not None else None,
            airport_metric=str(raw.get("airport_metric") or "nearest_distance"),
            top_n=int(top_n_raw) if top_n_raw not in (None, "") else 5,
            missing_conditions=tuple(
                _coerce_missing(item) for item in (raw.get("missing_conditions") or ())
            ),
            planner=provider_name,
        )

    # Even an LLM provider cannot silently reinterpret generic "airport access"
    # as the distance-and-scale score. That score requires explicit wording.
    if candidate.airport_metric == "access_score" and not _requests_airport_scale(query):
        candidate = replace(candidate, airport_metric="nearest_distance")

    supported: list[str] = []
    missing = [
        item
        for item in candidate.missing_conditions
        if item.condition not in _PLANNER_INTERNAL_CONDITIONS
        and item.condition not in SUPPORTED_CRITERIA
        and item.condition != "nearest_airport_distance"
    ]
    known_missing = {item.condition for item in missing}
    for item in _missing_conditions(query):
        if item.condition not in known_missing:
            missing.append(item)
            known_missing.add(item.condition)
    for criterion in candidate.criteria:
        if criterion in SUPPORTED_CRITERIA:
            normalized = (
                "nearest_airport_distance"
                if criterion == "airport_access" and candidate.airport_metric == "nearest_distance"
                else criterion
            )
            if normalized not in supported:
                supported.append(normalized)
        elif criterion not in known_missing:
            missing.append(_coerce_missing(criterion))
            known_missing.add(criterion)
    return replace(candidate, criteria=tuple(supported), missing_conditions=tuple(missing))


def plan_query(
    query: str,
    *,
    available_cities: Sequence[str] = PHASE1_CITY_NAMES,
    provider: PlannerProvider | None = None,
) -> QueryPlan:
    """Create a validated plan using offline rules or an injected provider."""

    if provider is None:
        return RuleBasedPlanner(available_cities).plan(query, available_cities)
    raw = provider.plan(query, available_cities)
    return validate_provider_plan(query, raw, provider_name=provider.name)


__all__ = [
    "INTENT_AIRPORT_BETTER",
    "INTENT_AIRPORT_RANK",
    "INTENT_BIDIRECTIONAL_FLOW",
    "INTENT_CATEGORY_SIMILARITY",
    "INTENT_CITY_SIMILARITY",
    "INTENT_CROSS_PREFECTURE_COMMUNITIES",
    "INTENT_FLOW_HUB",
    "INTENT_SIMILAR_AIRPORT",
    "INTENT_UNSUPPORTED",
    "MissingCondition",
    "PHASE1_CITY_NAMES",
    "PlannerProvider",
    "QueryPlan",
    "RuleBasedPlanner",
    "SUPPORTED_CRITERIA",
    "SUPPORTED_INTENTS",
    "plan_query",
    "validate_provider_plan",
]
