"""MCP server: stdio (``victus mcp --tenant``) and Streamable HTTP (``/mcp``) transports.

The server registers every :mod:`victus.mcp.tools` spec with the MCP SDK
(``mcp`` 2.x, ``MCPServer``). Over stdio the tenant is fixed by the CLI flag and
the local process is trusted; over HTTP each request carries a Victus API token
(``Authorization: Bearer vct_…``) whose scopes become the tenant context, the
client IP must fall into ``mcp.allowed_cidrs`` and requests are rate-limited
per token (ADR 0004, SPEC R41).
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import inspect
import ipaddress
import json
import logging
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError as McpToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ImageContent, TextContent
from pydantic import AnyHttpUrl, Field
from sqlalchemy.orm import Session, sessionmaker
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from victus.application.ports.blob_storage import BlobStorage
from victus.application.ports.transcription import TranscriptionPort
from victus.application.ports.unit_of_work import UnitOfWork
from victus.application.tenant_context import ALL_SCOPES, TenantContext
from victus.application.use_cases.auth import ResolveToken
from victus.config.server import ServerConfig
from victus.infrastructure.auth.lookup import SqlAuthLookup
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork
from victus.mcp.tools import (
    TOOLS,
    ImageResult,
    ToolContext,
    ToolError,
    ToolSpec,
    dispatch,
    result_text,
)

log = logging.getLogger("victus.mcp")

SERVER_NAME = "victus"
INSTRUCTIONS = (
    "Victus nutrition tracking. Read tools return JSON; write tools need the matching scope. "
    "Drafting a day: agent_run_start → day_thread_get → product_search per item → draft_create "
    "→ agent_run_finish. Approval is a separate, human decision (day_approve)."
)

ContextResolver = Callable[[], TenantContext]


# ── tool registration ───────────────────────────────────────────────────────


def _wrapper_for(spec: ToolSpec, resolve: Callable[[], ToolContext]) -> Callable[..., Any]:
    """A function whose signature mirrors the pydantic input model (the SDK derives the schema)."""

    def call(**kwargs: Any) -> list[TextContent | ImageContent]:
        tc = resolve()
        try:
            result = dispatch(tc, spec.name, kwargs)
        except ToolError as exc:
            raise McpToolError(f"{exc.code}: {exc.message}") from exc
        if isinstance(result, ImageResult):
            return [
                ImageContent(type="image", data=result.data_b64, mime_type=result.mime),
                TextContent(type="text", text=result.text),
            ]
        return [TextContent(type="text", text=result_text(result))]

    params: list[inspect.Parameter] = []
    annotations: dict[str, Any] = {}
    for field_name, info in spec.input_model.model_fields.items():
        # Python parameter names must be identifiers; a JSON alias such as "from"
        # travels as a pydantic alias so the published schema keeps the public name.
        extra: dict[str, Any] = {}
        if info.alias:
            extra["alias"] = info.alias
        if info.description:
            extra["description"] = info.description
        annotation: Any = info.annotation
        if extra:
            annotation = Annotated[annotation, Field(**extra)]
        default = (
            inspect.Parameter.empty
            if info.is_required()
            else info.get_default(call_default_factory=True)
        )
        params.append(
            inspect.Parameter(
                field_name, inspect.Parameter.KEYWORD_ONLY, annotation=annotation, default=default
            )
        )
        annotations[field_name] = annotation
    annotations["return"] = list[TextContent | ImageContent]
    call.__signature__ = inspect.Signature(params, return_annotation=annotations["return"])  # type: ignore[attr-defined]
    call.__annotations__ = annotations
    call.__name__ = spec.name
    call.__doc__ = spec.description
    return call


def build_server(
    resolve_context: Callable[[], ToolContext],
    *,
    token_verifier: Any | None = None,
    auth: AuthSettings | None = None,
) -> MCPServer:
    """An MCP server exposing every registry tool; ``resolve_context`` runs per call."""
    server = MCPServer(
        SERVER_NAME,
        instructions=INSTRUCTIONS,
        token_verifier=token_verifier,
        auth=auth,
    )
    for spec in TOOLS:
        server.add_tool(
            _wrapper_for(spec, resolve_context),
            name=spec.name,
            description=spec.description,
            structured_output=False,
        )
    return server


def make_tool_context(
    session_factory: sessionmaker[Session],
    ctx: TenantContext,
    config: ServerConfig,
    *,
    blobs: BlobStorage | None,
    transcription: TranscriptionPort | None,
    run_id: str | None = None,
) -> ToolContext:
    def factory(c: TenantContext) -> UnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory, c)

    return ToolContext(
        uow_factory=factory,
        ctx=ctx,
        config=config,
        blobs=blobs,
        transcription=transcription,
        run_id=run_id,
    )


# ── stdio ───────────────────────────────────────────────────────────────────


def stdio_context(tenant_slug: str, config: ServerConfig) -> ToolContext:
    """Trusted local process: the tenant comes from the flag, all scopes are granted."""
    from victus.infrastructure.db.engine import make_engine, make_session_factory
    from victus.infrastructure.storage.fs_blob import FsBlobStorage

    engine = make_engine(config.database.url, echo=config.database.echo)
    session_factory = make_session_factory(engine)
    probe = SqlAlchemyUnitOfWork(session_factory, TenantContext(tenant_id="-"))
    with probe:
        tenant = probe.tenants.get_by_slug(tenant_slug)
        if tenant is None:
            raise SystemExit(f"victus mcp: tenant '{tenant_slug}' not found")
        tenant_id = tenant.id
    ctx = TenantContext(tenant_id=tenant_id, token_id=f"stdio:{tenant_slug}", scopes=ALL_SCOPES)
    transcription = _transcription_from(config)
    return make_tool_context(
        session_factory,
        ctx,
        config,
        blobs=FsBlobStorage(config.storage.path),
        transcription=transcription,
    )


def _transcription_from(config: ServerConfig) -> TranscriptionPort | None:
    key = config.providers.openai_api_key
    if key is None:
        return None
    from victus.infrastructure.transcription.openai_transcribe import OpenAITranscription

    return OpenAITranscription(
        key.get_secret_value(),
        model=config.transcription.model,
        max_file_mb=config.transcription.max_file_mb,
        ffmpeg_path=config.transcription.ffmpeg_path,
    )


def serve_stdio(tenant_slug: str, config: ServerConfig) -> None:
    """Blocking: serve the tools over stdio for the given tenant."""
    tool_ctx = stdio_context(tenant_slug, config)
    server = build_server(lambda: tool_ctx)
    server.run("stdio")


# ── HTTP: token verifier, CIDR allow-list, rate limit ───────────────────────


class VictusAccessToken(AccessToken):
    """The SDK's access token plus the resolved tenant context."""

    tenant_id: str
    user_id: str | None = None
    token_id: str | None = None

    def tenant_context(self) -> TenantContext:
        return TenantContext(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            token_id=self.token_id,
            scopes=frozenset(self.scopes),
        )


