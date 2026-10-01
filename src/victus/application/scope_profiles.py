"""Scope profiles: which scopes to grant for a given intent.

The scope table says what each scope grants on its own; a profile is the opposite view —
"this client should do X and never Y" — named once here. ``docs/API.md`` ("Scope
profiles") explains each one, ``docs/SCOPES.md`` is generated from them, the web app offers
them as presets, and the tests build each one as a real token and check what it can and
cannot call.
"""

from __future__ import annotations

from dataclasses import dataclass

from victus.application.tenant_context import (
    SCOPE_AGENT_WRITE,
    SCOPE_APPROVE,
    SCOPE_CAPTURE_READ,
    SCOPE_CAPTURE_WRITE,
    SCOPE_READ,
    SCOPE_WRITE,
)


@dataclass(frozen=True, slots=True)
class ScopeProfile:
    key: str
    title: str
    #: In the order ``victus token create --scopes`` takes them.
    scopes: tuple[str, ...]
    intent: str

    @property
    def scope_list(self) -> str:
        return ",".join(self.scopes)


READ_ONLY = ScopeProfile(
    "read-only",
    "Read-only",
    (SCOPE_READ,),
    "Reports, days, catalogue; nothing written",
)
ASSISTANT = ScopeProfile(
    "assistant",
    "Assistant that proposes",
    (SCOPE_READ, SCOPE_WRITE, SCOPE_CAPTURE_READ, SCOPE_CAPTURE_WRITE, SCOPE_AGENT_WRITE),
    "Reads everything, drafts days and files catalogue proposals; creates no fact",
)
CAPTURE_UPLOADER = ScopeProfile(
    "capture-uploader",
    "Capture uploader",
    (SCOPE_CAPTURE_WRITE,),
    "Uploads photos and recordings, nothing else",
)
WORKER = ScopeProfile(
    "worker",
    "In-house worker",
    (SCOPE_READ, SCOPE_WRITE, SCOPE_CAPTURE_READ, SCOPE_CAPTURE_WRITE, SCOPE_AGENT_WRITE),
    "What victus worker runs with: the assistant's scopes, held in-process",
)
FULL_DELEGATE = ScopeProfile(
    "full-delegate",
    "Full delegate",
    (
        SCOPE_READ,
        SCOPE_WRITE,
        SCOPE_APPROVE,
        SCOPE_CAPTURE_READ,
        SCOPE_CAPTURE_WRITE,
        SCOPE_AGENT_WRITE,
    ),
    "Can also decide: whatever it writes is a fact",
)

PROFILES: tuple[ScopeProfile, ...] = (
    READ_ONLY,
    ASSISTANT,
    CAPTURE_UPLOADER,
    WORKER,
    FULL_DELEGATE,
)


def get_profile(key: str) -> ScopeProfile:
    for profile in PROFILES:
        if profile.key == key:
            return profile
    raise KeyError(key)
