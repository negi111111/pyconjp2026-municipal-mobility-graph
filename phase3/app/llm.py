"""Azure OpenAI adapters for the validated Phase 3 planner and response boundary."""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .planner import (
    PHASE1_CITY_NAMES,
    SUPPORTED_CRITERIA,
    SUPPORTED_INTENTS,
    RuleBasedPlanner,
)

DEFAULT_API_VERSION = "2025-04-01-preview"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_COMPLETION_TOKENS = 8192
DEFAULT_REASONING_EFFORT = "xhigh"
DEFAULT_PLANNER_REASONING_EFFORT = "high"
DEFAULT_RESPONSE_REASONING_EFFORT = "medium"
DEFAULT_COMPARISON_REASONING_EFFORT = "xhigh"
DEFAULT_PLANNER_MAX_COMPLETION_TOKENS = 4096
DEFAULT_RESPONSE_MAX_COMPLETION_TOKENS = 4096
DEFAULT_COMPARISON_MAX_COMPLETION_TOKENS = 8192
SUPPORTED_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh"})


class AzureOpenAIError(RuntimeError):
    """Raised when an Azure OpenAI request or response cannot be used safely."""


def _load_project_dotenv(path: Path | None = None) -> None:
    """Load the existing project dotenv helper without exposing its values."""

    try:
        from pipeline._common import load_dotenv
    except ModuleNotFoundError:
        return
    if path is not None:
        load_dotenv(path)
        return
    phase_root = Path(__file__).resolve().parents[1]
    phase_dotenv = phase_root / ".env"
    repository_dotenv = phase_root.parent / ".env"
    load_dotenv(phase_dotenv if phase_dotenv.exists() else repository_dotenv)


