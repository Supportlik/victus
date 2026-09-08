"""FastAPI dependencies: database access, authentication, scopes, CSRF."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from victus.application.errors import Forbidden, Unauthenticated
from victus.application.ports.unit_of_work import UnitOfWork
from victus.application.tenant_context import TenantContext
from victus.application.use_cases._base import UowFactory
from victus.application.use_cases.auth import ResolveSession, ResolveToken
from victus.config.server import ServerConfig
from victus.infrastructure.auth import sessions
from victus.infrastructure.auth.lookup import SqlAuthLookup
from victus.infrastructure.auth.webauthn import WebAuthnService
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork

RECOVERY_ALLOWED = (
    "/api/v1/auth/me",
    "/api/v1/auth/passkeys",
    "/api/v1/auth/webauthn/register",
    "/api/v1/auth/logout",
)


@dataclass(frozen=True, slots=True)
class Principal:
    ctx: TenantContext
    session_id: str | None
    recovery: bool


def get_config(request: Request) -> ServerConfig:
    cfg: ServerConfig = request.app.state.config
    return cfg


def get_session_factory(request: Request) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    return factory


def get_webauthn(request: Request) -> WebAuthnService:
    svc: WebAuthnService = request.app.state.webauthn
    return svc


def get_uow_factory(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> UowFactory:
    def make(ctx: TenantContext) -> UnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory, ctx)

    return make


def get_lookup(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> Iterator[SqlAuthLookup]:
    session = session_factory()
    try:
        yield SqlAuthLookup(session)
    finally:
        session.close()


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def optional_principal(
    request: Request, lookup: Annotated[SqlAuthLookup, Depends(get_lookup)]
) -> Principal | None:
    token = _bearer(request)
    if token:
        ctx = ResolveToken(lookup).execute(token)
        if ctx is None:
            raise Unauthenticated("invalid or expired token")
        return Principal(ctx=ctx, session_id=None, recovery=False)
    session_id = request.cookies.get(sessions.SESSION_COOKIE)
    if session_id:
        resolved = ResolveSession(lookup).execute(session_id)
        if resolved is None:
            return None
        ctx, recovery = resolved
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            expected = sessions.csrf_token_for(session_id)
            if request.headers.get(sessions.CSRF_HEADER) != expected:
                raise Forbidden("missing or invalid CSRF token")
        if recovery and not request.url.path.startswith(RECOVERY_ALLOWED):
            raise Forbidden("recovery sessions may only manage passkeys")
        return Principal(ctx=ctx, session_id=session_id, recovery=recovery)
    return None


def current_principal(
    principal: Annotated[Principal | None, Depends(optional_principal)],
) -> Principal:
    if principal is None:
        raise Unauthenticated("sign in with a passkey or send a bearer token")
    return principal


def current_context(principal: Annotated[Principal, Depends(current_principal)]) -> TenantContext:
    return principal.ctx


def require_scope(scope: str) -> Callable[..., TenantContext]:
    def dep(ctx: Annotated[TenantContext, Depends(current_context)]) -> TenantContext:
        ctx.require(scope)
        return ctx

    return dep


Ctx = Annotated[TenantContext, Depends(current_context)]
Uow = Annotated[UowFactory, Depends(get_uow_factory)]
Lookup = Annotated[SqlAuthLookup, Depends(get_lookup)]
Config = Annotated[ServerConfig, Depends(get_config)]
WebAuthn = Annotated[WebAuthnService, Depends(get_webauthn)]
Who = Annotated[Principal, Depends(current_principal)]
