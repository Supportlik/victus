"""SQLAlchemy implementation of the unscoped :class:`AuthLookup` port."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from victus.infrastructure.db import orm


class SqlAuthLookup:
    def __init__(self, session: Session) -> None:
        self._session = session

    def passkey_by_credential_id(
        self, credential_id: bytes
    ) -> tuple[orm.PasskeyCredential, orm.User] | None:
        row = self._session.execute(
            select(orm.PasskeyCredential, orm.User)
            .join(orm.User, orm.User.id == orm.PasskeyCredential.user_id)
            .where(orm.PasskeyCredential.credential_id == credential_id)
        ).first()
        if row is None:
            return None
        return row[0], row[1]

    def users_by_email(self, email: str) -> list[orm.User]:
        return list(
            self._session.scalars(select(orm.User).where(orm.User.email == email.strip().lower()))
        )

    def session(self, session_id: str) -> orm.Session | None:
        return self._session.get(orm.Session, session_id)

    def credential_ids_for_user(self, user_id: str) -> list[bytes]:
        rows = self._session.scalars(
            select(orm.PasskeyCredential.credential_id).where(
                orm.PasskeyCredential.user_id == user_id
            )
        ).all()
        return [bytes(r) for r in rows]

    def add_session(self, session: orm.Session) -> None:
        self._session.add(session)

    def delete_session(self, session: orm.Session) -> None:
        self._session.delete(session)

    def commit(self) -> None:
        self._session.commit()

    def token_by_hash(self, token_hash: str) -> orm.ApiToken | None:
        return self._session.scalar(
            select(orm.ApiToken).where(orm.ApiToken.token_hash == token_hash)
        )

    def tenant(self, tenant_id: str) -> orm.Tenant | None:
        return self._session.get(orm.Tenant, tenant_id)

    def user(self, user_id: str) -> orm.User | None:
        return self._session.get(orm.User, user_id)