def _required_environment(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise AzureOpenAIError(f"Azure OpenAIの環境変数 {name} が設定されていません。")
    return value


def _positive_float(value: str, name: str, default: float) -> float:
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise AzureOpenAIError(f"{name} は正の数で指定してください。") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise AzureOpenAIError(f"{name} は正の数で指定してください。")
    return parsed


def _positive_int(value: str, name: str, default: int) -> int:
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise AzureOpenAIError(f"{name} は正の整数で指定してください。") from exc
    if parsed <= 0:
        raise AzureOpenAIError(f"{name} は正の整数で指定してください。")
    return parsed


def _reasoning_effort(value: str, name: str, default: str) -> str:
    parsed = value.strip().lower() or default
    if parsed not in SUPPORTED_REASONING_EFFORTS:
        raise AzureOpenAIError(f"{name} はnone/low/medium/high/xhighのいずれかです。")
    return parsed


@dataclass(frozen=True)
class AzureOpenAISettings:
    """Connection settings loaded from environment variables."""

    endpoint: str
    api_key: str = field(repr=False)
    api_version: str = DEFAULT_API_VERSION
    chat_deployment: str = ""
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS
    reasoning_effort: str | None = DEFAULT_REASONING_EFFORT
    planner_reasoning_effort: str = DEFAULT_PLANNER_REASONING_EFFORT
    response_reasoning_effort: str = DEFAULT_RESPONSE_REASONING_EFFORT
    comparison_reasoning_effort: str = DEFAULT_COMPARISON_REASONING_EFFORT
    planner_max_completion_tokens: int = DEFAULT_PLANNER_MAX_COMPLETION_TOKENS
    response_max_completion_tokens: int = DEFAULT_RESPONSE_MAX_COMPLETION_TOKENS
    comparison_max_completion_tokens: int = DEFAULT_COMPARISON_MAX_COMPLETION_TOKENS

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        dotenv_path: Path | None = None,
    ) -> AzureOpenAISettings:
        """Create settings, loading the project ``.env`` only when needed."""

        if environment is None:
            _load_project_dotenv(dotenv_path)
            environment = os.environ

        endpoint = _required_environment(environment, "AZURE_OPENAI_ENDPOINT").rstrip("/")
        parsed_endpoint = urllib.parse.urlparse(endpoint)
        if parsed_endpoint.scheme not in {"http", "https"} or not parsed_endpoint.netloc:
            raise AzureOpenAIError("AZURE_OPENAI_ENDPOINT は有効なHTTP(S) URLで指定してください。")

        reasoning_effort = _reasoning_effort(
            environment.get("AZURE_OPENAI_REASONING_EFFORT", ""),
            "AZURE_OPENAI_REASONING_EFFORT",
            DEFAULT_REASONING_EFFORT,
        )

        return cls(
            endpoint=endpoint,
            api_key=_required_environment(environment, "AZURE_OPENAI_API_KEY"),
            api_version=environment.get("AZURE_OPENAI_API_VERSION", DEFAULT_API_VERSION).strip()
            or DEFAULT_API_VERSION,
            chat_deployment=_required_environment(environment, "AZURE_OPENAI_CHAT_DEPLOYMENT"),
            timeout_seconds=_positive_float(
                environment.get("AZURE_OPENAI_TIMEOUT_SECONDS", ""),
                "AZURE_OPENAI_TIMEOUT_SECONDS",
                DEFAULT_TIMEOUT_SECONDS,
            ),
            max_completion_tokens=_positive_int(
                environment.get("AZURE_OPENAI_MAX_COMPLETION_TOKENS", ""),
                "AZURE_OPENAI_MAX_COMPLETION_TOKENS",
                DEFAULT_MAX_COMPLETION_TOKENS,
            ),
            reasoning_effort=reasoning_effort,
            planner_reasoning_effort=_reasoning_effort(
                environment.get("AZURE_OPENAI_PLANNER_REASONING_EFFORT", ""),
                "AZURE_OPENAI_PLANNER_REASONING_EFFORT",
                DEFAULT_PLANNER_REASONING_EFFORT,
            ),
            response_reasoning_effort=_reasoning_effort(
                environment.get("AZURE_OPENAI_RESPONSE_REASONING_EFFORT", ""),
                "AZURE_OPENAI_RESPONSE_REASONING_EFFORT",
                DEFAULT_RESPONSE_REASONING_EFFORT,
            ),
            comparison_reasoning_effort=_reasoning_effort(
                environment.get("AZURE_OPENAI_COMPARISON_REASONING_EFFORT", ""),
                "AZURE_OPENAI_COMPARISON_REASONING_EFFORT",
                DEFAULT_COMPARISON_REASONING_EFFORT,
            ),
            planner_max_completion_tokens=_positive_int(
                environment.get("AZURE_OPENAI_PLANNER_MAX_COMPLETION_TOKENS", ""),
                "AZURE_OPENAI_PLANNER_MAX_COMPLETION_TOKENS",
                DEFAULT_PLANNER_MAX_COMPLETION_TOKENS,
            ),
            response_max_completion_tokens=_positive_int(
                environment.get("AZURE_OPENAI_RESPONSE_MAX_COMPLETION_TOKENS", ""),
                "AZURE_OPENAI_RESPONSE_MAX_COMPLETION_TOKENS",
                DEFAULT_RESPONSE_MAX_COMPLETION_TOKENS,
            ),
            comparison_max_completion_tokens=_positive_int(
                environment.get("AZURE_OPENAI_COMPARISON_MAX_COMPLETION_TOKENS", ""),
                "AZURE_OPENAI_COMPARISON_MAX_COMPLETION_TOKENS",
                DEFAULT_COMPARISON_MAX_COMPLETION_TOKENS,
            ),
        )


def _error_detail(payload: Any) -> str:
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            code = str(error.get("code", "")).strip()
            message = str(error.get("message", "")).strip()
            detail = ": ".join(item for item in (code, message) if item)
            if detail:
                return detail[:400]
        return json.dumps(dict(payload), ensure_ascii=False)[:400]
    return str(payload)[:400]


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
        if text.startswith("json\n"):
            text = text[5:]
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AzureOpenAIError("LLMのJSON応答を解析できませんでした。") from exc
    if not isinstance(value, dict):
        raise AzureOpenAIError("LLMの応答はJSONオブジェクトである必要があります。")
    return value


