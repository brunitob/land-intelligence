# Patagonia Land Intelligence

Descubre, extrae, normaliza y monitorea terrenos, lotes, chacras y campos publicados por inmobiliarias
locales en la zona de **BRC** (Bariloche), **CPC** (Chapelco) y **EQS** (Esquel). La especificación
completa está en [patagonia-land-intelligence.md](patagonia-land-intelligence.md).

## Inicio rápido

```bash
cp .env.example .env
docker compose up -d --build
```

- API: http://localhost:8000/docs
- Dashboard: http://localhost:8501

Alta de una inmobiliaria (sin tocar código):

```bash
curl -X POST localhost:8000/sources -H 'content-type: application/json' \
  -d '{"base_url": "https://www.inmobiliaria.com.ar", "region": "bariloche",
       "start_urls": ["https://www.inmobiliaria.com.ar/propiedades"]}'
```

Esto encola una **inspección** (robots, sitemaps, render, paginación, patrones de fichas → `SiteProfile`).
Después `POST /sources/{id}/crawl` (o esperar al scheduler) descubre las fichas, las extrae, guarda snapshots
y detecta cambios. El progreso se consulta en `GET /jobs/{id}`.

## Qué hay en esta versión

| Fase de la spec | Estado |
|---|---|
| 1. Infraestructura (Docker, PostGIS, modelos, migraciones, API) | ✅ |
| 2. Inspector, discovery, paginación, clasificador, extracción | ✅ validado con 3 sitios sintéticos de estructura distinta; falta validar con 3 sitios reales |
| 3. Snapshots, cambios, deduplicación, Telegram | ✅ (Telegram requiere `TELEGRAM_*`) |
| 4. Isócronas, tiempos, hidrografía | 🟡 isócronas/tiempos vía ORS listos (requiere `ORS_API_KEY`); hidrografía OSM pendiente |
| 5. Dashboard | ✅ Streamlit (Propiedades, Destacados, Estadísticas); deploy en VPS: [docs/deploy.md](docs/deploy.md) |

## Decisiones importantes

- **Nunca se inventan datos**: ausentes = `null`; cada campo guarda método, evidencia literal y confianza.
- **Jerarquía de extracción**: override manual → adaptador de sitio → selectores validados → JSON-LD/meta →
  HTML genérico → LLM (solo campos faltantes, y se descarta todo valor cuya evidencia no aparezca literal en la página).
- **Ubicación**: si la ficha no publica coordenadas se usa el centroide de la localidad con `precision=locality`;
  nunca se calcula un tiempo de manejo exacto para esos casos.
- **Agua**: el texto produce como máximo `waterfront_claimed`. `waterfront_confirmed` exige catastro/documentos.
- **Bajas**: un anuncio pasa a `missing` y recién a `removed` tras 3 ausencias en corridas sanas. Si una corrida
  encuentra < 50% de lo habitual se marca `possibly_broken` y no se da de baja nada.
- **Scraping responsable**: robots.txt, `Crawl-delay`, 2 s mínimo por dominio, backoff, sin evadir captcha/login,
  bloqueo SSRF (IPs privadas, localhost, metadata cloud, redirecciones).
- **Cola de jobs en Postgres** (`SKIP LOCKED`): no hace falta Redis.

## Desarrollo

```bash
uv venv --python 3.12 && uv pip install -e ".[dashboard,dev]"
docker compose up -d postgres
.venv/bin/pytest            # crea y migra patagonia_land_test automáticamente
```

LLM fallback: `LLM_ENABLED=true` + `ANTHROPIC_API_KEY`. Modelo por defecto `claude-opus-5-5`; para abaratar el
volumen se puede poner `LLM_MODEL=claude-haiku-5-5`. Playwright (sitios SPA): `ENABLE_PLAYWRIGHT=true` y
`docker compose build --build-arg WITH_PLAYWRIGHT=1`.

Más detalle en [docs/architecture.md](docs/architecture.md) y [docs/adding_sources.md](docs/adding_sources.md).
