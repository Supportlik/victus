"""The Anthropic model adapter against a faked HTTP transport, plus budget edges.

No network: the SDK client inside ``AnthropicModelClient`` is replaced by one whose
``httpx2`` transport (the HTTP library the SDK is built on) answers from the test, so
what is checked is exactly what the SDK sends and how the adapter reads what comes back.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2 as httpx
import pytest

from victus.agent.budget import Budget
from victus.agent.model import FALLBACK_BETA, AnthropicModelClient, ModelError
from victus.config.server import AgentBudget

Handler = Callable[[httpx.Request], httpx.Response]


def _message(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5",
        "content": [
            {"type": "thinking", "thinking": "Look up the product first.", "signature": "sig"},
            {"type": "text", "text": "  Searching the catalogue.  "},
            {"type": "tool_use", "id": "toolu_1", "name": "product_search", "input": {"q": "skyr"}},
            {"type": "tool_use", "id": "toolu_2", "name": "day_get", "input": {}},
        ],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 340},
    }
    body.update(overrides)
    return body


def _client(handler: Handler, *, fallbacks: bool = True) -> tuple[AnthropicModelClient, list]:
    """An adapter whose SDK client talks to ``handler`` instead of the API."""
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = AnthropicModelClient(
        "sk-ant-test", model="claude-opus-5", effort="high", max_tokens=4096, fallbacks=fallbacks
    )
    client._client = anthropic.Anthropic(
        api_key="sk-ant-test",
        base_url="https://api.victus.example.com",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(record)),
    )
    return client, seen


def _create(client: AnthropicModelClient) -> Any:
    return client.create(
        system="You draft days.",
        messages=[{"role": "user", "content": "Draft 2026-03-10."}],
        tools=[{"name": "product_search", "description": "x", "input_schema": {"type": "object"}}],
    )


def test_fallback_request_uses_the_beta_endpoint_and_maps_the_reply() -> None:
    """T-AGT-100: with fallbacks the adapter calls the beta endpoint with the fallback beta,
    adaptive thinking and the configured effort, and maps text, tool calls and usage."""
    client, seen = _client(lambda _r: httpx.Response(200, json=_message()))

    response = _create(client)

    assert client.model == "claude-opus-5"
    request = seen[0]
    assert request.url.path == "/v1/messages"
    assert request.url.params.get("beta") == "true"
    assert FALLBACK_BETA in request.headers["anthropic-beta"]
    body = json.loads(request.content)
    assert body["fallbacks"] == "default"
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "high"}
    assert body["max_tokens"] == 4096 and body["system"] == "You draft days."

    assert response.stop_reason == "tool_use"
    assert response.text == "Searching the catalogue."
    assert [(u.id, u.name, u.input) for u in response.tool_uses] == [
        ("toolu_1", "product_search", {"q": "skyr"}),
        ("toolu_2", "day_get", {}),
    ]
    assert [p["type"] for p in response.content_params] == [
        "thinking",
        "text",
        "tool_use",
        "tool_use",
    ]
    assert response.input_tokens == 1200 and response.output_tokens == 340
    assert response.model == "claude-opus-5"
    assert response.stop_details is None


def test_plain_request_without_fallbacks_and_a_refusal_with_details() -> None:
    """T-AGT-101: without fallbacks the stable endpoint is called; a refusal keeps its
    stop details and a missing stop reason reads as end_turn."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_message(
                content=[{"type": "text", "text": "I can't help with that."}],
                stop_reason="refusal",
                stop_details={"type": "refusal", "category": "general_harms", "explanation": "no"},
            ),
        )

    client, seen = _client(handler, fallbacks=False)
    response = _create(client)
    assert "beta" not in seen[0].url.params
    assert "fallbacks" not in json.loads(seen[0].content)
    assert response.stop_reason == "refusal"
    assert response.stop_details == {
        "type": "refusal",
        "category": "general_harms",
        "explanation": "no",
    }

    client2, _ = _client(
        lambda _r: httpx.Response(200, json=_message(stop_reason=None, content=[])),
        fallbacks=False,
    )
    empty = _create(client2)
    assert empty.stop_reason == "end_turn" and empty.text == "" and empty.tool_uses == []


def _error(status: int) -> Handler:
    payload = {"type": "error", "error": {"type": "api_error", "message": f"status {status}"}}
    return lambda _r: httpx.Response(status, json=payload)


@pytest.mark.parametrize(
    ("status", "retryable", "fragment"),
    [
        (429, True, "rate limited"),
        (529, True, "API error 529"),
        (500, True, "API error 500"),
        (400, False, "API error 400"),
    ],
)
def test_api_errors_become_model_errors(status: int, retryable: bool, fragment: str) -> None:
    """T-AGT-102: 429 and 5xx are retryable model errors, a 4xx is not."""
    client, _ = _client(_error(status))
    with pytest.raises(ModelError) as info:
        _create(client)
    assert info.value.retryable is retryable
    assert fragment in str(info.value)


def test_a_connection_failure_is_a_retryable_model_error() -> None:
    """T-AGT-103: a network failure is a retryable model error, not a crash."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client, _ = _client(refuse)
    with pytest.raises(ModelError) as info:
        _create(client)
    assert info.value.retryable is True
    assert "connection error" in str(info.value)


def test_model_error_defaults_to_not_retryable() -> None:
    """T-AGT-104: a model error raised without the flag is final."""
    assert ModelError("boom").retryable is False


def test_budget_reports_the_output_and_cost_limits() -> None:
    """T-AGT-105: the budget names the output-token and the cost limit when crossed."""
    b = Budget.from_config(
        AgentBudget(max_input_tokens=1000, max_output_tokens=100, max_usd_per_run=0.5)
    )
    b.charge(output_tokens=100)
    assert b.exceeded is not None and b.exceeded.startswith("output tokens 100")
    c = Budget.from_config(
        AgentBudget(max_input_tokens=1000, max_output_tokens=100, max_usd_per_run=0.5)
    )
    c.charge(usd=0.5)
    assert c.exceeded == "cost 0.50 USD >= 0.50 USD"
