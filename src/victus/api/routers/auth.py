"""Passkeys, sessions, recovery and API tokens."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response, status

from victus.api.deps import Config, Ctx, Lookup, Uow, WebAuthn, Who, optional_principal
from victus.api.schemas.auth import MeOut, PasskeyOut, TokenCreatedOut, TokenOut
from victus.api.schemas.requests import (
    LoginOptionsIn,
    LoginVerifyIn,
    RecoveryIn,
    RegisterOptionsIn,
    RegisterVerifyIn,
    TokenIn,
)
from victus.application import dto
from victus.application.errors import Unauthenticated, ValidationFailed
from victus.application.use_cases import auth as uc
from victus.infrastructure.auth import sessions

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookie(response: Response, info: dto.SessionInfo, secure: bool) -> None:
    response.set_cookie(
        sessions.SESSION_COOKIE,
        info.session_id,
        expires=info.expires_at,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _secure(request: Request, cfg: Any) -> bool:
    # Behind the reverse proxy everything is HTTPS; plain HTTP only exists in development.
    origin = cfg.auth.origin or ""
    return origin.startswith("https://") or request.url.scheme == "https"


def _credential(body: Any) -> tuple[str, dict[str, Any]]:
    data = body.model_dump()
    cid = data.pop("ceremony_id", None)
    data.pop("name", None)
    if not cid:
        raise ValidationFailed("ceremony_id is required")
    return cid, data


@router.post("/webauthn/register/options")
def register_options(
    body: RegisterOptionsIn, who: Who, uow: Uow, webauthn: WebAuthn
) -> dict[str, Any]:
    return uc.BeginRegistration(uow, who.ctx, webauthn).execute(body.name)


@router.post(
    "/webauthn/register/verify", response_model=PasskeyOut, status_code=status.HTTP_201_CREATED
)
def register_verify(body: RegisterVerifyIn, who: Who, uow: Uow, webauthn: WebAuthn) -> PasskeyOut:
    cid, credential = _credential(body)
    return PasskeyOut.model_validate(
        uc.FinishRegistration(uow, who.ctx, webauthn).execute(cid, credential, body.name)
    )


@router.post("/webauthn/login/options")
def login_options(body: LoginOptionsIn, lookup: Lookup, webauthn: WebAuthn) -> dict[str, Any]:
    return uc.BeginLogin(lookup, webauthn).execute(body.email)


@router.post("/webauthn/login/verify", response_model=MeOut)
def login_verify(
    body: LoginVerifyIn,
    request: Request,
    response: Response,
    lookup: Lookup,
    uow: Uow,
    webauthn: WebAuthn,
    cfg: Config,
) -> MeOut:
    cid, credential = _credential(body)
    info = uc.FinishLogin(lookup, webauthn, cfg.auth.session_ttl_days).execute(
        cid, credential, request.headers.get("user-agent")
    )
    _set_cookie(response, info, _secure(request, cfg))
    ctx = uc.ResolveSession(lookup).execute(info.session_id)
    assert ctx is not None
    return MeOut.model_validate(uc.Me(uow, ctx[0]).execute(info.session_id, False))


@router.post("/recovery", response_model=MeOut)
def recovery(
    body: RecoveryIn, request: Request, response: Response, lookup: Lookup, uow: Uow, cfg: Config
) -> MeOut:
    info = uc.Recover(lookup).execute(body.email, body.code, request.headers.get("user-agent"))
    _set_cookie(response, info, _secure(request, cfg))
    ctx = uc.ResolveSession(lookup).execute(info.session_id)
    assert ctx is not None
    return MeOut.model_validate(uc.Me(uow, ctx[0]).execute(info.session_id, True))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, lookup: Lookup) -> Response:
    session_id = request.cookies.get(sessions.SESSION_COOKIE)
    if session_id:
        uc.Logout(lookup).execute(session_id)
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    out.delete_cookie(sessions.SESSION_COOKIE, path="/")
    return out


@router.get("/me", response_model=MeOut)
def me(request: Request, uow: Uow, lookup: Lookup) -> MeOut:
    principal = optional_principal(request, lookup)
    if principal is None:
        raise Unauthenticated("not signed in")
    return MeOut.model_validate(
        uc.Me(uow, principal.ctx).execute(principal.session_id, principal.recovery)
    )


@router.get("/passkeys", response_model=list[PasskeyOut])
def list_passkeys(who: Who, uow: Uow) -> list[PasskeyOut]:
    return [PasskeyOut.model_validate(p) for p in uc.ListPasskeys(uow, who.ctx).execute()]


@router.delete("/passkeys/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_passkey(passkey_id: str, who: Who, uow: Uow) -> Response:
    uc.DeletePasskey(uow, who.ctx).execute(passkey_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tokens", response_model=list[TokenOut])
def list_tokens(ctx: Ctx, uow: Uow) -> list[TokenOut]:
    return [TokenOut.model_validate(t) for t in uc.ListTokens(uow, ctx).execute()]


@router.post("/tokens", response_model=TokenCreatedOut, status_code=status.HTTP_201_CREATED)
def create_token(body: TokenIn, ctx: Ctx, uow: Uow) -> TokenCreatedOut:
    return TokenCreatedOut.model_validate(
        uc.CreateToken(uow, ctx).execute(body.name, body.scopes, body.expires_at)
    )


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(token_id: str, ctx: Ctx, uow: Uow) -> Response:
    uc.RevokeToken(uow, ctx).execute(token_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
