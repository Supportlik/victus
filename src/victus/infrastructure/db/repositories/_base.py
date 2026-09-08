"""Shared plumbing for the repositories."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from sqlalchemy import Select
from sqlalchemy.orm import Session

from victus.application.tenant_context import TenantContext


class TenantMismatchError(PermissionError):
    """An entity from another tenant was passed to a scoped repository."""


class Repo:
    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx

    @property
    def tenant_id(self) -> str:
        return self.ctx.tenant_id

    def scoped(self, stmt: Select[Any], model: Any) -> Select[Any]:
        """Add ``model.tenant_id == ctx.tenant_id`` to a select."""
        return stmt.where(model.tenant_id == self.tenant_id)

    def guard(self, entity: Any) -> None:
        """Refuse entities that belong to another tenant (defence in depth)."""
        tenant_id = getattr(entity, "tenant_id", None)
        if tenant_id is None:
            entity.tenant_id = self.tenant_id
        elif tenant_id != self.tenant_id:
            raise TenantMismatchError(f"{type(entity).__name__} belongs to another tenant")


_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s%]", re.UNICODE)


def normalize(text: str) -> str:
    """Lower-case, strip accents and punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFKD", text)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("ß", "ss").lower()
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()
