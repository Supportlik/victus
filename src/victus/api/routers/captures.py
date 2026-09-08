"""Captures (text, voice notes, photos), their attachments and transcription."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status
from fastapi.responses import JSONResponse

from victus.api.deps import Blobs, Ctx, Transcription, Uow
from victus.api.schemas.inbox import CaptureOut, CapturePatch
from victus.application.errors import ExternalServiceError
from victus.application.use_cases import captures as uc
from victus.domain.values import CaptureKind

router = APIRouter(tags=["captures"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


@router.post(
    "/captures",
    response_model=CaptureOut,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": CaptureOut, "description": "Duplicate content; existing capture"}},
)
async def upload_capture(
    ctx: Ctx,
    uow: Uow,
    blobs: Blobs,
    transcription: Transcription,
    text: Annotated[str | None, Form()] = None,
    target_date: Annotated[date | None, Form()] = None,
    product_id: Annotated[int | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
) -> Response:
    data: bytes | None = None
    filename: str | None = None
    mime: str | None = None
    if file is not None:
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            return JSONResponse(
                {"title": "Payload too large", "detail": "file exceeds 50 MB", "status": 413},
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                media_type="application/problem+json",
            )
        filename = file.filename
        mime = file.content_type
        if not data:
            data = None
    view = uc.UploadCapture(uow, ctx, blobs).execute(
        uc.UploadInput(
            text=text,
            data=data,
            filename=filename,
            mime=mime,
            target_date=target_date,
            product_id=product_id,
        )
    )
    if view.created and view.kind == CaptureKind.AUDIO.value and transcription is not None:
        try:
            view = uc.TranscribeCapture(uow, ctx, blobs, transcription).execute(view.id)
        except ExternalServiceError:
            # the capture stays (status failed); the user can retry via /transcribe
            view = uc.GetCapture(uow, ctx).execute(view.id)
    code = status.HTTP_201_CREATED if view.created else status.HTTP_200_OK
    return JSONResponse(CaptureOut.model_validate(view).model_dump(mode="json"), status_code=code)


@router.get("/captures", response_model=list[CaptureOut])
def list_captures(
    ctx: Ctx,
    uow: Uow,
    status_: Annotated[str | None, Query(alias="status")] = None,
    day: Annotated[date | None, Query(alias="date")] = None,
    product_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[CaptureOut]:
    rows = uc.ListCaptures(uow, ctx).execute(
        status=status_, target_date=day, limit=limit, product_id=product_id
    )
    return [CaptureOut.model_validate(c) for c in rows]


@router.get("/captures/{capture_id}", response_model=CaptureOut)
def get_capture(capture_id: str, ctx: Ctx, uow: Uow) -> CaptureOut:
    return CaptureOut.model_validate(uc.GetCapture(uow, ctx).execute(capture_id))


@router.patch("/captures/{capture_id}", response_model=CaptureOut)
def patch_capture(capture_id: str, body: CapturePatch, ctx: Ctx, uow: Uow) -> CaptureOut:
    changes = body.model_dump(exclude_unset=True)
    return CaptureOut.model_validate(uc.UpdateCapture(uow, ctx).execute(capture_id, changes))


@router.post("/captures/{capture_id}/transcribe", response_model=CaptureOut)
def transcribe_capture(
    capture_id: str,
    ctx: Ctx,
    uow: Uow,
    blobs: Blobs,
    transcription: Transcription,
    force: Annotated[bool, Query()] = False,
) -> CaptureOut:
    view = uc.TranscribeCapture(uow, ctx, blobs, transcription).execute(capture_id, force=force)
    return CaptureOut.model_validate(view)


@router.get("/attachments/{attachment_id}", response_class=Response)
def get_attachment(attachment_id: str, ctx: Ctx, uow: Uow, blobs: Blobs) -> Response:
    att = uc.GetAttachment(uow, ctx, blobs).execute(attachment_id)
    name = (att.original_name or att.id).replace('"', "")
    return Response(
        content=att.data,
        media_type=att.mime,
        headers={
            "Content-Disposition": f'inline; filename="{name}"',
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )
