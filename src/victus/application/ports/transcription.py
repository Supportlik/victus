"""Transcription port: audio bytes in, text out (SPEC R36).

The first adapter is OpenAI ``gpt-4o-transcribe``
(``infrastructure/transcription/openai_transcribe.py``); tests use an in-memory
fake. Adapters never see the database — the use case stores the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    text: str
    provider: str
    model: str
    language: str | None = None
    duration_s: float | None = None
    segments: list[dict[str, Any]] | None = None
    cost_usd: float | None = None


class TranscriptionError(Exception):
    """The provider rejected or failed the request (network, quota, format)."""


class TranscriptionPort(Protocol):
    def transcribe(
        self,
        audio: bytes,
        *,
        mime: str,
        filename: str | None = None,
        language: str | None = None,
        vocabulary_prompt: str | None = None,
    ) -> TranscriptionResult: ...
