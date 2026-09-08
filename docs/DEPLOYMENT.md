# Deployment

Victus ships as one Docker Compose stack (`deploy/docker-compose.yml`). The reference deployment is a Linux home
server behind a reverse proxy, reachable only over a VPN (Tailscale is used in the examples; any VPN works).

## Prerequisites

| Item | Value / requirement |
|---|---|
| Host | Linux with Docker ≥ 27 and Compose v2 or newer; ≥ 2 GB RAM free |
| Storage | fast disk for `victus_data` (SQLite, WAL) and `victus_blobs`; a large disk for backups (bind-mounted) |
| Network | HTTPS is **mandatory** for passkeys. Public IPv4 is not required; a VPN plus DNS-01 certificates is enough |
| DNS | `victus.example.com` → A record to the server's VPN address; if the DNS provider offers proxying (e.g. Cloudflare), keep it **off** for VPN addresses |
| Certificates | Caddy with a DNS-01 plugin (`caddy-dns/cloudflare` in the examples), wildcard or per host |
| Secrets | `deploy/.env` from `deploy/.env.example`; never committed |

## Stack

| Service | Image | Command | Ports | Profile |
|---|---|---|---|---|
| `api` | `ghcr.io/supportlik/victus-api` | `alembic upgrade head && victus serve` | `127.0.0.1:8090` | default |
| `web` | `ghcr.io/supportlik/victus-web` | nginx serving the Angular build, proxies `/api` and `/mcp` to `api` | via `WEB_PORT` | default |
| `worker` | `victus-api` | `victus worker` (agent cron, scale sync, backup schedule) | – | default |
| `backup` | `victus-api` | `victus backup schedule --daemon`; one-shot via `docker compose run --rm backup …` | – | default |
| `postgres` | `postgres:17-alpine` | – | internal | `postgres` |
| `caddy` | `deploy/Dockerfile.caddy` | standalone TLS proxy for hosts without a central Caddy | 443 | `caddy` |
| `dev` overrides | `docker-compose.override.example.yml` | hot reload, bind mounts | 8090, 4200 | `dev` |

Volumes: `victus_data`, `victus_blobs`, `victus_pg` (postgres profile). Backups are a **bind mount** to the backup
disk, never a named volume.

### `.env` (see `deploy/.env.example`)

| Variable | Example | Note |
|---|---|---|
| `VICTUS_SERVER__BASE_URL` | `https://victus.example.com` | |
| `VICTUS_AUTH__RP_ID` | `victus.example.com` | **decide before the first passkey** |
| `VICTUS_AUTH__ORIGIN` | `https://victus.example.com` | |
| `VICTUS_DATABASE__URL` | `sqlite:////data/victus.db` | or `postgresql+psycopg://…` with the `postgres` profile |
| `VICTUS_PROVIDERS__OPENAI_API_KEY` | `sk-…` | transcription |
| `VICTUS_PROVIDERS__ANTHROPIC_API_KEY` | `sk-ant-…` | only for the in-house worker |
| `VICTUS_MCP__HTTP_ENABLED` | `true` | for external agents |
| `BACKUP_DIR` | `/mnt/backup/victus` | bind-mount source |
| `WEB_PORT` | `8090` | host port bound to `127.0.0.1` |
| `VICTUS_IMAGE_TAG` | `latest` | pin to `vX.Y.Z` in production |
| `CF_API_TOKEN` | – | only with the `caddy` profile (zone DNS edit scope) |

### Caddy snippet (central Caddy)

```caddy
victus.example.com {
    tls {
        dns cloudflare {env.CF_API_TOKEN}
    }
    @vpn remote_ip 100.64.0.0/10      # your VPN range
    handle @vpn {
        reverse_proxy localhost:8090
    }
    respond 403
}
```

## The four passkey preconditions

1. **HTTPS is mandatory.** WebAuthn works over `https://` only (exception: `http://localhost`). `http://<LAN-IP>` from a
   phone shows no passkey prompt. There is no "test in the LAN first".
2. **Fix `RP_ID` before the first passkey.** Changing it invalidates every passkey. Victus pins the value at the first
   registration and refuses to start with a different one. Do **not** start on a VPN-provided hostname or DynDNS and
   move to your own domain later.
3. **Plan recovery.** Register at least two passkeys (phone + laptop or hardware key) and store the recovery code.
4. **Transport.** DNS-01 certificates need no inbound port. Access via VPN (nothing public) or a tunnel service with
   an access layer in front. Port forwarding is often impossible behind carrier-grade NAT.

## First start

```bash
mkdir -p /srv/victus && cd /srv/victus
cp /path/to/victus/deploy/docker-compose.yml .
cp /path/to/victus/deploy/.env.example .env && $EDITOR .env      # set RP_ID, ORIGIN, keys, BACKUP_DIR
docker compose pull
docker compose up -d
docker compose logs -f api                                        # wait for "migrations applied", "listening"
docker compose exec api victus tenant create alice --name "Alice"          # owner tenant
docker compose exec api victus user invite --tenant alice --email alice@example.com   # prints invitation URL
# open the URL on the phone → register passkey 1
# open the URL again on the laptop → register passkey 2 (Settings → Passkeys)
# Settings → Recovery code → store it offline
docker compose exec api victus backup create --all && docker compose exec api victus backup verify --latest
curl -s https://victus.example.com/api/v1/health | jq              # backup_age_hours < 30
```

## Update

```bash
docker compose pull
docker compose exec api victus backup create --all           # always before a schema change
docker compose up -d                                         # api runs alembic upgrade head on start
docker compose logs --since 5m api | grep -i alembic
```

Rollback: `docker compose exec api alembic downgrade -1`, then pin the previous image tag in `.env`
(`VICTUS_IMAGE_TAG`) and `up -d`. See [OPERATIONS.md](OPERATIONS.md).

## Local development

```bash
cp deploy/.env.example deploy/.env             # RP_ID=localhost, ORIGIN=http://localhost:4200
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.override.example.yml --profile dev up
# API with reload on :8090, Angular dev server on :4200 (passkeys work on http://localhost)
```

Without Docker: `uv sync && uv run victus serve --reload` and `cd web && npm start`.

## PostgreSQL profile

```bash
docker compose --profile postgres up -d
# .env: VICTUS_DATABASE__URL=postgresql+psycopg://victus:${PG_PASSWORD}@postgres:5432/victus
```

Migration from SQLite: `victus backup create --all` on SQLite → switch URL → `victus backup restore <zip>`.
The backup format is dialect-neutral by design ([ADR 0008](adr/0008-backup-format-jsonl.md)).
