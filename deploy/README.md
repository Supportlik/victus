# deploy/

Everything needed to run Victus with Docker Compose. Detailed procedures live in
[`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md), [`docs/BACKUP.md`](../docs/BACKUP.md)
and [`docs/OPERATIONS.md`](../docs/OPERATIONS.md).

| File | Purpose |
|---|---|
| `docker-compose.yml` | The stack: `api`, `web`, `worker`, `backup` (default) plus profiles `postgres`, `caddy`, `dev` |
| `docker-compose.override.example.yml` | Local development override (ports on all interfaces, bind-mounted sources, reload) |
| `.env.example` | Every environment variable, commented. Copy to `.env` (never committed) |
| `Dockerfile.api` | API / worker / backup / MCP image (uv, Python 3.12, ffmpeg, non-root) |
| `Dockerfile.web` | Angular production build served by unprivileged nginx |
| `nginx.conf` | SPA fallback, `/api` and `/mcp` proxy (streaming-safe), security headers |
| `Dockerfile.caddy` | Caddy with `caddy-dns/cloudflare` for the standalone profile |
| `Caddyfile` | Standalone TLS termination (profile `caddy`) |
| `Caddyfile.snippet` | Vhost block for a central Caddy instance on the host |
| `backup/backup.sh` `restore.sh` `verify.sh` | Shell wrappers for emergencies — no Python knowledge needed |
| `ports.md.snippet` | Rows for a homelab port registry |

## Three ways to run

**1. Home server behind a central reverse proxy (production)**

```sh
cp deploy/.env.example deploy/.env      # set VICTUS_DOMAIN, RP_ID/ORIGIN, keys, BACKUP_DIR
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d
# add deploy/Caddyfile.snippet to your central Caddyfile, reload Caddy
# add deploy/ports.md.snippet rows to your port registry
```

`api` listens on `127.0.0.1:8090`, `web` on `127.0.0.1:8091`; the proxy forwards
your domain → `localhost:8091`. `/mcp` is reachable from the VPN range only.

The `worker` service needs `VICTUS_PROVIDERS__ANTHROPIC_API_KEY` to draft days itself; without it, connect your
own Claude over MCP (`docs/MCP.md`). `VICTUS_PROVIDERS__OPENAI_API_KEY` enables voice-note transcription.
`docker compose ps worker` must show *healthy* — the worker touches a heartbeat file on every tick.

**2. Standalone with bundled Caddy**

```sh
docker compose -f deploy/docker-compose.yml --env-file deploy/.env --profile caddy up -d
```

Needs `CF_API_TOKEN` (Cloudflare, scope Zone → DNS → Edit) and ports 80/443 free.
The DNS-01 challenge works even when the host is not reachable from the internet
(e.g. behind DS-Lite/CGNAT with an A record pointing at a VPN address).

**3. Local development**

```sh
cp deploy/docker-compose.override.example.yml deploy/docker-compose.override.yml
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.override.yml up api web
```

Or without Docker: `uv run victus serve --reload` and `cd web && npm start`.

## Passkeys — read before the first login

`VICTUS_AUTH__RP_ID` must be final before the first passkey is registered.
Changing it invalidates every passkey. WebAuthn requires HTTPS (only
`http://localhost` is exempt) — `http://<LAN-IP>` from a phone will not show a
passkey prompt. Register at least two passkeys and keep the recovery code.

## Backups

The `backup` service runs `victus backup schedule --daemon` (default 03:00,
retention 7 daily / 8 weekly / 12 monthly) into `BACKUP_DIR`. Manual:

```sh
deploy/backup/backup.sh --all
deploy/backup/verify.sh --latest
deploy/backup/restore.sh victus-demo-2026-09-08T030000Z.zip --dry-run
```

Scripts must keep LF line endings (`.gitattributes` enforces `eol=lf` for `*.sh`).
