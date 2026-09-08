"""Deterministic transcription adapter for tests."""

from __future__ import annotations

from victus.application.ports.transcription import TranscriptionError, TranscriptionResult


class FakeTranscription:
    def __init__(self, text: str = "transcribed text", *, fail: bool = False) -> None:
        self.text = text
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    def transcribe(
        self,
        audio: bytes,
        *,
        mime: str,
        filename: str | None = None,
        language: str | None = None,
        vocabulary_prompt: str | None = None,
    ) -> TranscriptionResult:
        self.calls.append(
            {
                "size": len(audio),
                "mime": mime,
                "filename": filename,
                "language": language,
                "vocabulary_prompt": vocabulary_prompt,
            }
        )
        if self.fail:
            raise TranscriptionError("fake provider failure")
        return TranscriptionResult(
            text=self.text,
            provider="fake",
            model="fake-1",
            language=language,
            duration_s=1.5,
            segments=None,
            cost_usd=0.0,
        )
