# Security policy

Victus is meant to be run on your own server, by you, for your own household. It holds a food
diary, weights and body measurements — data that is nobody else's business — behind passkeys and
scoped tokens. If any of that can be got at without the right credentials, that is a bug worth
reporting, and it will be treated as one.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting on this repository — **Security → Report a
vulnerability** — which is enabled and keeps the report between you and the maintainer. If you
would rather not use GitHub, write to **michael@bortlik.io**. Either way, please do not open a
public issue for something exploitable.

Say what you found, what an attacker can reach with it, and how to reproduce it — a request, a
log line or a short script says more than a description. If you would rather encrypt it, ask for
a key in a first message with no details in it.

What to expect: an acknowledgement within a few days, an assessment of whether it is a
vulnerability and how severe, and a fix released as a patch version with the finding described in
[`CHANGELOG.md`](CHANGELOG.md). You will be credited by whatever name you ask for, or not at all
if you prefer. This is a one-maintainer project, not a company with a queue: there is no bounty
and no service-level promise, only the intention to answer and to fix.

## What is in scope

The application as this repository ships it:

- authentication and session handling (WebAuthn, recovery codes, API tokens and their scopes),
- tenant isolation — every row belongs to one tenant, and a request must never read another's,
- the REST API under `/api/v1`, the MCP server, and the CLI,
- the agent path: what a capture, a transcript, or a model's answer can make the server do,
- the Docker Compose stack and the defaults in `deploy/`.

## What is not

- A deployment that changes the shipped configuration — an origin that does not match the
  WebAuthn relying party, `/mcp` exposed to the internet instead of a private network, a
  reverse proxy that terminates TLS and forwards nothing about it.
- Findings that depend on already having the server's shell, its database file, or a valid token
  with the scope in question.
- Reports from a scanner with no reachable path attached.
- The third-party services an installation may be pointed at (a speech model, a model provider).
  Report those to whoever runs them.

## Supported versions

The latest released version is the one that gets fixes. Releases are tagged and signed; the tags
and [`CHANGELOG.md`](CHANGELOG.md) are the record of what changed. Anything older is history —
upgrade before reporting.
