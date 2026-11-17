#!/usr/bin/env bash
# UNA SOLA VEZ, desde tu Mac: copia tu base local (fuentes, avisos, historial, destacados) al servidor.
#   deploy/migrate-db.sh root@IP_DEL_SERVIDOR
# Requiere: el Postgres local levantado (docker compose up -d postgres) y deploy/server-setup.sh ya corrido.
# REEMPLAZA la base del servidor.
set -euo pipefail
HOST="${1:?uso: deploy/migrate-db.sh usuario@servidor}"
cd "$(dirname "$0")/.."
envget() { grep -E "^$1=" .env | tail -1 | cut -d= -f2-; }
POSTGRES_USER=$(envget POSTGRES_USER); POSTGRES_DB=$(envget POSTGRES_DB)
DUMP="$(mktemp -t land).dump"
echo "==> Dump local"
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-patagonia}" -d "${POSTGRES_DB:-patagonia_land}" -Fc > "$DUMP"
echo "    $(du -h "$DUMP" | cut -f1)"
echo "==> Copia al servidor"
scp "$DUMP" "$HOST:/tmp/land.dump"
echo "==> Restauración en el servidor (con la app detenida)"
ssh "$HOST" 'bash -s' <<'REMOTE'
set -euo pipefail
cd /opt/land
envget() { grep -E "^$1=" .env | tail -1 | cut -d= -f2-; }
POSTGRES_USER=$(envget POSTGRES_USER); POSTGRES_DB=$(envget POSTGRES_DB)
C="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
$C stop api scraper-worker scheduler dashboard caddy 2>/dev/null || true
$C up -d postgres
until $C exec -T postgres pg_isready -U "$POSTGRES_USER" -d postgres >/dev/null 2>&1; do sleep 2; done
$C exec -T postgres dropdb -U "$POSTGRES_USER" --if-exists --force "$POSTGRES_DB"
$C exec -T postgres createdb -U "$POSTGRES_USER" "$POSTGRES_DB"
$C exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges < /tmp/land.dump
rm -f /tmp/land.dump
echo "Base restaurada. Levantando todo…"
./deploy/up.sh
REMOTE
rm -f "$DUMP"
