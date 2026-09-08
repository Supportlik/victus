"""API tokens: ``vct_`` + 8-character public prefix + 32 random bytes.

Only the SHA-256 of the full token is stored; the clear text is shown exactly
once at creation. The prefix lets people recognise a token in a list without
revealing the secret.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

TOKEN_PREFIX = "vct_"
_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


@dataclass(frozen=True, slots=True)
class GeneratedToken:
    clear_text: str
    prefix: str
    token_hash: str


def hash_token(clear_text: str) -> str:
    return hashlib.sha256(clear_text.encode("ascii")).hexdigest()


def generate_token() -> GeneratedToken:
    public = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    secret = secrets.token_urlsafe(32)
    clear = f"{TOKEN_PREFIX}{public}_{secret}"
    return GeneratedToken(
        clear_text=clear, prefix=f"{TOKEN_PREFIX}{public}", token_hash=hash_token(clear)
    )


def looks_like_token(value: str) -> bool:
    return value.startswith(TOKEN_PREFIX) and len(value) > len(TOKEN_PREFIX) + 9
