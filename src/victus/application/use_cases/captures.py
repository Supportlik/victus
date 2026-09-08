"""Captures: upload, list, inspect, re-target, transcribe (SPEC R35, R36, R51).

A capture is the user side of a day's thread (ADR 0010). Text typed on the day
view, a voice note or a photo all end up here; the agent reads them through
``GetDayContext`` and turns them into drafts.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from victus.application import dto
from victus.application.errors import (
    ExternalServiceError,
    NotFound,
    ValidationFailed,
)
from victus.application.ports.blob_storage import BlobNotFoundError, BlobStorage
from victus.application.ports.transcription import TranscriptionError, TranscriptionPort
from victus.application.ports.unit_of_work import UnitOfWork
from victus.application.tenant_context import (
    SCOPE_CAPTURE_READ,
    SCOPE_CAPTURE_WRITE,
    TenantContext,
)
from victus.application.use_cases._base import UowFactory, UseCase, now
from victus.domain.values import AgentMode, CaptureKind, CaptureStatus, DayStatus, RunStatus
from victus.infrastructure.db import orm

AUDIO_MIMES = frozenset(
    {
        "audio/mpeg",
        "audio/mp3",
        "audio/mp4",
        "audio/m4a",
        "audio/x-m4a",
        "audio/aac",
        "audio/wav",
        "audio/x-wav",
        "audio/webm",
        "audio/ogg",
        "audio/oga",
        "audio/opus",
        "audio/flac",
        "video/webm",  # browser MediaRecorder default container
        "video/ogg",
    }
)
IMAGE_MIMES = frozenset({"image/jpeg", "image/png", "image/webp", "image/heic", "image/gif"})

_EXT_MIME = {
    ".oga": "audio/ogg",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
}


def sniff_mime(mime: str | None, filename: str | None) -> str:
    """Trust a concrete MIME type; fall back to the file extension."""
    m = (mime or "").split(";")[0].strip().lower()
    if m and m != "application/octet-stream":
        return m
    if filename and "." in filename:
        ext = "." + filename.rsplit(".", 1)[1].lower()
        if ext in _EXT_MIME:
            return _EXT_MIME[ext]
    return m or "application/octet-stream"


def kind_for_mime(mime: str) -> CaptureKind:
    if mime in AUDIO_MIMES or mime.startswith("audio/"):
        return CaptureKind.AUDIO
    if mime in IMAGE_MIMES or mime.startswith("image/"):
        return CaptureKind.IMAGE
    raise ValidationFailed(f"unsupported attachment type '{mime}' (audio or image expected)")


def capture_view(
    cap: orm.Capture, transcript: orm.Transcript | None, *, created: bool = True
) -> dto.CaptureView:
    return dto.CaptureView(
        id=cap.id,
        kind=cap.kind,
        captured_at=cap.captured_at,
        target_date=cap.target_date,
        text=cap.text,
        status=cap.status,
        transcript=transcript.text if transcript else None,
        attachment_id=cap.attachment_id,
        attachment_mime=cap.attachment.mime if cap.attachment is not None else None,
        content_hash=cap.content_hash,
        processed_at=cap.processed_at,
        agent_run_id=cap.agent_run_id,
        created=created,
    )


def queue_follow_up_if_needed(
    uow: UnitOfWork, ctx: TenantContext, day: date, capture_ids: list[str], at: datetime
) -> orm.AgentRun | None:
    """New information on a drafted or locked day queues a ``follow_up`` run (ADR 0010).

    Only one queued follow-up per day is kept: a second message merges into it.
    """
    d = uow.day_logs.get_by_date(day)
    has_draft = d is not None and (
        d.status == DayStatus.DRAFT.value
        or any(li.is_draft for m in d.meals for li in m.line_items)
    )
    locked = uow.agent.lock_holder(day, at) is not None
    if not (has_draft or locked):
        return None
    key = day.isoformat()
    for run in uow.agent.queued_runs():
        if run.mode == AgentMode.FOLLOW_UP.value and run.days and key in run.days:
            run.captures = sorted(set(run.captures or []) | set(capture_ids))
            uow.flush()
            return run
    return uow.agent.add_run(
        orm.AgentRun(
            tenant_id=ctx.tenant_id,
            runner="worker",
            mode=AgentMode.FOLLOW_UP.value,
            status=RunStatus.QUEUED.value,
            captures=list(capture_ids),
            days=[key],
        )
    )


@dataclass(frozen=True, slots=True)
class UploadInput:
    text: str | None = None
    data: bytes | None = None
    filename: str | None = None
    mime: str | None = None
    target_date: date | None = None
    captured_at: datetime | None = None


class UploadCapture(UseCase):
    """Store a capture; identical content (per tenant) is a no-op (R35)."""

    def __init__(self, uow_factory: UowFactory, ctx: TenantContext, blobs: BlobStorage) -> None:
        super().__init__(uow_factory, ctx)
        self.blobs = blobs

    def execute(self, inp: UploadInput) -> dto.CaptureView:
        self.ctx.require(SCOPE_CAPTURE_WRITE)
        text = (inp.text or "").strip() or None
        if not text and not inp.data:
            raise ValidationFailed("a capture needs text or a file")
        ts = inp.captured_at or now()
        with self._uow() as uow:
            attachment: orm.Attachment | None = None
            if inp.data:
                mime = sniff_mime(inp.mime, inp.filename)
                kind = kind_for_mime(mime)
                digest = hashlib.sha256(inp.data).hexdigest()
                attachment = uow.captures.attachment_by_hash(digest)
                if attachment is None:
                    key = self.blobs.put(self.ctx.tenant_id, digest, inp.data)
                    attachment = uow.captures.add_attachment(
                        orm.Attachment(
                            tenant_id=self.ctx.tenant_id,
                            sha256=digest,
                            mime=mime,
                            size=len(inp.data),
                            storage_key=key,
                            original_name=inp.filename,
                        )
                    )
                content_hash = digest
            else:
                kind = CaptureKind.TEXT
                assert text is not None
                content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            existing = uow.captures.by_hash(content_hash)
            if existing is not None:
                return capture_view(
                    existing, uow.captures.transcript_for(existing.id), created=False
                )
            cap = uow.captures.add(
                orm.Capture(
                    tenant_id=self.ctx.tenant_id,
                    user_id=self.ctx.user_id,
                    kind=kind.value,
                    captured_at=ts,
                    target_date=inp.target_date,
                    text=text,
                    status=CaptureStatus.NEW.value,
                    attachment_id=attachment.id if attachment else None,
                    content_hash=content_hash,
                )
            )
            if attachment is not None:
                cap.attachment = attachment
            if inp.target_date is not None:
                queue_follow_up_if_needed(uow, self.ctx, inp.target_date, [cap.id], ts)
            uow.audit.record(
                "capture.create",
                "capture",
                cap.id,
                {
                    "kind": kind.value,
                    "target_date": inp.target_date.isoformat() if inp.target_date else None,
                },
            )
            view = capture_view(cap, None)
            uow.commit()
            return view


class ListCaptures(UseCase):
    def execute(
        self, *, status: str | None = None, target_date: date | None = None, limit: int = 200
    ) -> list[dto.CaptureView]:
        self.ctx.require(SCOPE_CAPTURE_READ)
        if status is not None and status not in {s.value for s in CaptureStatus}:
            raise ValidationFailed(f"unknown capture status '{status}'")
        with self._uow() as uow:
            rows = uow.captures.list(status=status, target_date=target_date, limit=limit)
            return [capture_view(c, uow.captures.transcript_for(c.id)) for c in rows]


class GetCapture(UseCase):
    def execute(self, capture_id: str) -> dto.CaptureView:
        self.ctx.require(SCOPE_CAPTURE_READ)
        with self._uow() as uow:
            cap = uow.captures.get(capture_id)
            if cap is None:
                raise NotFound(f"capture {capture_id} not found")
            return capture_view(cap, uow.captures.transcript_for(cap.id))


class UpdateCapture(UseCase):
    """Change status (e.g. discard) or the target day; both are user decisions."""

    def execute(self, capture_id: str, changes: dict[str, Any]) -> dto.CaptureView:
        self.ctx.require(SCOPE_CAPTURE_WRITE)
        with self._uow() as uow:
            cap = uow.captures.get(capture_id)
            if cap is None:
                raise NotFound(f"capture {capture_id} not found")
            diff: dict[str, Any] = {}
            if "status" in changes and changes["status"] is not None:
                status = str(changes["status"])
                if status not in {s.value for s in CaptureStatus}:
                    raise ValidationFailed(f"unknown capture status '{status}'")
                cap.status = status
                if status in (CaptureStatus.PROCESSED.value, CaptureStatus.DISCARDED.value):
                    cap.processed_at = now()
                diff["status"] = status
            if "target_date" in changes:
                new_day = changes["target_date"]
                cap.target_date = new_day
                diff["target_date"] = new_day.isoformat() if new_day else None
                if new_day is not None and cap.status == CaptureStatus.NEW.value:
                    queue_follow_up_if_needed(uow, self.ctx, new_day, [cap.id], now())
            uow.audit.record("capture.update", "capture", cap.id, diff)
            uow.flush()
            view = capture_view(cap, uow.captures.transcript_for(cap.id))
            uow.commit()
            return view


class GetAttachment(UseCase):
    def __init__(self, uow_factory: UowFactory, ctx: TenantContext, blobs: BlobStorage) -> None:
        super().__init__(uow_factory, ctx)
        self.blobs = blobs

    def execute(self, attachment_id: str) -> dto.AttachmentContent:
        self.ctx.require(SCOPE_CAPTURE_READ)
        with self._uow() as uow:
            att = uow.captures.get_attachment(attachment_id)
            if att is None:
                raise NotFound(f"attachment {attachment_id} not found")
            try:
                data = self.blobs.get(att.storage_key)
            except BlobNotFoundError as exc:
                raise NotFound(f"blob for attachment {attachment_id} is missing") from exc
            return dto.AttachmentContent(
                id=att.id,
                mime=att.mime,
                size=att.size,
                original_name=att.original_name,
                sha256=att.sha256,
                data=data,
            )


def transcription_settings(uow: UnitOfWork) -> tuple[str | None, str | None]:
    """(language, vocabulary_prompt) from the tenant's current settings version."""
    current = uow.settings.current()
    data: dict[str, Any] = dict(current.data) if current is not None else {}
    section = data.get("transcription") or {}
    if not isinstance(section, dict):
        return None, None
    lang = section.get("language")
    vocab = section.get("vocabulary_prompt")
    return (str(lang) if lang else None, str(vocab) if vocab else None)