class ApiTokenVerifier:
    """Resolve ``vct_…`` bearer tokens through the same lookup the REST API uses."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def verify_token(self, token: str) -> AccessToken | None:
        session = self._session_factory()
        try:
            ctx = ResolveToken(SqlAuthLookup(session)).execute(token)
        finally:
            session.close()
        if ctx is None:
            return None
        return VictusAccessToken(
            token=token,
            client_id=ctx.token_id or "token",
            scopes=sorted(ctx.scopes),
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            token_id=ctx.token_id,
        )


def current_http_context() -> TenantContext:
    token = get_access_token()
    if not isinstance(token, VictusAccessToken):
        raise ToolError("unauthenticated", "no bearer token in this request")
    return token.tenant_context()


_PRIVATE_NETS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
)


def _is_private(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in _PRIVATE_NETS)


def client_ip(scope: Scope) -> str | None:
    """Peer address, or the first X-Forwarded-For hop when the peer is a private proxy."""
    client = scope.get("client")
    peer: str | None = str(client[0]) if client else None
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    forwarded = headers.get("x-forwarded-for")
    if forwarded and (peer is None or _is_private(peer)):
        return str(forwarded.split(",")[0].strip())
    return peer


class RateLimiter:
    """Sliding one-minute window per key; in-process, good enough for one API instance."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        ts = now if now is not None else time.monotonic()
        with self._lock:
            window = self._hits.setdefault(key, deque())
            while window and ts - window[0] > 60.0:
                window.popleft()
            if len(window) >= self.per_minute:
                return False
            window.append(ts)
            return True


