"""Server-side sessions: cookie parameters and the CSRF double-submit token.

The CSRF token is derived from the session id (``sha256("victus-csrf:" + id)``).
A cross-site attacker cannot read the HttpOnly cookie and therefore cannot
compute the token; no extra server secret is needed. Recovery sessions are
short-lived and only allowed to manage passkeys.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

SESSION_COOKIE = "victus_session"
CSRF_HEADER = "X-CSRF-Token"
RECOVERY_TTL = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class CookieSettings:
    name: str = SESSION_COOKIE
    secure: bool = True
    same_site: str = "lax"
    path: str = "/"


def csrf_token_for(session_id: str) -> str:
    return hashlib.sha256(f"victus-csrf:{session_id}".encode()).hexdigest()


def session_expiry(ttl_days: int, *, now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) + timedelta(days=ttl_days)


def recovery_expiry(*, now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) + RECOVERY_TTL


def is_recovery_session(user_agent: str | None) -> bool:
    """Recovery sessions are tagged through the stored user agent (no schema change)."""
    return user_agent is not None and user_agent.startswith("recovery:")


def tag_recovery(user_agent: str | None) -> str:
    return f"recovery:{user_agent or ''}"[:500]
