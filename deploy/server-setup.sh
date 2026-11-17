#!/usr/bin/env bash
# Preparación ÚNICA de un servidor Ubuntu 24.04 recién creado (Hetzner). Correr como root en el servidor:
#   curl -fsSL https://raw.githubusercontent.com/brunitob/land-intelligence/main/deploy/server-setup.sh -o setup.sh
#   bash setup.sh
# Instala Docker (repo oficial), firewall, actualizaciones automáticas, swap, clona el repo en /opt/land,
# genera /opt/land/.env con contraseñas aleatorias y programa el backup diario. Idempotente.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/brunitob/land-intelligence.git}"
APP_DIR=/opt/land

[ "$(id -u)" = 0 ] || { echo "Correr como root"; exit 1; }
export DEBIAN_FRONTEND=noninteractive

echo "==> Paquetes base"
apt-get update -q
apt-get upgrade -yq
apt-get install -yq ca-certificates curl git ufw unattended-upgrades openssl

echo "==> Docker (repositorio oficial)"
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

echo "==> Firewall: solo SSH, HTTP y HTTPS"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

echo "==> Actualizaciones de seguridad automáticas"
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> Swap de 2 GB (colchón para builds)"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> Código en $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then git -C "$APP_DIR" pull --ff-only; else git clone "$REPO_URL" "$APP_DIR"; fi

echo "==> .env de producción"
if [ ! -f "$APP_DIR/.env" ]; then
  IP=$(curl -fsS https://api.ipify.org || hostname -I | awk '{print $1}')
  MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
  if [ "$MEM_MB" -lt 3000 ]; then WORKERS=1; elif [ "$MEM_MB" -lt 7000 ]; then WORKERS=2; else WORKERS=4; fi
  sed -e "s|^SITE_ADDRESS=.*|SITE_ADDRESS=${IP//./-}.sslip.io|" \
      -e "s|^WORKERS=.*|WORKERS=${WORKERS}|" \
      -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 24)|" \
      -e "s|^API_TOKEN=.*|API_TOKEN=$(openssl rand -hex 32)|" \
      "$APP_DIR/deploy/env.prod.example" > "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
  echo "    Creado $APP_DIR/.env (SITE_ADDRESS=${IP//./-}.sslip.io, WORKERS=${WORKERS} para ${MEM_MB} MB de RAM)."
  echo "    Completá ANTHROPIC_API_KEY, ORS_API_KEY y USER_AGENT."
else
  echo "    Ya existe $APP_DIR/.env: no se toca."
fi

echo "==> Backup diario de la base (03:30, guarda 14 días)"
chmod +x "$APP_DIR"/deploy/*.sh
cat > /etc/cron.d/land-backup <<CRON
30 3 * * * root $APP_DIR/deploy/backup.sh >> /var/log/land-backup.log 2>&1
CRON

cat <<NEXT

Listo. Próximos pasos (en el servidor):
  1) nano $APP_DIR/.env              # claves de Anthropic/ORS y contacto en USER_AGENT
  2) $APP_DIR/deploy/set-password.sh # usuario y contraseña del dashboard
  3) $APP_DIR/deploy/up.sh           # construir y levantar todo
NEXT
