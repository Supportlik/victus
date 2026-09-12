"""Product change proposals (agent suggestions awaiting a person's decision)."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select

from victus.infrastructure.db import orm
from victus.infrastructure.db.repositories._base import Repo


class ProposalRepo(Repo):
    def add(self, proposal: orm.ProductProposal) -> orm.ProductProposal:
        self.guard(proposal)
        self.session.add(proposal)
        self.session.flush()
        return proposal

    def get(self, proposal_id: str) -> orm.ProductProposal | None:
        return self.session.scalar(
            self.scoped(
                select(orm.ProductProposal).where(orm.ProductProposal.id == proposal_id),
                orm.ProductProposal,
            )
        )

    def list(
        self,
        status: str | None = None,
        product_id: int | None = None,
        limit: int = 200,
    ) -> Sequence[orm.ProductProposal]:
        stmt = self.scoped(select(orm.ProductProposal), orm.ProductProposal)
        if status:
            stmt = stmt.where(orm.ProductProposal.status == status)
        if product_id is not None:
            stmt = stmt.where(orm.ProductProposal.product_id == product_id)
        return self.session.scalars(
            stmt.order_by(orm.ProductProposal.created_at.desc()).limit(limit)
        ).all()

    def count(self, status: str | None = None) -> int:
        stmt = self.scoped(
            select(func.count()).select_from(orm.ProductProposal), orm.ProductProposal
        )
        if status:
            stmt = stmt.where(orm.ProductProposal.status == status)
        return self.session.scalar(stmt) or 0
