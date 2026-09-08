"""Tenants, users, passkeys, sessions and API tokens."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from victus.infrastructure.db import orm
from victus.infrastructure.db.repositories._base import Repo


class TenantRepo(Repo):
    """Not tenant-scoped: it manages the tenants themselves (admin/CLI only)."""

    def get(self, tenant_id: str) -> orm.Tenant | None:
        return self.session.get(orm.Tenant, tenant_id)

    def get_by_slug(self, slug: str) -> orm.Tenant | None:
        return self.session.scalar(select(orm.Tenant).where(orm.Tenant.slug == slug))

    def add(self, tenant: orm.Tenant) -> orm.Tenant:
        self.session.add(tenant)
        self.session.flush()
        return tenant

    def list(self) -> Sequence[orm.Tenant]:
        return self.session.scalars(select(orm.Tenant).order_by(orm.Tenant.slug)).all()


class UserRepo(Repo):
    def get(self, user_id: str) -> orm.User | None:
        return self.session.scalar(
            self.scoped(select(orm.User).where(orm.User.id == user_id), orm.User)
        )

    def get_by_email(self, email: str) -> orm.User | None:
        return self.session.scalar(
            self.scoped(select(orm.User).where(orm.User.email == email), orm.User)
        )

    def add(self, user: orm.User) -> orm.User:
        self.guard(user)
        self.session.add(user)
        self.session.flush()
        return user

    def list(self) -> Sequence[orm.User]:
        return self.session.scalars(
            self.scoped(select(orm.User), orm.User).order_by(orm.User.created_at)
        ).all()

    # passkeys
    def add_passkey(self, credential: orm.PasskeyCredential) -> orm.PasskeyCredential:
        if self.get(credential.user_id) is None:
            raise PermissionError("user not in tenant")
        self.session.add(credential)
        self.session.flush()
        return credential

    def passkey_by_credential_id(self, credential_id: bytes) -> orm.PasskeyCredential | None:
        stmt = (
            select(orm.PasskeyCredential)
            .join(orm.User, orm.User.id == orm.PasskeyCredential.user_id)
            .where(
                orm.PasskeyCredential.credential_id == credential_id,
                orm.User.tenant_id == self.tenant_id,
            )
        )
        return self.session.scalar(stmt)

    def passkeys_for_user(self, user_id: str) -> Sequence[orm.PasskeyCredential]:
        stmt = (
            select(orm.PasskeyCredential)
            .join(orm.User, orm.User.id == orm.PasskeyCredential.user_id)
            .where(orm.PasskeyCredential.user_id == user_id, orm.User.tenant_id == self.tenant_id)
            .order_by(orm.PasskeyCredential.created_at)
        )
        return self.session.scalars(stmt).all()

    def delete_passkey(self, credential: orm.PasskeyCredential) -> None:
        if self.get(credential.user_id) is None:
            raise PermissionError("user not in tenant")
        self.session.delete(credential)
        self.session.flush()

    # sessions
    def add_session(self, session: orm.Session) -> orm.Session:
        self.guard(session)
        self.session.add(session)
        self.session.flush()
        return session

    def get_session(self, session_id: str) -> orm.Session | None:
        return self.session.scalar(
            self.scoped(select(orm.Session).where(orm.Session.id == session_id), orm.Session)
        )

    def delete_session(self, session_id: str) -> None:
        s = self.get_session(session_id)
        if s is not None:
            self.session.delete(s)
            self.session.flush()

    # tokens
    def add_token(self, token: orm.ApiToken) -> orm.ApiToken:
        self.guard(token)
        self.session.add(token)
        self.session.flush()
        return token

    def token_by_hash(self, token_hash: str) -> orm.ApiToken | None:
        # Token lookup happens before a tenant is known: unscoped by design; the
        # token row itself names the tenant the context is then built for.
        return self.session.scalar(
            select(orm.ApiToken).where(orm.ApiToken.token_hash == token_hash)
        )

    def tokens(self) -> Sequence[orm.ApiToken]:
        return self.session.scalars(
            self.scoped(select(orm.ApiToken), orm.ApiToken).order_by(orm.ApiToken.created_at)
        ).all()
