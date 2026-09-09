"""Captures: upload, list, inspect, re-target, transcribe (SPEC R35, R36, R51).

A capture is the user side of a day's thread (ADR 0010). Text typed on the day
view, a voice note or a photo all end up here; the agent reads them through
``GetDayContext`` and turns them into drafts.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from victus.application import dto
from victus.application.errors import (
    Conflict,
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
    cap: orm.Capture,
    transcript: orm.Transcript | None,
    *,
    created: bool = True,
    attachments: list[orm.Attachment] | None = None,
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
        product_id=cap.product_id,
        attachments=[
            dto.AttachmentRef(id=a.id, mime=a.mime, size=a.size, original_name=a.original_name)
            for a in (attachments if attachments is not None else _fallback_attachments(cap))
        ],
        created=created,
    )


def _fallback_attachments(cap: orm.Capture) -> list[orm.Attachment]:
    return [cap.attachment] if cap.attachment is not None else []


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
class UploadFile:
    """One file of an upload."""

    data: bytes
    filename: str | None = None
    mime: str | None = None


@dataclass(frozen=True, slots=True)
class UploadInput:
    text: str | None = None
    data: bytes | None = None
    filename: str | None = None
    mime: str | None = None
    target_date: date | None = None
    captured_at: datetime | None = None
    product_id: int | None = None  # a capture about one product has no target day
    #: several files taken together stay one capture (photos, or a photo plus a voice note)
    files: tuple[UploadFile, ...] = ()

    def all_files(self) -> list[UploadFile]:
        first = [UploadFile(self.data, self.filename, self.mime)] if self.data else []
        return first + list(self.files)


def content_hash_of(text: str | None, digests: list[str]) -> str:
    """One file keeps its own digest, so re-uploading it is still a no-op (R35)."""
    if len(digests) == 1 and not text:
        return digests[0]
    joined = "|".join([text or "", *digests])
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


class UploadCapture(UseCase):
    """Store a capture; identical content (per tenant) is a no-op (R35)."""

    def __init__(self, uow_factory: UowFactory, ctx: TenantContext, blobs: BlobStorage) -> None:
        super().__init__(uow_factory, ctx)
        self.blobs = blobs

    def execute(self, inp: UploadInput) -> dto.CaptureView:
        self.ctx.require(SCOPE_CAPTURE_WRITE)
        text = (inp.text or "").strip() or None
        if not text and not inp.all_files():
            raise ValidationFailed("a capture needs text or at least one file")
        ts = inp.captured_at or now()
        with self._uow() as uow:
            if inp.product_id is not None and uow.products.get(inp.product_id) is None:
                raise NotFound(f"product {inp.product_id} not found")
            files = inp.all_files()
            attachments: list[orm.Attachment] = []
            digests: list[str] = []
            kind = CaptureKind.TEXT
            for f in files:
                mime = sniff_mime(f.mime, f.filename)
                file_kind = kind_for_mime(mime)
                # audio decides the kind: it is the one that gets transcribed
                if file_kind == CaptureKind.AUDIO or kind == CaptureKind.TEXT:
                    kind = file_kind
                digest = hashlib.sha256(f.data).hexdigest()
                digests.append(digest)
                attachment = uow.captures.attachment_by_hash(digest)
                if attachment is None:
                    key = self.blobs.put(self.ctx.tenant_id, digest, f.data)
                    attachment = uow.captures.add_attachment(
                        orm.Attachment(
                            tenant_id=self.ctx.tenant_id,
                            sha256=digest,
                            mime=mime,
                            size=len(f.data),
                            storage_key=key,
                            original_name=f.filename,
                        )
                    )
                attachments.append(attachment)
            content_hash = content_hash_of(text, digests)
            existing = uow.captures.by_hash(content_hash)
            if existing is not None:
                return capture_view(
                    existing,
                    uow.captures.transcript_for(existing.id),
                    created=False,
                    attachments=list(uow.captures.attachments_of(existing.id)),
                )
            cap = uow.captures.add(
                orm.Capture(
                    tenant_id=self.ctx.tenant_id,
                    user_id=self.ctx.user_id,
                    kind=kind.value,
                    captured_at=ts,
                    target_date=None if inp.product_id is not None else inp.target_date,
                    text=text,
                    status=CaptureStatus.NEW.value,
                    attachment_id=attachments[0].id if attachments else None,
                    content_hash=content_hash,
                    product_id=inp.product_id,
                )
            )
            if attachments:
                cap.attachment = attachments[0]
                for i, att in enumerate(attachments, start=1):
                    uow.captures.link_attachment(cap.id, att.id, i)
            if inp.target_date is not None and inp.product_id is None:
                queue_follow_up_if_needed(uow, self.ctx, inp.target_date, [cap.id], ts)
            uow.audit.record(
                "capture.create",
                "capture",
                cap.id,
                {
                    "kind": kind.value,
                    "target_date": inp.target_date.isoformat() if inp.target_date else None,
                    "product_id": inp.product_id,
                    "files": len(attachments),
                },
            )
            view = capture_view(cap, None, attachments=attachments)
            uow.commit()
            return view


DISCARD_RETENTION = timedelta(days=1)
#: A processed capture has already become line items; the files are only worth keeping
#: for a while so the photo or recording can still be looked at (R66).
PROCESSED_RETENTION_DEFAULT_DAYS = 10
DELETABLE_STATUSES = frozenset(
    {CaptureStatus.NEW.value, CaptureStatus.FAILED.value, CaptureStatus.DISCARDED.value}
)


def _remove_capture(uow: UnitOfWork, blobs: BlobStorage | None, cap: orm.Capture) -> None:
    """Delete a capture and every blob of it that nothing else references."""
    files = list(uow.captures.attachments_of(cap.id))
    uow.captures.delete(cap)
    for att in files:
        if uow.captures.attachment_refs(att.id) > 0:
            continue
        key = att.storage_key
        uow.captures.delete_attachment(att)
        if blobs is not None:
            # the row is gone; a stray file is harmless and reported by verify
            with contextlib.suppress(OSError):
                blobs.delete(key)


def processed_retention(uow: UnitOfWork) -> timedelta | None:
    """How long processed captures are kept; ``None`` when they are kept for ever."""
    current = uow.settings.current()
    data: dict[str, Any] = dict(current.data) if current is not None else {}
    section = data.get("captures")
    days = PROCESSED_RETENTION_DEFAULT_DAYS
    if isinstance(section, dict):
        raw = section.get("processed_retention_days", days)
        if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
            days = raw
    return timedelta(days=days) if days > 0 else None


def purge_settled(uow: UnitOfWork, blobs: BlobStorage | None, at: datetime) -> int:
    """Delete captures nobody needs any more, with their files.

    Discarded ones go after ``DISCARD_RETENTION``; processed ones after the tenant's
    retention, which can be turned off. Both free the blobs they alone referenced.
    """
    removed = 0
    stale: list[orm.Capture] = list(
        uow.captures.settled_before(CaptureStatus.DISCARDED.value, at - DISCARD_RETENTION)
    )
    keep = processed_retention(uow)
    if keep is not None:
        stale += list(uow.captures.settled_before(CaptureStatus.PROCESSED.value, at - keep))
    for cap in stale:
        _remove_capture(uow, blobs, cap)
        removed += 1
    return removed


class DeleteCapture(UseCase):
    """Remove a capture that the agent has not used (new, failed or discarded)."""

    def __init__(
        self, uow_factory: UowFactory, ctx: TenantContext, blobs: BlobStorage | None = None
    ) -> None:
        super().__init__(uow_factory, ctx)
        self.blobs = blobs

    def execute(self, capture_id: str) -> None:
        self.ctx.require(SCOPE_CAPTURE_WRITE)
        with self._uow() as uow:
            cap = uow.captures.get(capture_id)
            if cap is None:
                raise NotFound(f"capture {capture_id} not found")
            if cap.status not in DELETABLE_STATUSES:
                raise Conflict(
                    f"capture {capture_id} is {cap.status}; only new, failed or discarded "
                    "captures can be deleted"
                )
            uow.audit.record("capture.delete", "capture", cap.id, {"kind": cap.kind})
            _remove_capture(uow, self.blobs, cap)
            uow.commit()


class ListCaptures(UseCase):
    def __init__(
        self, uow_factory: UowFactory, ctx: TenantContext, blobs: BlobStorage | None = None
    ) -> None:
        super().__init__(uow_factory, ctx)
        self.blobs = blobs

    def execute(
        self,
        *,
        status: str | None = None,
        target_date: date | None = None,
        limit: int = 200,
        product_id: int | None = None,
    ) -> list[dto.CaptureView]:
        self.ctx.require(SCOPE_CAPTURE_READ)
        if status is not None and status not in {s.value for s in CaptureStatus}:
            raise ValidationFailed(f"unknown capture status '{status}'")
        with self._uow() as uow:
            # housekeeping on read: no worker is needed for the one-day retention
            if self.ctx.has_scope(SCOPE_CAPTURE_WRITE) and purge_settled(uow, self.blobs, now()):
                uow.commit()
            rows = uow.captures.list(
                status=status, target_date=target_date, limit=limit, product_id=product_id
            )
            return [
                capture_view(
                    c,
                    uow.captures.transcript_for(c.id),
                    attachments=list(uow.captures.attachments_of(c.id)),
                )
                for c in rows
            ]


class GetCapture(UseCase):
    def execute(self, capture_id: str) -> dto.CaptureView:
        self.ctx.require(SCOPE_CAPTURE_READ)
        with self._uow() as uow:
            cap = uow.captures.get(capture_id)
            if cap is None:
                raise NotFound(f"capture {capture_id} not found")
            return capture_view(
                cap,
                uow.captures.transcript_for(cap.id),
                attachments=list(uow.captures.attachments_of(cap.id)),
            )


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
            if "product_id" in changes:
                pid = changes["product_id"]
                if pid is not None and uow.products.get(int(pid)) is None:
                    raise NotFound(f"product {pid} not found")
                cap.product_id = int(pid) if pid is not None else None
                diff["product_id"] = cap.product_id
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


_WORD = re.compile(r"[\w'-]+", re.UNICODE)


def looks_like_prompt_echo(text: str, vocabulary_prompt: str | None) -> bool:
    """Speech models return the vocabulary prompt (or nothing) for silent audio.

    True when the transcript is empty, or short and made almost entirely of words
    that occur in the vocabulary prompt.
    """
    words = [w.lower() for w in _WORD.findall(text or "")]
    if not words:
        return True
    if not vocabulary_prompt:
        return False
    vocab = {w.lower() for w in _WORD.findall(vocabulary_prompt)}
    if len(words) > 40:
        return False
    hits = sum(1 for w in words if w in vocab)
    return hits / len(words) >= 0.8


def _audio_of(uow: UnitOfWork, cap: orm.Capture) -> orm.Attachment | None:
    """The capture's audio file, whichever position it holds.

    A capture is one thing made of several parts — two photos and a spoken note is an
    ordinary capture (R65) — and ``attachment_id`` names the part that arrived first.
    Transcribing that one handed ffmpeg a photo, which turned it into an mp3 with no
    stream in it and reported the failure as a conversion error.
    """
    files = list(uow.captures.attachments_of(cap.id))
    if not files and cap.attachment_id:
        single = uow.captures.get_attachment(cap.attachment_id)
        files = [single] if single is not None else []
    audio = [f for f in files if (f.mime or "").lower().startswith(("audio/", "video/"))]
    return audio[0] if audio else None


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
            att = _audio_of(uow, cap)
            if att is None:
                raise ValidationFailed(f"capture {capture_id} has no audio to transcribe")
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
            echo = looks_like_prompt_echo(result.text, vocab)
            transcript = uow.captures.add_transcript(
                orm.Transcript(
                    capture_id=cap.id,
                    provider=result.provider,
                    model=result.model,
                    language=result.language,
                    text="" if echo else result.text,
                    segments=None if echo else result.segments,
                    duration_s=result.duration_s,
                    cost_usd=result.cost_usd,
                )
            )
            if echo:
                # nothing intelligible: keep the audio, flag it, never feed the prompt to the agent
                cap.status = CaptureStatus.FAILED.value
                uow.audit.record(
                    "capture.transcribe_empty", "capture", cap.id, {"model": result.model}
                )
            elif cap.status == CaptureStatus.FAILED.value:
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
