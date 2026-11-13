# Arquitectura

```
POST /sources ─► job inspect ─► Site Inspector ─► SiteProfile (versionado; manual > auto)
                                                     │
scheduler ─► job crawl ─► Discovery Engine ◄─────────┘
                           │  sitemaps + crawl (tarjetas, next, paginación sintética)
                           │  clasificador: PROPERTY_DETAIL / LIST / PAGINATION / CATEGORY / OTHER / UNKNOWN
                           ▼
                     Fichas (HTML ya descargado)
                           ▼
         extract_listing: override → adapter → selectores → JSON-LD → HTML → LLM
                           ▼
         build_listing (Pydantic): validación, gazetteer, agua, confianza
                           ▼
         persistencia: listings + snapshots (hash) + changes + crawled_pages + properties (dedup)
                           ▼
         salud de la corrida → missing/removed · alertas Telegram
```

## Módulos

| Ruta | Responsabilidad |
|---|---|
| `crawling/fetcher.py` | HTTP con robots, rate limit, backoff, SSRF, límite de tamaño, Playwright opcional |
| `crawling/page.py` | Parseo único: links, JSON-LD, meta, grupos de tarjetas, señales de paginación |
| `crawling/classifier.py` | Puntaje por URL + DOM + datos estructurados |
| `crawling/inspector.py` | Genera el `SiteProfile` |
| `crawling/discovery.py` | Frontera con prioridades, profundidad, presupuesto de páginas |
| `extraction/*` | Extractores, draft con proveniencia, LLM, validación |
| `intelligence/*` | Normalización (formatos AR), agua, deduplicación |
| `geo/*` | Gazetteer de localidades, isócronas/tiempos ORS |
| `monitoring/*` | Diff de snapshots, alertas |
| `pipeline.py` | Orquestación del vertical slice |
| `jobs.py`, `worker/`, `scheduler/` | Cola de jobs en Postgres |

## Pendientes conocidos

- Hidrografía OSM (`water_features`) y distancia al agua más cercana.
- Endpoints JSON públicos detectados por el inspector (hoy solo se anotan; no se consumen).
- "Ver más"/scroll infinito requiere `ENABLE_PLAYWRIGHT=true`; el clic automático en "ver más" no está implementado.
- Conversión ARS→USD (hoy `price_usd` es null para precios en pesos).
- Dataset de evaluación de 100 fichas reales y medición de recall/exactitud.
