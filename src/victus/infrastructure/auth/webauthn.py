"""Thin wrapper around ``py_webauthn`` plus a challenge store.

The store keeps pending challenges for a few minutes keyed by an opaque
``ceremony_id`` the client echoes back. The default implementation is
in-memory: fine for one API process. Several processes need a shared store
(database or Redis) — implement :class:`ChallengeStore` for that; no other code
changes.
"""

from __future__ import annotations

import json
import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, options_to_json
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

CHALLENGE_TTL = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class PendingChallenge:
    challenge: bytes
    purpose: str  # "register" | "login"
    tenant_id: str | None
    user_id: str | None
    expires_at: datetime
    name: str | None = None  # passkey label chosen at registration


class ChallengeStore(Protocol):
    def put(self, pending: PendingChallenge) -> str: ...

    def pop(self, ceremony_id: str) -> PendingChallenge | None: ...


class InMemoryChallengeStore:
    def __init__(self) -> None:
        self._items: dict[str, PendingChallenge] = {}
        self._lock = threading.Lock()

    def put(self, pending: PendingChallenge) -> str:
        cid = secrets.token_urlsafe(24)
        with self._lock:
            self._purge()
            self._items[cid] = pending
        return cid

    def pop(self, ceremony_id: str) -> PendingChallenge | None:
        with self._lock:
            self._purge()
            return self._items.pop(ceremony_id, None)

    def _purge(self) -> None:
        now = datetime.now(UTC)
        for key in [k for k, v in self._items.items() if v.expires_at <= now]:
            del self._items[key]


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    credential_id: bytes
    public_key: bytes
    sign_count: int
    aaguid: str | None
    transports: list[str] | None


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    credential_id: bytes
    new_sign_count: int


class WebAuthnService:
    def __init__(self, rp_id: str, rp_name: str, origin: str, store: ChallengeStore) -> None:
        self.rp_id = rp_id
        self.rp_name = rp_name
        self.origin = origin
        self.store = store

    # ── registration ──
    def registration_options(
        self,
        *,
        tenant_id: str,
        user_id: str,
        user_name: str,
        display_name: str,
        existing_credential_ids: list[bytes],
        passkey_name: str | None,
    ) -> tuple[str, dict[str, Any]]:
        options = generate_registration_options(
            rp_id=self.rp_id,
            rp_name=self.rp_name,
            user_id=user_id.encode("ascii"),
            user_name=user_name,
            user_display_name=display_name,
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=c) for c in existing_credential_ids
            ],
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
        )
        cid = self.store.put(
            PendingChallenge(
                challenge=options.challenge,
                purpose="register",
                tenant_id=tenant_id,
                user_id=user_id,
                expires_at=datetime.now(UTC) + CHALLENGE_TTL,
                name=passkey_name,
            )
        )
        payload = json.loads(options_to_json(options))
        payload["ceremony_id"] = cid
        return cid, payload

    def verify_registration(
        self, ceremony_id: str, credential: dict[str, Any]
    ) -> tuple[PendingChallenge, RegistrationResult]:
        pending = self.store.pop(ceremony_id)
        if pending is None or pending.purpose != "register":
            raise ValueError("unknown or expired registration ceremony")
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=pending.challenge,
            expected_rp_id=self.rp_id,
            expected_origin=self.origin,
        )
        transports = credential.get("response", {}).get("transports")
        return pending, RegistrationResult(
            credential_id=verified.credential_id,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            aaguid=str(verified.aaguid) if verified.aaguid else None,
            transports=list(transports) if isinstance(transports, list) else None,
        )

    # ── authentication ──
    def authentication_options(
        self, *, allowed_credential_ids: list[bytes] | None
    ) -> tuple[str, dict[str, Any]]:
        options = generate_authentication_options(
            rp_id=self.rp_id,
            allow_credentials=[
                PublicKeyCredentialDescriptor(id=c) for c in allowed_credential_ids or []
            ],
            user_verification=UserVerificationRequirement.PREFERRED,
        )
        cid = self.store.put(
            PendingChallenge(
                challenge=options.challenge,
                purpose="login",
                tenant_id=None,
                user_id=None,
                expires_at=datetime.now(UTC) + CHALLENGE_TTL,
            )
        )
        payload = json.loads(options_to_json(options))
        payload["ceremony_id"] = cid
        return cid, payload

    def verify_authentication(
        self,
        ceremony_id: str,
        credential: dict[str, Any],
        *,
        public_key: bytes,
        current_sign_count: int,
    ) -> AuthenticationResult:
        pending = self.store.pop(ceremony_id)
        if pending is None or pending.purpose != "login":
            raise ValueError("unknown or expired login ceremony")
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=pending.challenge,
            expected_rp_id=self.rp_id,
            expected_origin=self.origin,
            credential_public_key=public_key,
            credential_current_sign_count=current_sign_count,
        )
        return AuthenticationResult(
            credential_id=verified.credential_id, new_sign_count=verified.new_sign_count
        )


def credential_id_from_response(credential: dict[str, Any]) -> bytes:
    """``rawId``/``id`` of a client response as bytes (base64url in JSON)."""
    raw = credential.get("rawId") or credential.get("id")
    if not isinstance(raw, str):
        raise ValueError("credential id missing")
    return base64url_to_bytes(raw)
