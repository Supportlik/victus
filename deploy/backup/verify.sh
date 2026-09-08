#!/bin/sh
# Victus — verify a backup archive without touching live data.
#
# Usage:
#   deploy/backup/verify.sh ARCHIVE.zip            verify one archive
#   deploy/backup/verify.sh --latest               verify the newest archive in BACKUP_DIR
#
# Verification = manifest hash check + restore into a throw-away database +
# row-count comparison. Exit codes: 0 ok · 1 usage · 3 verification failed
#
# Cron example (weekly, Sunday 04:00):
#   0 4 * * 0 cd /opt/victus && ./deploy/backup/verify.sh --latest >> /var/log/victus-backup.log 2>&1
#
# Install: chmod +x deploy/backup/*.sh  (LF line endings only)

set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY_DIR=$(CDPATH= cd -- "$HERE/.." && pwd)
COMPOSE="docker compose -f $DEPLOY_DIR/docker-compose.yml"
[ -f "$DEPLOY_DIR/.env" ] && COMPOSE="$COMPOSE --env-file $DEPLOY_DIR/.env"

log() { printf '%s [verify] %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$*"; }
usage() { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

[ $# -ge 1 ] || usage
case "$1" in
  --latest) TARGET_ARG="--latest" ;;
  -h|--help) usage ;;
  *) TARGET_ARG="/backups/$(basename -- "$1")" ;;
esac

log "starting: victus backup verify $TARGET_ARG"
if $COMPOSE run --rm --no-deps backup backup verify "$TARGET_ARG"; then
  log "archive OK"
  exit 0
else
  log "verification FAILED"
  exit 3
fi
