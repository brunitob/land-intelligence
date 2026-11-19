#!/usr/bin/env bash
# Actualiza el código y (re)levanta todo en el servidor. Las migraciones de la base corren solas al iniciar la API.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "Falta .env (correr deploy/server-setup.sh)"; exit 1; }
git pull --ff-only
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --remove-orphans
docker image prune -f >/dev/null
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}'
echo "Sitio: https://$(grep '^SITE_ADDRESS=' .env | cut -d= -f2)"
