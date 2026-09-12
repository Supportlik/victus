"""The server-sent events channel (SPEC R83): hello, change, heartbeat, resume.

The stream never ends by itself, so it cannot be read through `TestClient` or an
httpx ASGI transport — both wait for the response to complete before handing over a
single byte. The driver below therefore speaks ASGI directly: it feeds one
`http.request`, collects the frames as they are sent, and answers `http.disconnect`
once it has seen enough, which is also what proves the loop ends on a disconnect.

The database is a file rather than the usual in-memory SQLite, because here a write
really does happen while a poll is in flight, and those must not share one connection.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.integration.api.conftest import RP_ID, Account, bearer
from victus.application.use_cases import day_logs as day_uc
from victus.application.use_cases._base import UowFactory
from victus.config.server import ServerConfig
from victus.domain.services.calendar import DEFAULT_TIMEZONE, today_in

pytestmark = pytest.mark.api

PAST = today_in(DEFAULT_TIMEZONE) - timedelta(days=3)
EVENTS_URL = "/api/v1/events"


@pytest.fixture
def api_config(tmp_path: Path) -> ServerConfig:
    """Overrides the package fixture: a file database, so the poll and the write that
    races it hold their own connections, and a poll interval a test can wait for."""
    return ServerConfig(  # type: ignore[call-arg]
        _env_file=None,
        database={"url": f"sqlite:///{(tmp_path / 'events.db').as_posix()}"},
        storage={"path": str(tmp_path / "blobs")},
        auth={"rp_id": RP_ID, "origin": f"http://{RP_ID}", "session_ttl_days": 30},
        mcp={"rate_limit_per_minute": 10_000},
        events={"enabled": True, "poll_seconds": 0.02, "heartbeat_seconds": 0.1},
    )


# ── an ASGI driver for an endless response ──────────────────────────────────


@dataclass(frozen=True, slots=True)
class Frame:
    event: str
    id: int
    data: dict[str, Any]


def _frames(raw: str) -> list[Frame]:
    out: list[Frame] = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        lines = (line.partition(":") for line in block.splitlines())
        fields = {key.strip(): value.strip() for key, _, value in lines}
        out.append(Frame(fields["event"], int(fields["id"]), json.loads(fields["data"])))
    return out


@dataclass(frozen=True, slots=True)
class Listened:
    status: int
    headers: dict[str, str]
    frames: list[Frame]

    def of(self, event: str) -> list[Frame]:
        return [f for f in self.frames if f.event == event]


def listen(
    app: FastAPI,
    headers: dict[str, str],
    *,
    want: int = 1,
    query: str = "",
    during: Callable[[], None] | None = None,
    timeout: float = 20.0,
) -> Listened:
    """Open the stream, collect ``want`` frames, then disconnect.

    ``during`` runs in a worker thread as soon as the first frame has arrived, which
    is how a write lands while the connection is open.
    """

    async def scenario() -> Listened:
        chunks: list[bytes] = []
        response: dict[str, Any] = {}
        opened, enough = anyio.Event(), anyio.Event()
        asked = False

        async def receive() -> dict[str, Any]:
            nonlocal asked
            if not asked:
                asked = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await enough.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                response["status"] = message["status"]
                response["headers"] = {
                    k.decode().lower(): v.decode() for k, v in message["headers"]
                }
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                seen = len(_frames(b"".join(chunks).decode()))
                if seen >= 1:
                    opened.set()
                if seen >= want or not message.get("more_body", False):
                    enough.set()

        async def act() -> None:
            await opened.wait()
            if during is not None:
                await anyio.to_thread.run_sync(during)

        scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": EVENTS_URL,
            "raw_path": EVENTS_URL.encode(),
            "query_string": query.encode(),
            "root_path": "",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": ("127.0.0.1", 4711),
            "server": (RP_ID, 80),
        }
        with anyio.fail_after(timeout):
            async with anyio.create_task_group() as tg:
                tg.start_soon(act)
                await app(scope, receive, send)
        return Listened(
            status=int(response.get("status", 0)),
            headers=dict(response.get("headers", {})),
            frames=_frames(b"".join(chunks).decode()),
        )

    return anyio.run(scenario)


def _targets(frame: Frame) -> list[tuple[str, str]]:
    return [(t["action"], t["type"]) for t in frame.data["targets"]]


@pytest.fixture
def seeded(
    client: TestClient, alice_token: dict[str, str], api_factory: UowFactory, alice_account: Account
) -> Iterator[None]:
    """One untouched capture and one past day that was never closed."""
    r = client.post("/api/v1/captures", data={"text": "two slices of bread"}, headers=alice_token)
    assert r.status_code == 201, r.text
    day_uc.CreateDay(api_factory, alice_account.ctx).execute(PAST, reliable=True)
    yield


# ── cases ───────────────────────────────────────────────────────────────────


def test_connect_says_where_the_tenant_stands(
    api_app: FastAPI, alice_token: dict[str, str], seeded: None
) -> None:
    """T-API-076: a connect answers `hello` with the current cursor and the counts."""
    out = listen(api_app, alice_token, want=1)
    assert out.status == 200
    assert out.headers["content-type"].startswith("text/event-stream")
    assert out.headers["cache-control"] == "no-cache"
    assert out.headers["x-accel-buffering"] == "no"

    hello = out.of("hello")[0]
    assert hello.id == hello.data["cursor"] > 0
    assert hello.data["counts"] == {
        "new_captures": 1,
        "draft_days": 0,
        "open_days": 1,
        "pending_proposals": 0,
    }
    assert "targets" not in hello.data


def test_a_write_while_connected_is_pushed(
    api_app: FastAPI,
    alice_token: dict[str, str],
    api_factory: UowFactory,
    alice_account: Account,
    seeded: None,
) -> None:
    """T-API-077: a write after the connect produces a `change` naming that target."""
    written = PAST - timedelta(days=1)

    def write() -> None:
        day_uc.CreateDay(api_factory, alice_account.ctx).execute(written, reliable=True)

    out = listen(api_app, alice_token, want=2, during=write)
    hello, change = out.of("hello")[0], out.of("change")[0]
    assert change.data["cursor"] > hello.data["cursor"]
    assert change.id == change.data["cursor"]
    assert _targets(change) == [("day.create", "day_log")]
    assert change.data["truncated"] is False
    # the counts travel with the change, so the badges need no request of their own
    assert change.data["counts"]["open_days"] == 2


def test_last_event_id_resumes_from_the_cursor(
    api_app: FastAPI,
    alice_token: dict[str, str],
    api_factory: UowFactory,
    alice_account: Account,
    seeded: None,
) -> None:
    """T-API-078: a reconnect with `Last-Event-ID` replays only what it missed."""
    first = listen(api_app, alice_token, want=1)
    cursor = int(first.of("hello")[0].data["cursor"])
    day_uc.CreateDay(api_factory, alice_account.ctx).execute(
        PAST - timedelta(days=2), reliable=True
    )

    resumed = listen(api_app, {**alice_token, "Last-Event-ID": str(cursor)}, want=2)
    assert resumed.of("hello")[0].data["cursor"] == cursor
    assert _targets(resumed.of("change")[0]) == [("day.create", "day_log")]

    # ?cursor= does the same for a client that is not an EventSource
    by_query = listen(api_app, alice_token, want=2, query=f"cursor={cursor}")
    assert by_query.of("hello")[0].data["cursor"] == cursor
    assert _targets(by_query.of("change")[0]) == [("day.create", "day_log")]

    # starting from the current cursor there is nothing to replay; only heartbeats follow
    current = int(by_query.of("change")[0].data["cursor"])
    quiet = listen(api_app, alice_token, want=2, query=f"cursor={current}")
    assert quiet.of("change") == []
    assert quiet.of("heartbeat")[0].data == {"cursor": current}


def test_another_tenants_writes_never_appear(
    api_app: FastAPI,
    alice_token: dict[str, str],
    api_factory: UowFactory,
    bob_account: Account,
    seeded: None,
) -> None:
    """T-API-079: Bob's writes move his cursor, never Alice's stream."""

    def bob_writes() -> None:
        day_uc.CreateDay(api_factory, bob_account.ctx).execute(PAST, reliable=True)

    out = listen(api_app, alice_token, want=3, during=bob_writes)
    assert out.of("change") == []
    assert [f.event for f in out.frames] == ["hello", "heartbeat", "heartbeat"]
    assert out.of("heartbeat")[0].id == out.of("hello")[0].id


def test_the_stream_never_carries_a_diff(
    api_app: FastAPI,
    alice_token: dict[str, str],
    api_factory: UowFactory,
    alice_account: Account,
    seeded: None,
) -> None:
    """T-API-080: `day.create` books a diff; the listener learns only the target."""
    written = PAST - timedelta(days=4)

    def write() -> None:
        day_uc.CreateDay(api_factory, alice_account.ctx).execute(written, reliable=True)

    out = listen(api_app, alice_token, want=2, during=write)
    target = out.of("change")[0].data["targets"][0]
    assert set(target) == {"action", "type", "id"}
    everything = json.dumps([f.data for f in out.frames])
    assert "diff" not in everything
    assert written.isoformat() not in everything  # the diff's only field


def test_refusals(
    api_app: FastAPI,
    client: TestClient,
    alice_token: dict[str, str],
    api_factory: UowFactory,
    alice_account: Account,
) -> None:
    """T-API-081: no principal, a scope that cannot read captures, and the feature off."""
    assert client.get(EVENTS_URL).status_code == 401
    assert client.get(EVENTS_URL, headers={"Authorization": "Bearer nope"}).status_code == 401
    read_only = bearer(api_factory, alice_account, ["read"])
    assert client.get(EVENTS_URL, headers=read_only).status_code == 403

    cfg: ServerConfig = api_app.state.config
    cfg.events.enabled = False
    try:
        r = client.get(EVENTS_URL, headers=alice_token)
        assert r.status_code == 503
        assert r.headers["content-type"].startswith("application/problem+json")
        assert r.json()["title"] == "Feature disabled"
    finally:
        cfg.events.enabled = True