class TranscribeCapture(UseCase):
    """Transcribe an audio capture through the port and store the transcript (R36)."""

    def __init__(
        self,
        uow_factory: UowFactory,
        ctx: TenantContext,
        blobs: BlobStorage,
        transcription: TranscriptionPort | None,
    ) -> None:
        super().__init__(uow_factory, ctx)
        self.blobs = blobs
        self.transcription = transcription

    def execute(self, capture_id: str, *, force: bool = False) -> dto.CaptureView:
        self.ctx.require(SCOPE_CAPTURE_WRITE)
        with self._uow() as uow:
            cap = uow.captures.get(capture_id)
            if cap is None:
                raise NotFound(f"capture {capture_id} not found")
            if cap.kind != CaptureKind.AUDIO.value:
                raise ValidationFailed("only audio captures can be transcribed")
            existing = uow.captures.transcript_for(cap.id)
            if existing is not None and not force:
                return capture_view(cap, existing)
            if self.transcription is None:
                raise ExternalServiceError(
                    "transcription is not configured (providers.openai_api_key missing)"
                )
            att = uow.captures.get_attachment(cap.attachment_id or "")
            if att is None:
                raise NotFound(f"capture {capture_id} has no attachment")
            try:
                audio = self.blobs.get(att.storage_key)
            except BlobNotFoundError as exc:
                raise NotFound(f"blob for capture {capture_id} is missing") from exc
            language, vocab = transcription_settings(uow)
            try:
                result = self.transcription.transcribe(
                    audio,
                    mime=att.mime,
                    filename=att.original_name,
                    language=language,
                    vocabulary_prompt=vocab,
                )
            except TranscriptionError as exc:
                cap.status = CaptureStatus.FAILED.value
                uow.audit.record(
                    "capture.transcribe_failed", "capture", cap.id, {"error": str(exc)}
                )
                uow.commit()
                raise ExternalServiceError(f"transcription failed: {exc}") from exc
            transcript = uow.captures.add_transcript(
                orm.Transcript(
                    capture_id=cap.id,
                    provider=result.provider,
                    model=result.model,
                    language=result.language,
                    text=result.text,
                    segments=result.segments,
                    duration_s=result.duration_s,
                    cost_usd=result.cost_usd,
                )
            )
            if cap.status == CaptureStatus.FAILED.value:
                cap.status = CaptureStatus.NEW.value
            uow.audit.record(
                "capture.transcribe",
                "capture",
                cap.id,
                {
                    "model": result.model,
                    "duration_s": result.duration_s,
                    "cost_usd": result.cost_usd,
                },
            )
            view = capture_view(cap, transcript)
            uow.commit()
            return view