class NetworkGuard:
    """ASGI middleware: CIDR allow-list first, then per-token rate limit."""

    def __init__(self, app: ASGIApp, allowed_cidrs: list[str], limiter: RateLimiter) -> None:
        self.app = app
        self.networks = [ipaddress.ip_network(c, strict=False) for c in allowed_cidrs]
        self.limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        ip = client_ip(scope)
        if self.networks and not self._allowed(ip):
            log.warning("mcp: rejected client %s (outside allowed_cidrs)", ip)
            await JSONResponse(
                {"error": "forbidden", "error_description": "client address not allowed"},
                status_code=403,
            )(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        key = hashlib.sha256(auth.encode()).hexdigest()[:16] if auth else f"ip:{ip}"
        if not self.limiter.allow(key):
            await JSONResponse(
                {"error": "rate_limited", "error_description": "too many requests"},
                status_code=429,
                headers={"Retry-After": "60"},
            )(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _allowed(self, ip: str | None) -> bool:
        if ip is None:
            return False
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr in net for net in self.networks)


def mount_http(app: FastAPI, cfg: ServerConfig) -> None:
    """Mount the Streamable HTTP transport at ``/mcp`` inside the API process.

    Reads the session factory, blob storage and transcription adapter from
    ``app.state`` (set by the API factory) and chains the MCP session manager
    into the application's lifespan.
    """
    session_factory: sessionmaker[Session] = app.state.session_factory
    blobs: BlobStorage | None = getattr(app.state, "blobs", None)
    transcription: TranscriptionPort | None = getattr(app.state, "transcription", None)

    def resolve() -> ToolContext:
        ctx = current_http_context()
        return make_tool_context(
            session_factory, ctx, cfg, blobs=blobs, transcription=transcription
        )

    origin = cfg.auth.origin or f"http://{cfg.auth.rp_id or 'localhost'}"
    auth = AuthSettings(
        issuer_url=AnyHttpUrl(origin),  # tokens are issued by Victus itself
        resource_server_url=AnyHttpUrl(f"{origin.rstrip('/')}/mcp"),
        validate_token_resource=False,
        required_scopes=[],
    )
    server = build_server(resolve, token_verifier=ApiTokenVerifier(session_factory), auth=auth)
    mcp_app = server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        # The reverse proxy, the bearer token and the CIDR list protect this route;
        # the SDK's Host-header check would reject every proxied request.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    guarded = NetworkGuard(
        mcp_app, cfg.mcp.allowed_cidrs, RateLimiter(cfg.mcp.rate_limit_per_minute)
    )
    app.mount("/mcp", guarded, name="mcp")

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[Any]:
        async with original_lifespan(application) as state, server.session_manager.run():
            yield state

    app.router.lifespan_context = lifespan
    app.state.mcp_server = server


# ── helpers for tests and callers ───────────────────────────────────────────


def decode_image(content: ImageContent) -> bytes:
    return base64.b64decode(content.data)


def parse_text(content: TextContent) -> Any:
    with contextlib.suppress(json.JSONDecodeError):
        return json.loads(content.text)
    return content.text


def build_http_request_headers(token: str) -> dict[str, str]:
    """Headers a Streamable-HTTP client sends (bearer + JSON accept)."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }


__all__ = [
    "ApiTokenVerifier",
    "NetworkGuard",
    "RateLimiter",
    "VictusAccessToken",
    "build_http_request_headers",
    "build_server",
    "client_ip",
    "current_http_context",
    "decode_image",
    "make_tool_context",
    "mount_http",
    "parse_text",
    "serve_stdio",
    "stdio_context",
]
