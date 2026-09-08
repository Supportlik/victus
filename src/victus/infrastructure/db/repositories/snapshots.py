"""Report snapshots: frozen report results with their assessment."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from victus.infrastructure.db import orm
from victus.infrastructure.db.repositories._base import Repo


class SnapshotRepo(Repo):
    def add(self, snapshot: orm.ReportSnapshot) -> orm.ReportSnapshot:
        self.guard(snapshot)
        self.session.add(snapshot)
        self.session.flush()
        return snapshot

    def get(self, snapshot_id: str) -> orm.ReportSnapshot | None:
        return self.session.scalar(
            self.scoped(
                select(orm.ReportSnapshot).where(orm.ReportSnapshot.id == snapshot_id),
                orm.ReportSnapshot,
            )
        )

    def list(
        self,
        report_name: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> Sequence[orm.ReportSnapshot]:
        stmt = self.scoped(select(orm.ReportSnapshot), orm.ReportSnapshot)
        if report_name:
            stmt = stmt.where(orm.ReportSnapshot.report_name == report_name)
        if status:
            stmt = stmt.where(orm.ReportSnapshot.status == status)
        return self.session.scalars(
            stmt.order_by(orm.ReportSnapshot.created_at.desc()).limit(limit)
        ).all()

    def delete(self, snapshot: orm.ReportSnapshot) -> None:
        self.guard(snapshot)
        self.session.delete(snapshot)
        self.session.flush()
