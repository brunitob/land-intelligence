#!/usr/bin/env bash
# Crea un usuario de la app o le cambia la contraseña (cierra sus sesiones abiertas). Correr en el servidor:
#   /opt/land/deploy/set-password.sh            # pregunta el usuario
#   /opt/land/deploy/set-password.sh bruno
# Otros: docker compose ... exec api python -m patagonia_land.auth list | delete <u> | logout-all <u>
set -euo pipefail
cd "$(dirname "$0")/.."
USER_NAME="${1:-}"
[ -n "$USER_NAME" ] || read -rp "Usuario: " USER_NAME
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api python -m patagonia_land.auth set-password "$USER_NAME"
