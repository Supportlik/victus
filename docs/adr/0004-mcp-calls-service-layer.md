# ADR 0004 — The MCP server calls the service layer, not the REST API

**Status:** accepted · **Date:** 2026-09-08

## Context

Victus exposes MCP tools for agents. Two implementations were possible: (a) the MCP server is an HTTP client of the
Victus REST API, or (b) the MCP server is an in-process adapter that invokes use cases directly.

## Decision

Option (b). `mcp/server.py` builds a `TenantContext` from the transport (stdio: `--tenant` flag; HTTP: bearer token
with scopes) and calls the same use cases the routers call. The stdio transport runs as `victus mcp --tenant <slug>`;
the Streamable HTTP transport is mounted at `/mcp` inside the API process.

## Rationale

- Authorisation already lives in the use cases (`TenantContext`, scopes). Going through HTTP would add a second
  authentication hop (the MCP server authenticating to its own API) without adding a check.
- No double serialisation (domain → Pydantic → JSON → Pydantic → tool result).
- Tests for tools are use-case tests with a thin mapping layer; no running server needed.
- Tool errors map from typed domain errors, exactly like problem+json does for HTTP.

## Consequences

- MCP and REST share the process and the database session factory; the MCP layer must respect the one-transaction-per-
  use-case rule and never bypass repositories.
- A remote-only deployment of the MCP server (different host than the API) is not supported; the HTTP transport is the
  remote option.
- Any new capability must be a use case first, then exposed to both REST and MCP.
