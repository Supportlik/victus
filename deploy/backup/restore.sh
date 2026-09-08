#!/bin/sh
# Victus — restore a backup archive (wrapper around `victus backup restore`).
#
# Usage:
#   deploy/backup/restore.sh ARCHIVE.zip [--tenant NEW-SLUG] [--dry-run] [--yes]
#
# ARCHIVE.zip must live inside the backup directory that is bind-mounted into
# the `backup` service (BACKUP_DIR, default ./backups) — give the file name or
# the full host path.
#
# What happens: the archive is verified (manifest hashes), restored into a
# temporary database, row counts are compared with the manifest, and only then
# is it swapped into the live database. Running services (api, worker) are
# stopped before and started after the restore. Without --yes you are asked to
# confirm; --dry-run performs everything except the final swap.
# Exit codes: 0 ok · 1 usage · 2 aborted by user · 3 restore failed
#
# Install: chmod +x deploy/backup/*.sh  (LF line endings only)

set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY_DIR=$(CDPATH= cd -- "$HERE/.." && pwd)
COMPOSE="docker compose -f $DEPLOY_DIR/docker-compose.yml"
[ -f "$DEPLOY_DIR/.env" ] && COMPOSE="$COMPOSE --env-file $DEPLOY_DIR/.env"

log() { printf '%s [restore] %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$*"; }
usage() { sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

[ $# -ge 1 ] || usage
ARCHIVE="$1"; shift
EXTRA=""
YES=0
DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --tenant) [ $# -ge 2 ] || usage; EXTRA="$EXTRA --tenant $2"; shift 2 ;;
    --dry-run) DRY=1; EXTRA="$EXTRA --dry-run"; shift ;;
    --yes|-y) YES=1; shift ;;
    -h|--help) usage ;;
    *) log "unknown argument: $1"; usage ;;
  esac
done

# Only the file name matters inside the container (mounted at /backups).
NAME=$(basename -- "$ARCHIVE")

if [ "$YES" -ne 1 ] && [ "$DRY" -ne 1 ]; then
  printf 'This will REPLACE the live Victus data with %s. Continue? [yes/NO] ' "$NAME"
  read -r answer
  [ "$answer" = "yes" ] || { log "aborted"; exit 2; }
fi

if [ "$DRY" -ne 1 ]; then
  log "stopping api and worker"
  $COMPOSE stop api worker backup >/dev/null
fi

log "starting: victus backup restore /backups/$NAME$EXTRA"
# shellcheck disable=SC2086
if $COMPOSE run --rm --no-deps backup backup restore "/backups/$NAME" $EXTRA; then
  RC=0
  log "restore finished"
else
  RC=3
  log "restore FAILED — live data untouched (swap happens only after verification)"
fi

if [ "$DRY" -ne 1 ]; then
  log "starting api, worker, backup"
  $COMPOSE up -d api worker backup >/dev/null
fi
exit $RC
