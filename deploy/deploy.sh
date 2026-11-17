#!/usr/bin/env bash
# Desde tu Mac: publica lo que esté pusheado en GitHub (main) en el servidor.
#   deploy/deploy.sh root@IP_DEL_SERVIDOR
set -euo pipefail
HOST="${1:?uso: deploy/deploy.sh usuario@servidor}"
if [ -n "$(git status --porcelain)" ] || [ "$(git rev-parse HEAD)" != "$(git rev-parse @{u} 2>/dev/null)" ]; then
  echo "Ojo: hay cambios sin commitear o sin pushear; el servidor despliega lo que está en GitHub."
fi
ssh "$HOST" /opt/land/deploy/up.sh
