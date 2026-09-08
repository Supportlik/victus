#!/bin/sh
# Victus — create a backup (wrapper around `victus backup create`).
#
# Usage:
#   deploy/backup/backup.sh [--tenant SLUG | --all] [--target DIR] [--min-free-mb N]
#
# Defaults: --all, target = BACKUP_DIR from deploy/.env (falls back to
# ./backups), refuse to run with less than 2048 MB free.
# Exit codes: 0 ok · 1 usage · 2 not enough free space · 3 backup failed
#
# Cron example (daily 03:15; the compose `backup` service already does this via
# `victus backup schedule --daemon` — use cron only if you run without it):
#   15 3 * * * cd /opt/victus && ./deploy/backup/backup.sh --all >> /var/log/victus-backup.log 2>&1
#
# Install: chmod +x deploy/backup/*.sh  (files must keep LF line endings)

set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY_DIR=$(CDPATH= cd -- "$HERE/.." && pwd)
COMPOSE="docker compose -f $DEPLOY_DIR/docker-compose.yml"
[ -f "$DEPLOY_DIR/.env" ] && COMPOSE="$COMPOSE --env-file $DEPLOY_DIR/.env"

SCOPE="--all"
TARGET=""
MIN_FREE_MB=2048

log() { printf '%s [backup] %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$*"; }
usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --tenant) [ $# -ge 2 ] || usage; SCOPE="--tenant $2"; shift 2 ;;
    --all) SCOPE="--all"; shift ;;
    --target) [ $# -ge 2 ] || usage; TARGET="$2"; shift 2 ;;
    --min-free-mb) [ $# -ge 2 ] || usage; MIN_FREE_MB="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) log "unknown argument: $1"; usage ;;
  esac
done

# Resolve the host backup directory (for the free-space check only; inside the
# container the target is always /backups).
if [ -z "$TARGET" ]; then
  if [ -f "$DEPLOY_DIR/.env" ]; then
    TARGET=$(sed -n 's/^BACKUP_DIR=\([^#]*\).*/\1/p' "$DEPLOY_DIR/.env" | tr -d ' ')
  fi
  TARGET=${TARGET:-$DEPLOY_DIR/backups}
fi

if [ -d "$TARGET" ]; then
  FREE_MB=$(df -Pm "$TARGET" | awk 'NR==2 {print $4}')
  if [ "${FREE_MB:-0}" -lt "$MIN_FREE_MB" ]; then
    log "only ${FREE_MB} MB free in $TARGET (minimum $MIN_FREE_MB MB) — aborting"
    exit 2
  fi
  log "target $TARGET, ${FREE_MB} MB free"
else
  log "warning: $TARGET does not exist on this host (fine if Docker runs elsewhere)"
fi

log "starting: victus backup create $SCOPE"
# shellcheck disable=SC2086
if $COMPOSE run --rm --no-deps backup backup create $SCOPE --target /backups; then
  log "done"
  exit 0
else
  log "backup FAILED"
  exit 3
fi