def _message_text(payload: Mapping[str, Any]) -> str:
    try:
        message = payload["choices"][0]["message"]
        content = message["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AzureOpenAIError(
            "Azure OpenAI応答にchoices[0].message.contentがありません。"
        ) from exc
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts = [
            item.get("text", "")
            for item in content
            if isinstance(item, Mapping) and isinstance(item.get("text"), str)
        ]
        if "".join(parts).strip():
            return "".join(parts)
    raise AzureOpenAIError("Azure OpenAI応答の本文が空です。")


class AzureOpenAIChatClient:
    """Minimal standard-library client for Azure OpenAI chat completions."""

    def __init__(
        self,
        settings: AzureOpenAISettings,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ):
        self.settings = settings
        self._opener = opener

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        dotenv_path: Path | None = None,
    ) -> AzureOpenAIChatClient:
        return cls(
            AzureOpenAISettings.from_environment(environment, dotenv_path=dotenv_path)
        )

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        json_object: bool = False,
        max_completion_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> str:
        effective_reasoning_effort = (
            _reasoning_effort(
                reasoning_effort,
                "reasoning_effort",
                self.settings.reasoning_effort or DEFAULT_REASONING_EFFORT,
            )
            if reasoning_effort is not None
            else self.settings.reasoning_effort
        )
        payload: dict[str, Any] = {
            "messages": [dict(message) for message in messages],
            "max_completion_tokens": max_completion_tokens or self.settings.max_completion_tokens,
        }
        if json_object:
            payload["response_format"] = {"type": "json_object"}
        if effective_reasoning_effort is not None:
            payload["reasoning_effort"] = effective_reasoning_effort

        deployment = urllib.parse.quote(self.settings.chat_deployment, safe="")
        url = (
            f"{self.settings.endpoint}/openai/deployments/{deployment}/chat/completions"
            f"?api-version={urllib.parse.quote(self.settings.api_version, safe='')}"
        )
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"api-key": self.settings.api_key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.settings.timeout_seconds) as response:
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                body: Any = json.loads(raw)
            except json.JSONDecodeError:
                body = raw
            raise AzureOpenAIError(
                f"Azure OpenAI呼び出しに失敗しました（HTTP {exc.code}）: {_error_detail(body)}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AzureOpenAIError(f"Azure OpenAIへの接続に失敗しました: {exc}") from exc

        try:
            response_payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AzureOpenAIError("Azure OpenAIの応答がJSONではありません。") from exc
        if not isinstance(response_payload, Mapping):
            raise AzureOpenAIError("Azure OpenAIの応答形式が不正です。")
        return _message_text(response_payload)

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_completion_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        return _parse_json_object(
            self.complete(
                messages,
                json_object=True,
                max_completion_tokens=max_completion_tokens,
                reasoning_effort=reasoning_effort,
            )
        )


class AzureOpenAIPlanner:
    """Use Azure OpenAI only to select a validated query plan."""

    name = "azure_openai_chat_planner_v1"

    def __init__(
        self,
        client: AzureOpenAIChatClient,
        *,
        city_names: Sequence[str] = PHASE1_CITY_NAMES,
    ):
        self.client = client
        self.city_names = tuple(city_names)

    def plan(self, query: str, available_cities: Sequence[str]) -> Mapping[str, Any]:
        cities = tuple(available_cities or self.city_names)
        system = (
            "You are a strict query planner for a Japanese public-data city analysis system. "
            "Return only a JSON object. Select one supported intent and extract the reference "
            "city. Never calculate, invent, rank, or return any numeric result. Conditions not "
            "present in the structured data must be listed in missing_conditions. "
            f"Supported intents: {sorted(SUPPORTED_INTENTS)}. "
            f"Supported criteria: {sorted(SUPPORTED_CRITERIA)}."
        )
        user = json.dumps(
            {
                "query": query,
                "available_cities": cities,
                "output_schema": {
                    "intent": "supported intent string",
                    "city": "canonical city name or null",
                    "region": "one supported region or null",
                    "exclude_regions": ["supported regions to exclude"],
                    "population_min": "integer or null",
                    "population_max": "integer or null",
                    "criteria": ["supported criterion strings"],
                    "category": "population/medical/education/economy/welfare or null",
                    "airport_metric": "nearest_distance or access_score",
                    "top_n": "positive integer",
                    "missing_conditions": [
                        {"condition": "key", "label": "Japanese label", "reason": "Japanese reason"}
                    ],
                },
            },
            ensure_ascii=False,
        )
        raw = self.client.complete_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_completion_tokens=self.client.settings.planner_max_completion_tokens,
            reasoning_effort=self.client.settings.planner_reasoning_effort,
        )
        # Keep the remote model responsible for language understanding while
        # using the deterministic Phase 3 grammar as a semantic guard.
        guarded = RuleBasedPlanner(cities).plan(query, cities)
        normalized = dict(raw)
        guarded_missing = [item.to_dict() for item in guarded.missing_conditions]
        guarded_missing_keys = {
            entry["condition"] for entry in guarded_missing
        }
        raw_missing = [
            item for item in (raw.get("missing_conditions") or ()) if isinstance(item, Mapping)
        ]
        merged_missing = guarded_missing + [
            item
            for item in raw_missing
            if str(item.get("condition")) not in guarded_missing_keys
        ]
        normalized.update(
            {
                "intent": guarded.intent,
                "city": guarded.city,
                "region": guarded.region,
                "exclude_regions": list(guarded.exclude_regions),
                "population_min": guarded.population_min,
                "population_max": guarded.population_max,
                "criteria": list(guarded.criteria),
                "category": guarded.category,
                "airport_metric": guarded.airport_metric,
                "top_n": guarded.top_n,
                "missing_conditions": merged_missing,
            }
        )
        return normalized


