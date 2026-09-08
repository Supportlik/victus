"""Request/response models for captures, attachments and agent runs (Stage 3)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from victus.api.schemas.common import Out

CaptureStatusLiteral = Literal["new", "in_progress", "assigned", "processed", "discarded", "failed"]
AgentModeLiteral = Literal["historical", "batch", "manual", "follow_up"]


class CaptureOut(Out):
    id: str
    kind: str
    captured_at: datetime
    target_date: date | None = None
    text: str | None = None
    status: str
    transcript: str | None = None
    attachment_id: str | None = None
    attachment_mime: str | None = None
    content_hash: str
    processed_at: datetime | None = None
    agent_run_id: str | None = None
    created: bool = True


class CapturePatch(BaseModel):
    status: CaptureStatusLiteral | None = None
    target_date: date | None = None
    # PATCH semantics: only keys present in the body are applied.
    model_config = {"extra": "forbid"}


class AgentSessionOut(Out):
    date: date
    model: str | None = None
    prompt_version: str | None = None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    outcome: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AgentRunOut(Out):
    id: str
    runner: str
    mode: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    captures: list[str] = Field(default_factory=list)
    days: list[date] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str | None = None
    prompt_version: str | None = None
    summary_md: str | None = None
    error: str | None = None
    sessions: list[AgentSessionOut] = Field(default_factory=list)


class AgentRunIn(BaseModel):
    mode: AgentModeLiteral = "historical"
    captures: list[str] | None = None
    from_: date | None = Field(default=None, alias="from")
    to: date | None = None
    model_config = {"populate_by_name": True}


class AgentLockOut(Out):
    date: date
    runner: str
    run_id: str
    locked_until: datetime


class UnlockOut(Out):
    date: date
    released: bool
