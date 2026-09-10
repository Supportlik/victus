"""OpenAI transcription adapter (``gpt-4o-transcribe`` by default, SPEC R36).

Formats the API does not accept (Telegram ``.oga``/Opus, browser ``.webm``) are
converted to MP3 with ffmpeg when it is installed. The tenant's vocabulary
prompt is passed as ``prompt`` so product names and numbers come out right.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from victus.application.ports.transcription import TranscriptionError, TranscriptionResult

# USD per audio minute; unknown models book no cost rather than a guess.
PRICE_PER_MINUTE_USD: dict[str, float] = {
    "gpt-4o-transcribe": 0.006,
    "gpt-4o-mini-transcribe": 0.003,
    "whisper-1": 0.006,
}

# Containers OpenAI accepts as-is; everything else goes through ffmpeg.
#: ffmpeg reports progress as ``time=HH:MM:SS.ss``; the last one is the length it read.
_FFMPEG_TIME = re.compile(r"time=(\d+):(\d\d):(\d\d(?:\.\d+)?)")


def duration_from_ffmpeg(output: str) -> float | None:
    """The length ffmpeg last reported, in seconds.

    Read from the progress lines rather than from ``Duration:``, because a recording the
    browser produced has no duration in its header — that header is exactly why the player
    shows 0:00 — and only decoding it to the end finds out.
    """
    matches = _FFMPEG_TIME.findall(output)
    if not matches:
        return None
    hours, minutes, seconds = matches[-1]
    total = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return round(total, 2) if total > 0 else None


_NATIVE = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
    "audio/webm": "webm",
    "video/webm": "webm",
}


class OpenAITranscription:
    provider = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-transcribe",
        *,
        max_file_mb: int = 25,
        ffmpeg_path: str = "ffmpeg",
        timeout_s: float = 120.0,
    ) -> None:
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, timeout=timeout_s)
        self.model = model
        self.max_file_mb = max_file_mb
        self.ffmpeg_path = ffmpeg_path

    # ── conversion ──
    def _probe_duration(self, audio: bytes, suffix: str) -> float | None:
        """How long the recording is, by decoding it and discarding the output.

        Silent about its own failure on purpose: a missing length costs a label on a card,
        and refusing a transcript over it would cost the transcript.
        """
        ffmpeg = shutil.which(self.ffmpeg_path)
        if ffmpeg is None:
            return None
        with tempfile.TemporaryDirectory(prefix="victus-probe-") as tmp:
            src = Path(tmp) / f"input{suffix or '.bin'}"
            src.write_bytes(audio)
            cmd = [ffmpeg, "-i", str(src), "-vn", "-f", "null", "-"]
            try:
                done = subprocess.run(cmd, capture_output=True, timeout=120, check=False)
            except (subprocess.TimeoutExpired, OSError):
                return None
            return duration_from_ffmpeg(done.stderr.decode("utf-8", "replace"))

    def _to_mp3(self, audio: bytes, suffix: str) -> bytes:
        ffmpeg = shutil.which(self.ffmpeg_path)
        if ffmpeg is None:
            raise TranscriptionError(
                f"audio format needs conversion but ffmpeg ('{self.ffmpeg_path}') is not installed"
            )
        with tempfile.TemporaryDirectory(prefix="victus-transcribe-") as tmp:
            src = Path(tmp) / f"input{suffix}"
            dst = Path(tmp) / "output.mp3"
            src.write_bytes(audio)
            cmd = [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(src),
                "-vn",
                "-b:a",
                "64k",
                str(dst),
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=300)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
                detail = getattr(exc, "stderr", b"") or b""
                text = (
                    detail.decode("utf-8", "replace").strip() if isinstance(detail, bytes) else ""
                )
                raise TranscriptionError(f"ffmpeg conversion failed: {text or exc}") from exc
            return dst.read_bytes()

    def _prepare(self, audio: bytes, mime: str, filename: str | None) -> tuple[str, bytes, str]:
        mime = (mime or "").lower()
        ext = _NATIVE.get(mime)
        if ext is None:
            suffix = Path(filename).suffix if filename and Path(filename).suffix else ".bin"
            return "audio.mp3", self._to_mp3(audio, suffix), "audio/mpeg"
        name = filename if filename and filename.lower().endswith(f".{ext}") else f"audio.{ext}"
        return name, audio, mime

    # ── port ──
    def transcribe(
        self,
        audio: bytes,
        *,
        mime: str,
        filename: str | None = None,
        language: str | None = None,
        vocabulary_prompt: str | None = None,
    ) -> TranscriptionResult:
        import openai

        limit = self.max_file_mb * 1024 * 1024
        if len(audio) > limit:
            raise TranscriptionError(
                f"audio is {len(audio) / 1024 / 1024:.1f} MB; the limit is {self.max_file_mb} MB"
            )
        name, data, upload_mime = self._prepare(audio, mime, filename)
        if len(data) > limit:
            raise TranscriptionError("converted audio still exceeds the size limit")
        kwargs: dict[str, Any] = {"model": self.model, "file": (name, data, upload_mime)}
        if language:
            kwargs["language"] = language
        if vocabulary_prompt:
            kwargs["prompt"] = vocabulary_prompt
        # gpt-4o-* models only return json/text; whisper-1 can give timings.
        kwargs["response_format"] = "verbose_json" if self.model.startswith("whisper") else "json"
        try:
            response = self.client.audio.transcriptions.create(**kwargs)
        except openai.APIError as exc:
            raise TranscriptionError(str(exc)) from exc
        text = response if isinstance(response, str) else getattr(response, "text", "")
        duration = getattr(response, "duration", None)
        if duration is None:
            # Only whisper-* answers in verbose_json; the gpt-4o transcribers return the
            # text alone, so the length has to be measured here or it is lost for good.
            suffix = Path(name).suffix or (Path(filename).suffix if filename else ".bin")
            duration = self._probe_duration(data, suffix)
        segments_raw = getattr(response, "segments", None)
        segments: list[dict[str, Any]] | None = None
        if segments_raw:
            segments = [
                {
                    "start": getattr(s, "start", None),
                    "end": getattr(s, "end", None),
                    "text": getattr(s, "text", ""),
                }
                for s in segments_raw
            ]
        price = PRICE_PER_MINUTE_USD.get(self.model)
        cost = round(float(duration) / 60.0 * price, 6) if duration is not None and price else None
        return TranscriptionResult(
            text=str(text).strip(),
            provider=self.provider,
            model=self.model,
            language=getattr(response, "language", None) or language,
            duration_s=float(duration) if duration is not None else None,
            segments=segments,
            cost_usd=cost,
        )