class AzureOpenAIResponse:
    """Use Azure OpenAI to explain computed evidence without changing it."""

    name = "azure_openai_chat_response_v1"

    def __init__(self, client: AzureOpenAIChatClient):
        self.client = client

    @staticmethod
    def _text_field(value: Any, key: str) -> str | None:
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, list):
            if all(isinstance(item, str) for item in value):
                return "\n".join(item for item in value if item)
            if all(
                isinstance(item, Mapping)
                and item
                and all(isinstance(part, str) for part in item.values())
                for item in value
            ):
                return "\n".join(
                    "\n".join(str(part) for part in item.values()) for item in value
                )
        if isinstance(value, Mapping) and value and all(
            isinstance(part, str) for part in value.values()
        ):
            return "\n".join(str(part) for part in value.values())
        raise AzureOpenAIError(
            f"LLMの回答JSONの{key}は文字列、文字列配列、文字列オブジェクト、"
            "またはnullである必要があります。"
        )

    def generate(
        self,
        query: str,
        plan: Mapping[str, Any],
        hard_facts: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        system = (
            "You are a Japanese answer writer. The hard_facts JSON is authoritative computed "
            "evidence. Explain it clearly, but do not recalculate, reorder, or add numeric facts. "
            "Do not put hard facts in soft_knowledge. Return only a JSON object with exactly two "
            "keys: evidence_explanation and soft_knowledge. Use null when no soft knowledge is "
            "needed. Soft knowledge must be explicitly labelled as general background."
        )
        user = json.dumps(
            {
                "query": query,
                "validated_plan": dict(plan),
                "hard_facts": hard_facts,
            },
            ensure_ascii=False,
        )
        result = self.client.complete_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_completion_tokens=self.client.settings.response_max_completion_tokens,
            reasoning_effort=self.client.settings.response_reasoning_effort,
        )
        unknown = set(result).difference({"evidence_explanation", "soft_knowledge"})
        if unknown:
            raise AzureOpenAIError(
                "LLMの回答JSONに許可されていないフィールドがあります: "
                + ", ".join(sorted(unknown))
            )
        return {
            **result,
            "evidence_explanation": self._text_field(
                result.get("evidence_explanation"), "evidence_explanation"
            ),
            "soft_knowledge": self._text_field(
                result.get("soft_knowledge"), "soft_knowledge"
            ),
        }


__all__ = [
    "AzureOpenAIChatClient",
    "AzureOpenAIError",
    "AzureOpenAIPlanner",
    "AzureOpenAIResponse",
    "AzureOpenAISettings",
]
