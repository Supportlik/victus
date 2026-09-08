"""Recovery codes (Argon2id) — the way back in when every passkey is lost.

A code is 5 groups of 5 characters (``xxxxx-xxxxx-…``), shown once; only the
Argon2 hash is stored. Verification normalises case and separators.
"""

from __future__ import annotations

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i
_hasher = PasswordHasher()


def generate_recovery_code() -> str:
    groups = ["".join(secrets.choice(_ALPHABET) for _ in range(5)) for _ in range(5)]
    return "-".join(groups)


def normalise(code: str) -> str:
    return "".join(ch for ch in code.lower() if ch.isalnum())


def hash_recovery_code(code: str) -> str:
    return _hasher.hash(normalise(code))


def verify_recovery_code(code_hash: str | None, code: str) -> bool:
    if not code_hash:
        return False
    try:
        return _hasher.verify(code_hash, normalise(code))
    except VerifyMismatchError:
        return False
    except Exception:  # malformed hash, unknown parameters — treat as failure
        return False
