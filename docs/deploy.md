# Deploy en Hetzner (VPS con Docker)

Todo corre igual que en local (`docker compose`). El servicio `web` (Caddy) es el único público: HTTPS
automático, sirve la app web (React, `frontend/`) y pasa `/api/*` a la API, que pide login. La base y la API no quedan expuestas a internet; solo `web` escucha en los puertos 80/443.

## 1. Crear el servidor (en la consola de Hetzner)

1. Cuenta en <https://console.hetzner.cloud> → **New project** → **Add server**.
2. **Location:** cualquiera (Ashburn/Hillsboro para menos latencia desde Argentina; Europa también sirve).
3. **Image:** Ubuntu 24.04.
4. **Type:** lo más barato que funciona es **2 GB de RAM** (p. ej. **CPX12**, 1 vCPU): corre con 1 worker y el
   crawl diario tarda ~2–3 h (de madrugada). Con 4 GB (CPX22) usa 2 workers; con 8 GB, 4. El setup elige
   `WORKERS` según la RAM. Si "Cost-Optimized x86" está disponible en alguna ubicación, suele ser más barato.
   Nunca 1 GB (CPX02): no entran Postgres, la API y el worker. Evitar Arm64 (PostGIS).
   **Networking:** dejar **Public IPv4** activada (muchos sitios de inmobiliarias y GitHub no tienen IPv6).
5. **SSH key:** agregá tu clave pública (`cat ~/.ssh/id_ed25519.pub` en tu Mac; si no tenés,
   `ssh-keygen -t ed25519`). Sin contraseña de root.
6. **Backups:** activalos (+20 % del precio): snapshot diario de todo el servidor, además del backup de la base.
7. Crear y anotar la **IP**.

## 2. Preparar el servidor (una vez)

```bash
ssh root@IP
curl -fsSL https://raw.githubusercontent.com/brunitob/land-intelligence/main/deploy/server-setup.sh -o setup.sh
bash setup.sh
```

Instala Docker, firewall (solo SSH/HTTP/HTTPS), actualizaciones automáticas de seguridad, swap, clona el repo
en `/opt/land`, crea `/opt/land/.env` con contraseñas aleatorias y programa el backup diario.

Completá las claves (las mismas que tenés en tu `.env` local):

```bash
nano /opt/land/.env      # ANTHROPIC_API_KEY, ORS_API_KEY, USER_AGENT con un contacto real
```

`SITE_ADDRESS` queda como `IP-con-guiones.sslip.io` (HTTPS válido sin comprar dominio). Si tenés dominio:
creá un registro **A** `land.tudominio.com → IP` y poné ese nombre en `SITE_ADDRESS`.

## 3. Pasar tus datos actuales (una vez, desde tu Mac)

Copia fuentes, avisos, historial de precios y destacados. Con Docker Desktop andando:

```bash
docker compose up -d postgres
deploy/migrate-db.sh root@IP
docker compose stop postgres
```

Al terminar levanta todo en el servidor. Si preferís arrancar de cero, salteá este paso y corré
`/opt/land/deploy/up.sh` en el servidor.

## 4. Crear tu usuario

Con todo levantado, en el servidor:

```bash
/opt/land/deploy/set-password.sh
```

## 5. Listo

App: `https://<SITE_ADDRESS>`, con pantalla de ingreso (usuario y contraseña; la guarda el gestor de
contraseñas). Seguridad: contraseñas con scrypt, sesión en cookie `HttpOnly`/`Secure`/`SameSite=Strict`
(30 días, vence a los 7 sin uso), protección CSRF, y tras 5 intentos fallidos por usuario (o 20 por IP) se
bloquea 15 minutos.

## Día a día

| Qué | Cómo |
|---|---|
| Publicar cambios | commit + push a `main`, y desde tu Mac `deploy/deploy.sh root@IP` |
| Ver estado | `ssh root@IP 'cd /opt/land && docker compose -f docker-compose.yml -f docker-compose.prod.yml ps'` |
| Ver logs | `... logs -f --tail 100 scraper-worker` (mismo prefijo) |
| Backup manual | `ssh root@IP /opt/land/deploy/backup.sh` (los diarios quedan en `/opt/land/deploy/backups`, 14 días) |
| Bajar un backup | `scp root@IP:/opt/land/deploy/backups/land-AAAAMMDD-HHMM.dump .` |
| Crear usuario o cambiar contraseña | `ssh -t root@IP /opt/land/deploy/set-password.sh` (cierra las sesiones abiertas de ese usuario) |

## Notas

- El servidor despliega lo que está **pusheado** en GitHub, no lo que tenés sin commitear.
- Si pasás el repo a **privado**, el servidor necesita una *deploy key* de solo lectura:
  `ssh-keygen -t ed25519 -f ~/.ssh/land_deploy` en el servidor, cargar la `.pub` en GitHub →
  Settings → Deploy keys, y `git -C /opt/land remote set-url origin git@github.com:brunitob/land-intelligence.git`.
- Las migraciones de la base corren solas al iniciar la API.
- Nunca subas `/opt/land/.env` a git (está en `.gitignore`).
