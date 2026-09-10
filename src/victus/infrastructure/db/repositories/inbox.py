"""Captures, attachments, transcripts, agent runs/sessions/locks and day messages."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select

from victus.infrastructure.db import orm
from victus.infrastructure.db.repositories._base import Repo


class CaptureRepo(Repo):
    def get(self, capture_id: str) -> orm.Capture | None:
        return self.session.scalar(
            self.scoped(select(orm.Capture).where(orm.Capture.id == capture_id), orm.Capture)
        )

    def add(self, capture: orm.Capture) -> orm.Capture:
        self.guard(capture)
        self.session.add(capture)
        self.session.flush()
        return capture

    def by_hash(self, content_hash: str) -> orm.Capture | None:
        return self.session.scalar(
            self.scoped(
                select(orm.Capture).where(orm.Capture.content_hash == content_hash), orm.Capture
            )
        )

    def list(
        self,
        status: str | None = None,
        target_date: date | None = None,
        limit: int | None = None,
        product_id: int | None = None,
    ) -> Sequence[orm.Capture]:
        stmt = self.scoped(select(orm.Capture), orm.Capture)
        if status:
            stmt = stmt.where(orm.Capture.status == status)
        if target_date:
            stmt = stmt.where(orm.Capture.target_date == target_date)
        if product_id is not None:
            stmt = stmt.where(orm.Capture.product_id == product_id)
        stmt = stmt.order_by(orm.Capture.captured_at.desc() if limit else orm.Capture.captured_at)
        if limit:
            stmt = stmt.limit(limit)
        return self.session.scalars(stmt).all()

    def add_attachment(self, attachment: orm.Attachment) -> orm.Attachment:
        self.guard(attachment)
        self.session.add(attachment)
        self.session.flush()
        return attachment

    def get_attachment(self, attachment_id: str) -> orm.Attachment | None:
        return self.session.scalar(
            self.scoped(
                select(orm.Attachment).where(orm.Attachment.id == attachment_id), orm.Attachment
            )
        )

    def attachment_by_hash(self, sha256: str) -> orm.Attachment | None:
        return self.session.scalar(
            self.scoped(
                select(orm.Attachment).where(orm.Attachment.sha256 == sha256), orm.Attachment
            )
        )

    def link_attachment(self, capture_id: str, attachment_id: str, position: int) -> None:
        self.session.merge(
            orm.CaptureAttachment(
                capture_id=capture_id, attachment_id=attachment_id, position=position
            )
        )
        self.session.flush()

    def attachments_of(self, capture_id: str) -> Sequence[orm.Attachment]:
        """Every file of a capture, in order (falls back to the single link)."""
        rows = self.session.execute(
            select(orm.Attachment)
            .join(orm.CaptureAttachment, orm.CaptureAttachment.attachment_id == orm.Attachment.id)
            .where(
                orm.CaptureAttachment.capture_id == capture_id,
                orm.Attachment.tenant_id == self.tenant_id,
            )
            .order_by(orm.CaptureAttachment.position)
        ).scalars()
        found = list(rows)
        if found:
            return found
        cap = self.get(capture_id)
        return [cap.attachment] if cap is not None and cap.attachment is not None else []

    def attachment_refs(self, attachment_id: str) -> int:
        by_column = self.scoped(
            select(orm.Capture).where(orm.Capture.attachment_id == attachment_id), orm.Capture
        )
        links = select(orm.CaptureAttachment).where(
            orm.CaptureAttachment.attachment_id == attachment_id
        )
        return len(self.session.scalars(by_column).all()) + len(self.session.scalars(links).all())

    def add_transcript(self, transcript: orm.Transcript) -> orm.Transcript:
        if self.get(transcript.capture_id) is None:
            raise PermissionError("capture not in tenant")
        self.session.add(transcript)
        self.session.flush()
        return transcript

    def transcript_for(self, capture_id: str) -> orm.Transcript | None:
        if self.get(capture_id) is None:
            return None
        return self.session.scalar(
            select(orm.Transcript)
            .where(orm.Transcript.capture_id == capture_id)
            .order_by(orm.Transcript.created_at.desc())
            .limit(1)
        )

    def transcripts_for(self, capture_id: str) -> Sequence[orm.Transcript]:
        """Every transcript of a capture, oldest first.

        A capture with two spoken notes has two of them (R65), and re-transcribing adds
        a row rather than replacing one, so the caller picks the newest per recording.
        """
        if self.get(capture_id) is None:
            return []
        return self.session.scalars(
            select(orm.Transcript)
            .where(orm.Transcript.capture_id == capture_id)
            .order_by(orm.Transcript.created_at, orm.Transcript.id)
        ).all()

    def delete(self, capture: orm.Capture) -> None:
        self.guard(capture)
        self.session.delete(capture)
        self.session.flush()

    def delete_attachment(self, attachment: orm.Attachment) -> None:
        self.guard(attachment)
        self.session.delete(attachment)
        self.session.flush()

    def settled_before(self, status: str, cutoff: datetime) -> Sequence[orm.Capture]:
        """Captures that reached ``status`` before ``cutoff`` (discarded or processed)."""
        stmt = self.scoped(
            select(orm.Capture).where(
                orm.Capture.status == status,
                orm.Capture.processed_at.is_not(None),
                orm.Capture.processed_at < cutoff,
            ),
            orm.Capture,
        )
        return self.session.scalars(stmt).all()


class AgentRepo(Repo):
    def add_run(self, run: orm.AgentRun) -> orm.AgentRun:
        self.guard(run)
        self.session.add(run)
        self.session.flush()
        return run

    def get_run(self, run_id: str) -> orm.AgentRun | None:
        return self.session.scalar(
            self.scoped(select(orm.AgentRun).where(orm.AgentRun.id == run_id), orm.AgentRun)
        )

    def list_runs(self, limit: int = 50) -> Sequence[orm.AgentRun]:
        return self.session.scalars(
            self.scoped(select(orm.AgentRun), orm.AgentRun)
            .order_by(orm.AgentRun.created_at.desc())
            .limit(limit)
        ).all()

    def queued_runs(self) -> Sequence[orm.AgentRun]:
        return self.session.scalars(
            self.scoped(
                select(orm.AgentRun).where(orm.AgentRun.status == "queued"), orm.AgentRun
            ).order_by(orm.AgentRun.created_at)
        ).all()

    def add_session(self, session: orm.AgentSession) -> orm.AgentSession:
        if self.get_run(session.run_id) is None:
            raise PermissionError("run not in tenant")
        self.session.add(session)
        self.session.flush()
        return session

    def sessions_for(self, run_id: str) -> Sequence[orm.AgentSession]:
        if self.get_run(run_id) is None:
            return []
        return self.session.scalars(
            select(orm.AgentSession)
            .where(orm.AgentSession.run_id == run_id)
            .order_by(orm.AgentSession.date)
        ).all()

    # ── locks (ADR 0005) ──
    def try_acquire_lock(
        self, day: date, runner: str, run_id: str, ttl_minutes: int, now: datetime
    ) -> bool:
        """Acquire the per-day lock. Returns False if another live lock exists.

        Implemented as "delete expired, then INSERT … ON CONFLICT DO NOTHING" so the
        same statement works on SQLite and PostgreSQL and races resolve in the database.
        """
        self.session.execute(
            delete(orm.AgentLock).where(
                orm.AgentLock.tenant_id == self.tenant_id,
                orm.AgentLock.date == day,
                orm.AgentLock.locked_until <= now,
            )
        )
        values = {
            "tenant_id": self.tenant_id,
            "date": day,
            "runner": runner,
            "run_id": run_id,
            "locked_until": now + timedelta(minutes=ttl_minutes),
        }
        dialect = self.session.get_bind().dialect.name
        stmt: Any
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            stmt = pg_insert(orm.AgentLock).values(**values).on_conflict_do_nothing()
        else:
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            stmt = sqlite_insert(orm.AgentLock).values(**values).on_conflict_do_nothing()
        result = cast(CursorResult[Any], self.session.execute(stmt))
        self.session.flush()
        if result.rowcount == 1:
            return True
        holder = self.lock_holder(day, now)
        return holder is not None and holder.run_id == run_id

    def lock_holder(self, day: date, now: datetime) -> orm.AgentLock | None:
        lock = self.session.get(orm.AgentLock, (self.tenant_id, day))
        if lock is None:
            return None
        self.session.refresh(lock)
        if lock.locked_until <= now:
            return None
        return lock

    def extend_lock(self, day: date, run_id: str, ttl_minutes: int, now: datetime) -> bool:
        """Push ``locked_until`` forward for a lock this run still holds."""
        lock = self.lock_holder(day, now)
        if lock is None or lock.run_id != run_id:
            return False
        lock.locked_until = now + timedelta(minutes=ttl_minutes)
        self.session.flush()
        return True

    def list_runs_by_status(self, status: str) -> Sequence[orm.AgentRun]:
        return self.session.scalars(
            self.scoped(
                select(orm.AgentRun).where(orm.AgentRun.status == status), orm.AgentRun
            ).order_by(orm.AgentRun.created_at)
        ).all()

    def release_locks(self, run_id: str) -> int:
        result = cast(
            CursorResult[Any],
            self.session.execute(
                delete(orm.AgentLock).where(
                    orm.AgentLock.tenant_id == self.tenant_id, orm.AgentLock.run_id == run_id
                )
            ),
        )
        self.session.flush()
        return int(result.rowcount or 0)

    def release_lock(self, day: date) -> bool:
        result = cast(
            CursorResult[Any],
            self.session.execute(
                delete(orm.AgentLock).where(
                    orm.AgentLock.tenant_id == self.tenant_id, orm.AgentLock.date == day
                )
            ),
        )
        self.session.flush()
        return bool(result.rowcount)

    def locks(self) -> Sequence[orm.AgentLock]:
        return self.session.scalars(
            self.scoped(select(orm.AgentLock), orm.AgentLock).order_by(orm.AgentLock.date)
        ).all()


class DayMessageRepo(Repo):
    def add(self, message: orm.DayMessage) -> orm.DayMessage:
        self.guard(message)
        self.session.add(message)
        self.session.flush()
        return message

    def thread(self, day: date) -> Sequence[orm.DayMessage]:
        return self.session.scalars(
            self.scoped(
                select(orm.DayMessage).where(orm.DayMessage.date == day), orm.DayMessage
            ).order_by(orm.DayMessage.created_at, orm.DayMessage.id)
        ).all()

    def latest(self, day: date, kind: str) -> orm.DayMessage | None:
        return self.session.scalars(
            self.scoped(
                select(orm.DayMessage).where(
                    orm.DayMessage.date == day, orm.DayMessage.kind == kind
                ),
                orm.DayMessage,
            ).order_by(orm.DayMessage.created_at.desc(), orm.DayMessage.id.desc())
        ).first()

    def remove_kind(self, day: date, kind: str) -> int:
        result = cast(
            CursorResult[Any],
            self.session.execute(
                delete(orm.DayMessage).where(
                    orm.DayMessage.tenant_id == self.tenant_id,
                    orm.DayMessage.date == day,
                    orm.DayMessage.kind == kind,
                )
            ),
        )
        self.session.flush()
        return int(result.rowcount or 0)
