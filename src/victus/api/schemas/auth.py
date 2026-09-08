"""Auth responses."""

from __future__ import annotations

from datetime import datetime

from victus.api.schemas.common import Out


class UserOut(Out):
    id: str
    display_name: str
    email: str | None
    role: str


class TenantOut(Out):
    id: str
    slug: str
    name: str


class MeOut(Out):
    user: UserOut
    tenant: TenantOut
    csrf_token: str
    passkeys: int
    recovery_session: bool = False


class PasskeyOut(Out):
    id: str
    name: str | None
    created_at: datetime
    last_used_at: datetime | None


class TokenOut(Out):
    id: str
    name: str
    prefix: str
    scopes: list[str]
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


class TokenCreatedOut(TokenOut):
    token: str


class UserCreatedOut(Out):
    user: UserOut
    recovery_code: str
