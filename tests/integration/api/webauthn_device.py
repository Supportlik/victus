"""A minimal software authenticator for tests (ES256, attestation "none").

Produces the JSON a browser would hand back from ``navigator.credentials`` so the
API's WebAuthn ceremonies can be exercised end to end without a device.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import bytes_to_base64url, encode_cbor

AAGUID = b"\x00" * 16


class SoftAuthenticator:
    def __init__(self, rp_id: str, origin: str) -> None:
        self.rp_id = rp_id
        self.origin = origin
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.sign_count = 0
        self.user_handle: bytes | None = None

    # ── helpers ──
    def _cose_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return encode_cbor(
            {
                1: 2,  # kty EC2
                3: -7,  # alg ES256
                -1: 1,  # crv P-256
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )

    def _client_data(self, typ: str, challenge: str) -> bytes:
        return json.dumps(
            {"type": typ, "challenge": challenge, "origin": self.origin, "crossOrigin": False}
        ).encode()

    # ── ceremonies ──
    def register(self, options: dict[str, Any]) -> dict[str, Any]:
        """``options`` is the JSON our API returns (challenge base64url, rp, user…)."""
        self.user_handle = options["user"]["id"].encode()
        client_data = self._client_data("webauthn.create", options["challenge"])
        flags = b"\x41"  # user present + attested credential data
        auth_data = (
            hashlib.sha256(self.rp_id.encode()).digest()
            + flags
            + struct.pack(">I", self.sign_count)
            + AAGUID
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + self._cose_key()
        )
        attestation = encode_cbor({"fmt": "none", "attStmt": {}, "authData": auth_data})
        cid = bytes_to_base64url(self.credential_id)
        return {
            "id": cid,
            "rawId": cid,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "attestationObject": bytes_to_base64url(attestation),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
        }

    def authenticate(
        self, options: dict[str, Any], *, sign_count: int | None = None
    ) -> dict[str, Any]:
        self.sign_count = sign_count if sign_count is not None else self.sign_count + 1
        client_data = self._client_data("webauthn.get", options["challenge"])
        auth_data = (
            hashlib.sha256(self.rp_id.encode()).digest()
            + b"\x01"
            + struct.pack(">I", self.sign_count)
        )
        signature = self.key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        cid = bytes_to_base64url(self.credential_id)
        return {
            "id": cid,
            "rawId": cid,
            "type": "public-key",
            "response": {
                "authenticatorData": bytes_to_base64url(auth_data),
                "clientDataJSON": bytes_to_base64url(client_data),
                "signature": bytes_to_base64url(signature),
                "userHandle": bytes_to_base64url(self.user_handle) if self.user_handle else None,
            },
            "clientExtensionResults": {},
        }
