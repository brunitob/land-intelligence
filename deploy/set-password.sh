#!/usr/bin/env bash
# Usuario y contraseña del sitio (basic auth de Caddy). Correr en el servidor; se puede repetir.
set -euo pipefail
cd "$(dirname "$0")/.."
read -rp "Usuario: " USER_NAME
read -rsp "Contraseña (mín. 12 caracteres): " PASS; echo
[ ${#PASS} -ge 12 ] || { echo "La contraseña debe tener al menos 12 caracteres"; exit 1; }
HASH=$(docker run --rm caddy:2.8-alpine caddy hash-password --plaintext "$PASS")
printf 'basic_auth {\n\t%s %s\n}\n' "$USER_NAME" "$HASH" > deploy/users.caddy
chmod 600 deploy/users.caddy
echo "Guardado. Si el sitio ya está arriba: docker compose -f docker-compose.yml -f docker-compose.prod.yml restart web"
