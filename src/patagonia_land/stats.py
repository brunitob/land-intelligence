"""Métricas operativas y de mercado para el tab Estadísticas (solo lectura, SQL agregado)."""

from __future__ import annotations

from statistics import median
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from patagonia_land.geo.localities import zones as zone_index

LAND = ("terreno", "lote", "chacra", "campo")
ACTIVE = ("active", "missing")


# Un 'new_listing' cuenta como nuevo de verdad solo si aparece después del primer crawl terminado de su fuente
# (la carga inicial no son avisos nuevos en el mercado).
NOT_INITIAL = """(c.change_type <> 'new_listing' OR c.detected_at > (
    SELECT min(r.finished_at) FROM crawl_runs r JOIN listings l2 ON l2.source_id = r.source_id
    WHERE l2.id = c.listing_id))"""


def _rows(s: Session, sql: str, **params: Any) -> list[dict[str, Any]]:
    return [dict(r._mapping) for r in s.execute(text(sql), params)]


def _one(s: Session, sql: str, **params: Any) -> dict[str, Any]:
    return dict(s.execute(text(sql), params).one()._mapping)


def _num(v: Any) -> float | None:
    return float(v) if v is not None else None


def compute(s: Session, days: int = 14) -> dict[str, Any]:
    land = {"land": list(LAND), "active": list(ACTIVE)}
    kpis = _one(s, """
        SELECT
          (SELECT count(*) FROM listings WHERE status = ANY(:active)) AS listings_active,
          (SELECT count(*) FROM listings WHERE status = ANY(:active) AND property_type = ANY(:land)
                                         AND coalesce(operation, '') <> 'alquiler') AS land_active,
          (SELECT count(*) FROM sources WHERE enabled) AS sources_enabled,
          (SELECT count(*) FROM sources) AS sources_total,
          (SELECT count(*) FROM crawl_runs WHERE started_at > now() - interval '24 hours') AS runs_24h,
          (SELECT count(*) FROM crawl_runs WHERE started_at > now() - interval '24 hours'
                                           AND status NOT IN ('success', 'partial')) AS runs_failed_24h,
          (SELECT count(*) FROM crawl_runs WHERE started_at > now() - interval '24 hours'
                                           AND possibly_broken) AS runs_broken_24h,
          (SELECT max(finished_at) FROM crawl_runs) AS last_run_at,
          (SELECT count(*) FROM listing_changes c WHERE c.change_type = 'new_listing'
                                                  AND c.detected_at > now() - interval '7 days'
                                                  AND """ + NOT_INITIAL + """) AS new_7d,
          (SELECT count(*) FROM listing_changes WHERE change_type = 'price_decreased'
                                                AND detected_at > now() - interval '7 days') AS price_drops_7d,
          (SELECT count(*) FROM listing_changes WHERE change_type = 'removed'
                                                AND detected_at > now() - interval '7 days') AS removed_7d,
          (SELECT count(*) FROM dedup_candidates WHERE status = 'pending') AS dedup_pending,
          (SELECT count(DISTINCT property_id) FROM property_geo_analysis
            WHERE within_isochrone IS NOT NULL) AS props_with_drive_time,
          (SELECT count(*) FROM properties WHERE location IS NOT NULL) AS props_located,
          (SELECT count(*) FROM highlights) AS highlights
    """, **land)

    runs_by_day = _rows(s, """
        SELECT date(started_at AT TIME ZONE 'America/Argentina/Buenos_Aires') AS day,
               count(*) FILTER (WHERE status IN ('success', 'partial')) AS ok,
               count(*) FILTER (WHERE status NOT IN ('success', 'partial')) AS failed,
               round(avg(duration_seconds)::numeric / 60, 1) AS avg_minutes
        FROM crawl_runs WHERE started_at > now() - make_interval(days => :days)
        GROUP BY 1 ORDER BY 1""", days=days)

    changes_by_day = _rows(s, """
        SELECT date(c.detected_at AT TIME ZONE 'America/Argentina/Buenos_Aires') AS day, c.change_type,
               count(*) AS n
        FROM listing_changes c WHERE c.detected_at > now() - make_interval(days => :days) AND """ + NOT_INITIAL + """
        GROUP BY 1, 2 ORDER BY 1""", days=days)

    changes_7d = _rows(s, """
        SELECT c.change_type, count(*) AS n FROM listing_changes c
        WHERE c.detected_at > now() - interval '7 days' AND """ + NOT_INITIAL + """ GROUP BY 1 ORDER BY 2 DESC""")

    types = _rows(s, """
        SELECT coalesce(property_type, 'sin tipo') AS property_type, count(*) AS n FROM listings
        WHERE status = ANY(:active) AND coalesce(operation, '') <> 'alquiler' GROUP BY 1 ORDER BY 2 DESC""",
                  active=list(ACTIVE))

    # Mercado de tierra por zona (en Python: la zona sale del gazetteer, no de la base).
    land_rows = _rows(s, """
        SELECT locality, price_usd, area_m2 FROM listings
        WHERE status = ANY(:active) AND property_type = ANY(:land) AND coalesce(operation, '') <> 'alquiler'""",
                      **land)
    loc_to_zone = {name: z for z, names in zone_index().items() for name in names}
    agg: dict[str, dict[str, list[float]]] = {}
    for r in land_rows:
        z = loc_to_zone.get(r["locality"] or "", "Sin zona / fuera del gazetteer")
        a = agg.setdefault(z, {"n": [], "price": [], "per_ha": []})
        a["n"].append(1)
        p, m2 = _num(r["price_usd"]), r["area_m2"]
        if p:
            a["price"].append(p)
            if m2 and m2 >= 500:  # USD/ha solo con superficie creíble
                a["per_ha"].append(p / (m2 / 10_000))
    zones = sorted(({"zone": z, "listings": len(a["n"]), "with_price": len(a["price"]),
                     "median_price_usd": round(median(a["price"])) if a["price"] else None,
                     "median_usd_per_ha": round(median(a["per_ha"])) if a["per_ha"] else None}
                    for z, a in agg.items()), key=lambda x: -x["listings"])

    sources = _rows(s, """
        WITH last AS (SELECT DISTINCT ON (source_id) * FROM crawl_runs ORDER BY source_id, id DESC),
        cov AS (
          SELECT source_id, count(*) AS active,
                 count(*) FILTER (WHERE property_type = ANY(:land)) AS land,
                 avg((price IS NOT NULL OR (data->>'price_on_request') = 'true')::int) AS pct_price,
                 avg((area_m2 IS NOT NULL)::int) AS pct_area,
                 avg((locality IS NOT NULL)::int) AS pct_locality,
                 avg((geo_precision IN ('exact', 'approximate'))::int) AS pct_coords
          FROM listings WHERE status = ANY(:active) GROUP BY 1),
        ch AS (SELECT l.source_id,
                      count(*) FILTER (WHERE c.change_type = 'new_listing') AS new_7d,
                      count(*) FILTER (WHERE c.change_type IN ('price_decreased', 'price_increased')) AS price_7d,
                      count(*) FILTER (WHERE c.change_type = 'removed') AS removed_7d
               FROM listing_changes c JOIN listings l ON l.id = c.listing_id
               WHERE c.detected_at > now() - interval '7 days' AND """ + NOT_INITIAL + """ GROUP BY 1)
        SELECT s.id, s.name, s.region, s.enabled, s.base_url,
               coalesce(cov.active, 0) AS active, coalesce(cov.land, 0) AS land,
               cov.pct_price, cov.pct_area, cov.pct_locality, cov.pct_coords,
               last.status AS last_status, last.finished_at AS last_run_at, last.possibly_broken,
               last.errors_count AS last_errors, round(last.duration_seconds::numeric / 60, 1) AS last_minutes,
               coalesce(ch.new_7d, 0) AS new_7d, coalesce(ch.price_7d, 0) AS price_changes_7d,
               coalesce(ch.removed_7d, 0) AS removed_7d
        FROM sources s LEFT JOIN cov ON cov.source_id = s.id LEFT JOIN last ON last.source_id = s.id
        LEFT JOIN ch ON ch.source_id = s.id
        ORDER BY s.enabled DESC, coalesce(cov.active, 0) DESC""", **land)
    for r in sources:
        for k in ("pct_price", "pct_area", "pct_locality", "pct_coords", "last_minutes"):
            r[k] = _num(r[k])

    price_moves = _rows(s, """
        SELECT c.detected_at, c.change_type, c.pct_change, l.id AS listing_id, l.title, l.locality, l.source_id,
               l.price, l.currency, l.url
        FROM listing_changes c JOIN listings l ON l.id = c.listing_id
        WHERE c.change_type IN ('price_decreased', 'price_increased')
          AND c.detected_at > now() - make_interval(days => :days)
        ORDER BY c.detected_at DESC LIMIT 50""", days=days)
    for r in price_moves:
        r["pct_change"], r["price"] = _num(r["pct_change"]), _num(r["price"])

    drive = _rows(s, """
        SELECT airport_code, count(*) FILTER (WHERE within_isochrone) AS within,
               count(*) FILTER (WHERE within_isochrone IS FALSE) AS outside,
               count(*) FILTER (WHERE within_isochrone IS NULL) AS unknown
        FROM property_geo_analysis GROUP BY 1 ORDER BY 1""")

    return {"kpis": kpis, "runs_by_day": runs_by_day, "changes_by_day": changes_by_day,
            "changes_7d": changes_7d, "types": types, "zones": zones, "sources": sources,
            "price_moves": price_moves, "drive": drive}
