#!/usr/bin/env bash
# Backup de la base (formato custom de pg_dump). Lo corre cron todos los días; guarda los últimos 14.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p deploy/backups
envget() { grep -E "^$1=" .env | tail -1 | cut -d= -f2-; }
POSTGRES_USER=$(envget POSTGRES_USER); POSTGRES_DB=$(envget POSTGRES_DB)
OUT="deploy/backups/land-$(date +%Y%m%d-%H%M).dump"
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$OUT"
ls -1t deploy/backups/land-*.dump | tail -n +15 | xargs -r rm --
echo "$(date -Is) backup ok: $OUT ($(du -h "$OUT" | cut -f1))"
