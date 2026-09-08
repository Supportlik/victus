"""Passkeys, sessions, recovery codes and API tokens."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from victus.application import dto
from victus.application.errors import Forbidden, NotFound, Unauthenticated, ValidationFailed
from victus.application.ports.auth_lookup import AuthLookup
from victus.application.tenant_context import ALL_SCOPES, SCOPE_ADMIN, TenantContext
from victus.application.use_cases._base import UowFactory, UseCase, now
from victus.infrastructure.auth import recovery, sessions, tokens
from victus.infrastructure.auth.webauthn import WebAuthnService, credential_id_from_response
from victus.infrastructure.db import orm

MAX_TOKEN_DAYS = 365
KNOWN_SCOPES = ALL_SCOPES


def _user_view(u: orm.User) -> dto.UserView:
    return dto.UserView(id=u.id, display_name=u.display_name, email=u.email, role=u.role)


def _passkey_view(p: orm.PasskeyCredential) -> dto.PasskeyView:
    return dto.PasskeyView(
        id=p.id, name=p.name, created_at=p.created_at, last_used_at=p.last_used_at
    )


def _token_view(t: orm.ApiToken) -> dto.TokenView:
    return dto.TokenView(
        id=t.id,
        name=t.name,
        prefix=t.prefix,
        scopes=list(t.scopes or []),
        expires_at=t.expires_at,
        last_used_at=t.last_used_at,
        revoked_at=t.revoked_at,
    )


# ── registration (needs a session: normal or recovery) ──────────────────────


class BeginRegistration(UseCase):
    def __init__(
        self, uow_factory: UowFactory, ctx: TenantContext, webauthn: WebAuthnService
    ) -> None:
        super().__init__(uow_factory, ctx)
        self.webauthn = webauthn

    def execute(self, passkey_name: str | None) -> dict[str, Any]:
        if not self.ctx.user_id:
            raise Unauthenticated("a user session is required to register a passkey")
        with self._uow() as uow:
            user = uow.users.get(self.ctx.user_id)
            if user is None:
                raise Unauthenticated("user not found")
            existing = [p.credential_id for p in uow.users.passkeys_for_user(user.id)]
            _, options = self.webauthn.registration_options(
                tenant_id=self.ctx.tenant_id,
                user_id=user.id,
                user_name=user.email or user.display_name,
                display_name=user.display_name,
                existing_credential_ids=existing,
                passkey_name=passkey_name,
            )
            return options


class FinishRegistration(UseCase):
    def __init__(
        self, uow_factory: UowFactory, ctx: TenantContext, webauthn: WebAuthnService
    ) -> None:
        super().__init__(uow_factory, ctx)
        self.webauthn = webauthn

    def execute(
        self, ceremony_id: str, credential: dict[str, Any], name: str | None
    ) -> dto.PasskeyView:
        if not self.ctx.user_id:
            raise Unauthenticated("a user session is required")
        try:
            pending, result = self.webauthn.verify_registration(ceremony_id, credential)
        except Exception as exc:
            raise ValidationFailed(f"passkey registration failed: {exc}") from exc
        if pending.user_id != self.ctx.user_id or pending.tenant_id != self.ctx.tenant_id:
            raise Forbidden("ceremony belongs to another user")
        with self._uow() as uow:
            if uow.users.passkey_by_credential_id(result.credential_id) is not None:
                raise ValidationFailed("this passkey is already registered")
            row = uow.users.add_passkey(
                orm.PasskeyCredential(
                    user_id=self.ctx.user_id,
                    credential_id=result.credential_id,
                    public_key=result.public_key,
                    sign_count=result.sign_count,
                    aaguid=result.aaguid,
                    transports=result.transports,
                    name=name or pending.name or "Passkey",
                )
            )
            uow.audit.record("passkey.add", "passkey_credential", row.id, {"name": row.name})
            view = _passkey_view(row)
            uow.commit()
            return view


# ── login (no tenant yet: uses the unscoped lookup) ─────────────────────────


class BeginLogin:
    def __init__(self, lookup: AuthLookup, webauthn: WebAuthnService) -> None:
        self.lookup = lookup
        self.webauthn = webauthn

    def execute(self, email: str | None) -> dict[str, Any]:
        allowed: list[bytes] | None = None
        if email:
            allowed = []
            for user in self.lookup.users_by_email(email):
                # credentials of every account with that address (one per tenant)
                allowed.extend(self.lookup.credential_ids_for_user(user.id))
        _, options = self.webauthn.authentication_options(allowed_credential_ids=allowed)
        return options


class FinishLogin:
    def __init__(
        self, lookup: AuthLookup, webauthn: WebAuthnService, session_ttl_days: int
    ) -> None:
        self.lookup = lookup
        self.webauthn = webauthn
        self.ttl_days = session_ttl_days

    def execute(
        self, ceremony_id: str, credential: dict[str, Any], user_agent: str | None
    ) -> dto.SessionInfo:
        try:
            cred_id = credential_id_from_response(credential)
        except ValueError as exc:
            raise Unauthenticated(str(exc)) from exc
        found = self.lookup.passkey_by_credential_id(cred_id)
        if found is None:
            raise Unauthenticated("unknown passkey")
        passkey, user = found
        try:
            result = self.webauthn.verify_authentication(
                ceremony_id,
                credential,
                public_key=passkey.public_key,
                current_sign_count=passkey.sign_count,
            )
        except Exception as exc:
            raise Unauthenticated(f"passkey login failed: {exc}") from exc
        passkey.sign_count = result.new_sign_count
        passkey.last_used_at = now()
        session = orm.Session(
            user_id=user.id,
            tenant_id=user.tenant_id,
            expires_at=sessions.session_expiry(self.ttl_days),
            user_agent=(user_agent or "")[:500] or None,
        )
        self.lookup.add_session(session)
        self.lookup.commit()
        return dto.SessionInfo(
            session_id=session.id,
            tenant_id=user.tenant_id,
            user_id=user.id,
            expires_at=session.expires_at,
        )


class Recover:
    """Recovery code → short session that may only manage passkeys."""

    def __init__(self, lookup: AuthLookup) -> None:
        self.lookup = lookup

    def execute(self, email: str, code: str, user_agent: str | None) -> dto.SessionInfo:
        for user in self.lookup.users_by_email(email):
            if recovery.verify_recovery_code(user.recovery_code_hash, code):
                session = orm.Session(
                    user_id=user.id,
                    tenant_id=user.tenant_id,
                    expires_at=sessions.recovery_expiry(),
                    user_agent=sessions.tag_recovery(user_agent),
                )
                self.lookup.add_session(session)
                self.lookup.commit()
                return dto.SessionInfo(
                    session_id=session.id,
                    tenant_id=user.tenant_id,
                    user_id=user.id,
                    expires_at=session.expires_at,
                    recovery=True,
                )
        raise Unauthenticated("recovery code not accepted")


class ResolveSession:
    def __init__(self, lookup: AuthLookup) -> None:
        self.lookup = lookup

    def execute(self, session_id: str) -> tuple[TenantContext, bool] | None:
        s = self.lookup.session(session_id)
        if s is None or s.expires_at <= now():
            return None
        return TenantContext(
            tenant_id=s.tenant_id, user_id=s.user_id
        ), sessions.is_recovery_session(s.user_agent)


class ResolveToken:
    def __init__(self, lookup: AuthLookup) -> None:
        self.lookup = lookup

    def execute(self, clear_text: str) -> TenantContext | None:
        if not tokens.looks_like_token(clear_text):
            return None
        t = self.lookup.token_by_hash(tokens.hash_token(clear_text))
        if t is None or t.revoked_at is not None:
            return None
        if t.expires_at is not None and t.expires_at <= now():
            return None
        t.last_used_at = now()
        self.lookup.commit()
        return TenantContext(
            tenant_id=t.tenant_id,
            user_id=t.user_id,
            token_id=t.id,
            scopes=frozenset(t.scopes or []),
        )


class Logout:
    def __init__(self, lookup: AuthLookup) -> None:
        self.lookup = lookup

    def execute(self, session_id: str) -> None:
        s = self.lookup.session(session_id)
        if s is not None:
            self.lookup.delete_session(s)
            self.lookup.commit()


# ── inside a tenant ─────────────────────────────────────────────────────────


class Me(UseCase):
    def execute(self, session_id: str | None = None, recovery_session: bool = False) -> dto.MeView:
        with self._uow() as uow:
            tenant = uow.tenants.get(self.ctx.tenant_id)
            if tenant is None:
                raise Unauthenticated("tenant not found")
            if self.ctx.user_id is None:
                raise Unauthenticated("token contexts have no user profile")
            user = uow.users.get(self.ctx.user_id)
            if user is None:
                raise Unauthenticated("user not found")
            passkeys = len(uow.users.passkeys_for_user(user.id))
            return dto.MeView(
                user=_user_view(user),
                tenant=dto.TenantView(id=tenant.id, slug=tenant.slug, name=tenant.name),
                csrf_token=sessions.csrf_token_for(session_id) if session_id else "",
                passkeys=passkeys,
                recovery_session=recovery_session,
            )


class ListPasskeys(UseCase):
    def execute(self) -> list[dto.PasskeyView]:
        if not self.ctx.user_id:
            raise Unauthenticated("a user session is required")
        with self._uow() as uow:
            return [_passkey_view(p) for p in uow.users.passkeys_for_user(self.ctx.user_id)]


class DeletePasskey(UseCase):
    def execute(self, passkey_id: str) -> None:
        if not self.ctx.user_id:
            raise Unauthenticated("a user session is required")
        with self._uow() as uow:
            mine = list(uow.users.passkeys_for_user(self.ctx.user_id))
            target = next((p for p in mine if p.id == passkey_id), None)
            if target is None:
                raise NotFound("passkey not found")
            if len(mine) == 1:
                raise ValidationFailed("cannot delete the last passkey; register another one first")
            uow.users.delete_passkey(target)
            uow.audit.record(
                "passkey.delete", "passkey_credential", passkey_id, {"name": target.name}
            )
            uow.commit()


class ListTokens(UseCase):
    def execute(self) -> list[dto.TokenView]:
        with self._uow() as uow:
            return [_token_view(t) for t in uow.users.tokens()]


class CreateToken(UseCase):
    def execute(
        self, name: str, scopes: list[str], expires_at: datetime | None
    ) -> dto.TokenCreatedView:
        if self.ctx.token_id:
            self.ctx.require(SCOPE_ADMIN)  # tokens cannot mint tokens
        unknown = sorted(set(scopes) - KNOWN_SCOPES)
        if unknown:
            raise ValidationFailed(f"unknown scopes: {', '.join(unknown)}")
        if not scopes:
            raise ValidationFailed("at least one scope is required")
        limit = now() + timedelta(days=MAX_TOKEN_DAYS)
        if expires_at is None:
            expires_at = limit
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at > limit:
            raise ValidationFailed(f"tokens expire after at most {MAX_TOKEN_DAYS} days")
        generated = tokens.generate_token()
        with self._uow() as uow:
            row = uow.users.add_token(
                orm.ApiToken(
                    tenant_id=self.ctx.tenant_id,
                    user_id=self.ctx.user_id,
                    name=name,
                    prefix=generated.prefix,
                    token_hash=generated.token_hash,
                    scopes=list(scopes),
                    expires_at=expires_at,
                )
            )
            uow.audit.record("token.create", "api_token", row.id, {"name": name, "scopes": scopes})
            base = _token_view(row)
            uow.commit()
            return dto.TokenCreatedView(
                id=base.id,
                name=base.name,
                prefix=base.prefix,
                scopes=base.scopes,
                expires_at=base.expires_at,
                last_used_at=base.last_used_at,
                revoked_at=base.revoked_at,
                token=generated.clear_text,
            )


class RevokeToken(UseCase):
    def execute(self, token_id: str) -> None:
        with self._uow() as uow:
            row = next((t for t in uow.users.tokens() if t.id == token_id), None)
            if row is None:
                raise NotFound("token not found")
            row.revoked_at = now()
            uow.audit.record("token.revoke", "api_token", row.id, {})
            uow.commit()
