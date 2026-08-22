"""Tests for the optional Azure OpenAI planner and response adapters."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.llm import (
    AzureOpenAIChatClient,
    AzureOpenAIError,
    AzureOpenAIPlanner,
    AzureOpenAIResponse,
    AzureOpenAISettings,
)
from app.planner import INTENT_CITY_SIMILARITY, plan_query


class FakeHTTPResponse:
    def __init__(self, payload: dict[str, Any]):
        self.payload = json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]})

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.payload.encode("utf-8")


def fake_opener(_request, timeout):
    assert timeout == 30
    return FakeHTTPResponse(
        {
            "intent": INTENT_CITY_SIMILARITY,
            "city": "広島市",
            "criteria": ["city_similarity"],
            "category": None,
            "airport_metric": "nearest_distance",
            "top_n": 5,
            "missing_conditions": [],
        }
    )


def settings() -> AzureOpenAISettings:
    return AzureOpenAISettings(
        endpoint="https://example.test",
        api_key="not-a-real-key",
        chat_deployment="chat",
        timeout_seconds=30,
    )


def test_settings_require_connection_values():
    with pytest.raises(AzureOpenAIError, match="AZURE_OPENAI_API_KEY"):
        AzureOpenAISettings.from_environment(
            {
                "AZURE_OPENAI_ENDPOINT": "https://example.test",
                "AZURE_OPENAI_CHAT_DEPLOYMENT": "chat",
            }
        )


def test_settings_default_reasoning_effort_is_xhigh():
    configured = AzureOpenAISettings.from_environment(
        {
            "AZURE_OPENAI_ENDPOINT": "https://example.test",
            "AZURE_OPENAI_API_KEY": "not-a-real-key",
            "AZURE_OPENAI_CHAT_DEPLOYMENT": "gpt-5.6-luna",
        }
    )
    assert configured.chat_deployment == "gpt-5.6-luna"
    assert configured.reasoning_effort == "xhigh"
    assert configured.max_completion_tokens == 8192
    assert configured.planner_reasoning_effort == "high"
    assert configured.response_reasoning_effort == "medium"
    assert configured.comparison_reasoning_effort == "xhigh"
    assert configured.planner_max_completion_tokens == 4096
    assert configured.response_max_completion_tokens == 4096


def test_chat_payload_includes_xhigh_reasoning_effort():
    observed: dict[str, Any] = {}

    def opener(request, timeout):
        observed["payload"] = json.loads(request.data)
        assert timeout == 30
        return FakeHTTPResponse({"answer": "ok"})

    AzureOpenAIChatClient(settings(), opener=opener).complete(
        [{"role": "user", "content": "test"}]
    )
    assert observed["payload"]["reasoning_effort"] == "xhigh"


@pytest.mark.parametrize("timeout", ["nan", "inf", "-inf"])
def test_settings_reject_nonfinite_timeout(timeout: str):
    with pytest.raises(AzureOpenAIError, match="正の数"):
        AzureOpenAISettings.from_environment(
            {
                "AZURE_OPENAI_ENDPOINT": "https://example.test",
                "AZURE_OPENAI_API_KEY": "not-a-real-key",
                "AZURE_OPENAI_CHAT_DEPLOYMENT": "chat",
                "AZURE_OPENAI_TIMEOUT_SECONDS": timeout,
            }
        )


def test_client_and_planner_use_json_boundary():
    client = AzureOpenAIChatClient(settings(), opener=fake_opener)
    planner = AzureOpenAIPlanner(client)
    plan = plan_query(
        "自然が豊かで広島市と似た都市は？",
        provider=planner,
    )
    assert plan.intent == INTENT_CITY_SIMILARITY
    assert plan.city == "広島市"
    assert {item.condition for item in plan.missing_conditions} == {"nature"}


def test_response_provider_rejects_unexpected_fields():
    def invalid_opener(_request, timeout):
        assert timeout == 30
        return FakeHTTPResponse({"evidence_explanation": "説明", "unexpected": "値"})

    provider = AzureOpenAIResponse(
        AzureOpenAIChatClient(settings(), opener=invalid_opener)
    )
    with pytest.raises(AzureOpenAIError, match="許可されていない"):
        provider.generate("質問", {}, {"analysis": "test"})


def test_response_provider_joins_string_list_fields():
    def list_opener(_request, timeout):
        assert timeout == 30
        return FakeHTTPResponse(
            {"evidence_explanation": ["説明1", "説明2"], "soft_knowledge": None}
        )

    provider = AzureOpenAIResponse(
        AzureOpenAIChatClient(settings(), opener=list_opener)
    )
    result = provider.generate("質問", {}, {"analysis": "test"})
    assert result["evidence_explanation"] == "説明1\n説明2"
