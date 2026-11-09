"""Model access behind a small protocol so the runner is testable without a network.

``AnthropicModelClient`` talks to the Claude API (``anthropic`` SDK): adaptive
thinking, ``output_config.effort``, optional server-side refusal fallbacks.
``ScriptedModelClient`` replays a fixed sequence of turns for tests.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass(frozen=True, slots=True)
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """What the runner needs from one model turn."""

    stop_reason: str
    text: str
    tool_uses: list[ToolUse]
    # The assistant content exactly as it must be echoed back (thinking, text, tool_use, …).
    content_params: list[dict[str, Any]]
    input_tokens: int
    output_tokens: int
    model: str
    stop_details: dict[str, Any] | None = None
    #: Prompt caching: input written to the cache and input read from it. Both come on top
    #: of ``input_tokens``, which counts only the uncached rest.
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    #: Web searches the server ran during this turn (``agent.web``); billed per search.
    web_search_requests: int = 0


class ModelError(Exception):
    """A model call failed. ``retryable`` marks transient failures (429, 5xx, network)."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class ModelClient(Protocol):
    @property
    def model(self) -> str: ...

    def create(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse: ...


# ── Anthropic ───────────────────────────────────────────────────────────────


class AnthropicModelClient:
    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        effort: str = "medium",
        max_tokens: int = 16_000,
        fallbacks: bool = True,
        timeout_s: float = 600.0,
        prompt_cache: bool = True,
    ) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=2)
        self._model = model
        self._effort = effort
        self._max_tokens = max_tokens
        self._fallbacks = fallbacks
        self._prompt_cache = prompt_cache

    @property
    def model(self) -> str:
        return self._model

    def create(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        import anthropic

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": messages,
            "tools": tools,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self._effort},
        }
        if self._prompt_cache:
            # Automatic caching: the breakpoint moves to the last block of every request, so
            # each turn of a day session reads tools, system prompt, the first message (with
            # its images) and every earlier turn from the cache.
            kwargs["cache_control"] = {"type": "ephemeral"}
        try:
            if self._fallbacks:
                response: Any = self._client.beta.messages.create(
                    **kwargs, betas=[FALLBACK_BETA], fallbacks="default"
                )
            else:
                response = self._client.messages.create(**kwargs)
        except anthropic.RateLimitError as exc:
            raise ModelError(f"rate limited: {exc}", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            raise ModelError(
                f"API error {exc.status_code}: {exc.message}", retryable=exc.status_code >= 500
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ModelError(f"connection error: {exc}", retryable=True) from exc
        return _from_sdk(response)


def _from_sdk(response: Any) -> ModelResponse:
    text_parts: list[str] = []
    tool_uses: list[ToolUse] = []
    params: list[dict[str, Any]] = []
    for block in response.content:
        params.append(block.model_dump(mode="json", exclude_none=True))
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            raw = block.input
            tool_uses.append(ToolUse(id=block.id, name=block.name, input=dict(raw) if raw else {}))
    details = None
    if getattr(response, "stop_details", None) is not None:
        details = response.stop_details.model_dump(mode="json", exclude_none=True)
    return ModelResponse(
        stop_reason=response.stop_reason or "end_turn",
        text="\n".join(text_parts).strip(),
        tool_uses=tool_uses,
        content_params=params,
        input_tokens=int(response.usage.input_tokens),
        output_tokens=int(response.usage.output_tokens),
        model=str(response.model),
        stop_details=details,
        cache_creation_input_tokens=int(
            getattr(response.usage, "cache_creation_input_tokens", None) or 0
        ),
        cache_read_input_tokens=int(getattr(response.usage, "cache_read_input_tokens", None) or 0),
        web_search_requests=int(
            getattr(getattr(response.usage, "server_tool_use", None), "web_search_requests", None)
            or 0
        ),
    )


# ── scripted (tests, dry runs) ──────────────────────────────────────────────


@dataclass(slots=True)
class ScriptedTurn:
    """One scripted assistant turn: tool calls (dicts or callables) and/or text."""

    tool_calls: Sequence[
        tuple[str, dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]]]
    ] = ()
    text: str = ""
    stop_reason: str | None = None
    input_tokens: int = 1_000
    output_tokens: int = 200
    stop_details: dict[str, Any] | None = None
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    #: Content blocks the server would have produced itself (``server_tool_use``,
    #: ``web_search_tool_result``, …), echoed back like the rest of the turn.
    server_blocks: Sequence[dict[str, Any]] = ()
    web_search_requests: int = 0


@dataclass(slots=True)
class ScriptedModelClient:
    """Replays ``turns`` in order; callable tool inputs receive a memo dict the test controls
    (the runner stores the last tool result per tool name under ``memo["results"]``)."""

    turns: list[ScriptedTurn]
    model_name: str = "scripted-model"
    memo: dict[str, Any] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)
    _index: int = 0

    @property
    def model(self) -> str:
        return self.model_name

    def create(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        self.calls.append({"system": system, "messages": list(messages), "tools": list(tools)})
        self._remember_results(messages)
        if self._index >= len(self.turns):
            turn = ScriptedTurn(text="(script exhausted)")
        else:
            turn = self.turns[self._index]
            self._index += 1
        tool_uses: list[ToolUse] = []
        params: list[dict[str, Any]] = []
        params.extend(dict(b) for b in turn.server_blocks)
        if turn.text:
            params.append({"type": "text", "text": turn.text})
        for i, (name, inp) in enumerate(turn.tool_calls):
            payload = inp(self.memo) if callable(inp) else dict(inp)
            tid = f"toolu_{self._index}_{i}"
            tool_uses.append(ToolUse(id=tid, name=name, input=payload))
            params.append({"type": "tool_use", "id": tid, "name": name, "input": payload})
        stop = turn.stop_reason or ("tool_use" if tool_uses else "end_turn")
        return ModelResponse(
            stop_reason=stop,
            text=turn.text,
            tool_uses=tool_uses,
            content_params=params,
            input_tokens=turn.input_tokens,
            output_tokens=turn.output_tokens,
            model=self.model_name,
            stop_details=turn.stop_details,
            cache_creation_input_tokens=turn.cache_creation_input_tokens,
            cache_read_input_tokens=turn.cache_read_input_tokens,
            web_search_requests=turn.web_search_requests,
        )

    def _remember_results(self, messages: list[dict[str, Any]]) -> None:
        """Expose the latest tool results to callable tool inputs (e.g. product ids)."""
        results = self.memo.setdefault("results", {})
        names: dict[str, str] = {}
        for m in messages:
            content = m.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if block.get("type") == "tool_use":
                    names[block["id"]] = block["name"]
                elif block.get("type") == "tool_result":
                    name = names.get(block.get("tool_use_id", ""), "?")
                    results[name] = block.get("content")
