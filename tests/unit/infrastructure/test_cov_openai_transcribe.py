"""The OpenAI transcription adapter against a faked HTTP transport and a faked ffmpeg.

No network and no ffmpeg binary: the adapter's ``client`` is an ``openai.OpenAI`` whose
``httpx2`` transport (the HTTP library the SDK is built on) answers from the test, and
``shutil.which`` / ``subprocess.run`` are replaced where the adapter shells out.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2 as httpx
import openai
import pytest

from victus.application.ports.transcription import TranscriptionError
from victus.infrastructure.transcription import openai_transcribe as mod
from victus.infrastructure.transcription.openai_transcribe import OpenAITranscription

pytestmark = pytest.mark.domain

Handler = Callable[[httpx.Request], httpx.Response]


def _adapter(
    handler: Handler, model: str = "gpt-4o-transcribe", **kwargs: Any
) -> tuple[OpenAITranscription, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    adapter = OpenAITranscription("sk-test", model, **kwargs)
    adapter.client = openai.OpenAI(
        api_key="sk-test",
        base_url="https://api.victus.example.com/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(record)),
    )
    return adapter, seen


def _json(body: dict[str, Any]) -> Handler:
    return lambda _r: httpx.Response(200, json=body)


class FakeFfmpeg:
    """Stands in for the ffmpeg binary: conversion writes ``output``, probing prints ``probe``."""

    def __init__(self, output: bytes = b"ID3mp3", probe: str = "time=00:00:30.00") -> None:
        self.output = output
        self.probe = probe
        self.calls: list[list[str]] = []
        self.fail_convert: BaseException | None = None
        self.fail_probe: BaseException | None = None

    def run(self, cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(cmd)
        if "null" in cmd:
            if self.fail_probe is not None:
                raise self.fail_probe
            return subprocess.CompletedProcess(cmd, 0, b"", self.probe.encode())
        if self.fail_convert is not None:
            raise self.fail_convert
        Path(cmd[-1]).write_bytes(self.output)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")


@pytest.fixture
def ffmpeg(monkeypatch: pytest.MonkeyPatch) -> FakeFfmpeg:
    fake = FakeFfmpeg()
    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/opt/bin/{name}")
    monkeypatch.setattr(mod.subprocess, "run", fake.run)
    return fake


@pytest.fixture
def no_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)


VERBOSE = {
    "text": "  two slices of rye bread  ",
    "language": "english",
    "duration": 90.0,
    "segments": [
        {
            "id": 0,
            "seek": 0,
            "start": 0.0,
            "end": 4.2,
            "text": "two slices",
            "tokens": [1, 2],
            "temperature": 0.0,
            "avg_logprob": -0.1,
            "compression_ratio": 1.0,
            "no_speech_prob": 0.0,
        }
    ],
}


def test_whisper_answers_in_verbose_json_with_timings_and_cost(no_ffmpeg: None) -> None:
    """T-SVC-470: a whisper model asks for verbose JSON, passes language and vocabulary,
    keeps a native file name and books the cost from the reported duration."""
    adapter, seen = _adapter(_json(VERBOSE), model="whisper-1")

    result = adapter.transcribe(
        b"ID3audio",
        mime="audio/mpeg",
        filename="note.mp3",
        language="en",
        vocabulary_prompt="Skyr, rye bread",
    )

    body = seen[0].content.decode("utf-8", "replace")
    assert seen[0].url.path == "/v1/audio/transcriptions"
    for part in ("whisper-1", "verbose_json", "Skyr, rye bread", 'filename="note.mp3"'):
        assert part in body
    assert result.text == "two slices of rye bread"
    assert result.provider == "openai" and result.model == "whisper-1"
    assert result.language == "english"
    assert result.duration_s == 90.0
    assert result.cost_usd == pytest.approx(0.009)
    assert result.segments == [{"start": 0.0, "end": 4.2, "text": "two slices"}]


def test_gpt4o_returns_text_only_so_the_length_is_probed(ffmpeg: FakeFfmpeg) -> None:
    """T-SVC-471: a gpt-4o model answers in plain JSON; the length is measured with ffmpeg
    and the cost is derived from it. No language given: none is sent or reported."""
    adapter, seen = _adapter(_json({"text": "a banana"}))

    result = adapter.transcribe(b"RIFFwav", mime="audio/wav")

    body = seen[0].content.decode("utf-8", "replace")
    assert 'filename="audio.wav"' in body
    assert re.search(r'name="response_format"\r?\n\r?\njson\r?\n', body)
    assert 'name="language"' not in body and 'name="prompt"' not in body
    assert result.text == "a banana"
    assert result.language is None and result.segments is None
    assert result.duration_s == 30.0
    assert result.cost_usd == pytest.approx(0.003)
    assert ffmpeg.calls[0][-3:] == ["-f", "null", "-"]
    assert ffmpeg.calls[0][2].endswith("input.wav")


def test_without_ffmpeg_the_length_is_unknown_and_nothing_is_booked(no_ffmpeg: None) -> None:
    """T-SVC-472: no ffmpeg on the host: the transcript still comes back, without length."""
    adapter, _ = _adapter(_json({"text": "oats"}))
    result = adapter.transcribe(b"x", mime="audio/webm", filename="rec.WEBM")
    assert result.text == "oats"
    assert result.duration_s is None and result.cost_usd is None


def test_a_failing_probe_is_silent(ffmpeg: FakeFfmpeg) -> None:
    """T-SVC-473: a probe that cannot run costs the length, never the transcript."""
    ffmpeg.fail_probe = subprocess.TimeoutExpired(["ffmpeg"], 120)
    adapter, _ = _adapter(_json({"text": "tea"}))
    result = adapter.transcribe(b"x", mime="audio/flac")
    assert result.text == "tea" and result.duration_s is None


def test_an_unknown_model_books_no_cost(ffmpeg: FakeFfmpeg) -> None:
    """T-SVC-474: a model without a price has a length but no guessed cost."""
    adapter, _ = _adapter(_json({"text": "tea"}), model="custom-transcriber")
    result = adapter.transcribe(b"x", mime="audio/mp4")
    assert result.duration_s == 30.0 and result.cost_usd is None


def test_foreign_formats_are_converted_to_mp3_first(ffmpeg: FakeFfmpeg) -> None:
    """T-SVC-475: a Telegram voice note (.oga) is converted to MP3 and uploaded as such;
    a file without a usable name goes in as ``input.bin``."""
    adapter, seen = _adapter(_json({"text": "lentils"}))

    adapter.transcribe(b"OggS", mime="audio/ogg", filename="voice.oga")

    convert = ffmpeg.calls[0]
    assert convert[convert.index("-i") + 1].endswith("input.oga")
    body = seen[0].content.decode("utf-8", "replace")
    assert 'filename="audio.mp3"' in body and "audio/mpeg" in body
    assert "ID3mp3" in body  # the converted bytes, not the original

    ffmpeg.calls.clear()
    adapter.transcribe(b"OggS", mime="", filename=None)
    convert = ffmpeg.calls[0]
    assert convert[convert.index("-i") + 1].endswith("input.bin")


def test_audio_above_the_limit_is_refused_before_and_after_conversion(
    ffmpeg: FakeFfmpeg,
) -> None:
    """T-SVC-476: too large an upload is refused; so is a conversion that stays too large."""
    adapter, seen = _adapter(_json({"text": "x"}), max_file_mb=1)
    with pytest.raises(TranscriptionError, match="the limit is 1 MB"):
        adapter.transcribe(b"0" * (1024 * 1024 + 1), mime="audio/mpeg")
    ffmpeg.output = b"0" * (1024 * 1024 + 1)
    with pytest.raises(TranscriptionError, match="still exceeds"):
        adapter.transcribe(b"OggS", mime="audio/ogg", filename="voice.oga")
    assert seen == []  # nothing was uploaded


def test_conversion_needs_ffmpeg(no_ffmpeg: None) -> None:
    """T-SVC-477: a format that needs conversion without ffmpeg names the missing binary."""
    adapter, _ = _adapter(_json({"text": "x"}), ffmpeg_path="ffmpeg-custom")
    with pytest.raises(TranscriptionError, match=r"'ffmpeg-custom'.*not installed"):
        adapter.transcribe(b"OggS", mime="audio/ogg")


@pytest.mark.parametrize(
    ("failure", "fragment"),
    [
        (subprocess.CalledProcessError(1, ["ffmpeg"], stderr=b"Invalid data found\n"), "Invalid"),
        (subprocess.TimeoutExpired(["ffmpeg"], 300), "timed out"),
        (OSError("exec format error"), "exec format error"),
    ],
)
def test_a_failed_conversion_says_why(
    ffmpeg: FakeFfmpeg, failure: BaseException, fragment: str
) -> None:
    """T-SVC-478: ffmpeg's own error text (or the exception) ends up in the message."""
    ffmpeg.fail_convert = failure
    adapter, _ = _adapter(_json({"text": "x"}))
    with pytest.raises(TranscriptionError, match="ffmpeg conversion failed") as info:
        adapter.transcribe(b"OggS", mime="audio/ogg", filename="voice.oga")
    assert fragment in str(info.value)


def test_an_api_error_becomes_a_transcription_error(no_ffmpeg: None) -> None:
    """T-SVC-479: an error status from the provider is a transcription error."""
    payload = {"error": {"message": "Invalid file format.", "type": "invalid_request_error"}}
    adapter, _ = _adapter(lambda _r: httpx.Response(400, json=payload))
    with pytest.raises(TranscriptionError, match="Invalid file format"):
        adapter.transcribe(b"x", mime="audio/mpeg")
