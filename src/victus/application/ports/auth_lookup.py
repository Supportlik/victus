"""Unscoped lookups needed *before* a tenant is known (login, session, token).

Everything else in the application layer runs inside a tenant-scoped unit of
work; these three lookups are the deliberate exception and are therefore a
separate, read-only port.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from victus.infrastructure.db import orm


class AuthLookup(Protocol):
    def passkey_by_credential_id(
        self, credential_id: bytes
    ) -> tuple[orm.PasskeyCredential, orm.User] | None: ...

    def users_by_email(self, email: str) -> list[orm.User]: ...

    def session(self, session_id: str) -> orm.Session | None: ...

    def token_by_hash(self, token_hash: str) -> orm.ApiToken | None: ...

    def tenant(self, tenant_id: str) -> orm.Tenant | None: ...

    def user(self, user_id: str) -> orm.User | None: ...

    def credential_ids_for_user(self, user_id: str) -> list[bytes]: ...

    def add_session(self, session: orm.Session) -> None: ...

    def delete_session(self, session: orm.Session) -> None: ...

    def commit(self) -> None: ...
