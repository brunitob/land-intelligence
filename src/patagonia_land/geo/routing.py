"""Isócronas y tiempos de manejo vía OpenRouteService (Fase 4).

Sin ORS_API_KEY no se calcula nada: nunca se sustituye el tiempo de manejo por distancia en línea recta.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog
from shapely.geometry import MultiPolygon, Point, shape
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from patagonia_land.config import get_settings, load_yaml
from patagonia_land.db.models import Airport, AirportIsochrone, DriveTimeCache, Property, PropertyGeoAnalysis

log = structlog.get_logger()
ORS = "https://api.openrouteservice.org"


def _headers() -> dict[str, str]:
    return {"Authorization": get_settings().ors_api_key, "Content-Type": "application/json"}


def fetch_isochrones(session: Session) -> int:
    """Calcula y guarda isócronas en auto para BRC/CPC/EQS. Idempotente."""
    if not get_settings().ors_api_key:
        log.warning("isochrones.skip", reason="ORS_API_KEY no configurada")
        return 0
    minutes = load_yaml("airports.yaml").get("geography", {}).get("isochrone_minutes", [60])
    n = 0
    with httpx.Client(timeout=60) as client:
        for ap in session.scalars(select(Airport).where(Airport.enabled.is_(True))):
            r = client.post(f"{ORS}/v2/isochrones/driving-car", headers=_headers(), json={
                "locations": [[ap.longitude, ap.latitude]], "range": [m * 60 for m in minutes],
                "range_type": "time"})
            r.raise_for_status()
            for feat in r.json()["features"]:
                mins = int(feat["properties"]["value"] / 60)
                geom = shape(feat["geometry"])
                mp = geom if isinstance(geom, MultiPolygon) else MultiPolygon([geom])
                row = session.scalar(select(AirportIsochrone).where(
                    AirportIsochrone.airport_code == ap.code, AirportIsochrone.minutes == mins,
                    AirportIsochrone.provider == "openrouteservice"))
                row = row or AirportIsochrone(airport_code=ap.code, minutes=mins, provider="openrouteservice")
                row.geom = f"SRID=4326;{mp.wkt}"
                session.add(row)
                n += 1
    return n


MATRIX_PAUSE_S = 2.0
MATRIX_CHUNK = 200  # destinos por pedido (límite público de ORS: 3500 rutas por pedido)

Point_ = tuple[int, int]  # (lat_e4, lon_e4): coordenadas redondeadas a 4 decimales (~10 m)


class QuotaExceeded(Exception):
    """ORS rechaza por cuota/clave (401/403/429): no insistir en esta corrida."""


def _key(lat: float, lon: float) -> Point_:
    return round(lat * 1e4), round(lon * 1e4)


def _drive_minutes_many(client: httpx.Client, ap: Airport, points: list[tuple[float, float]]
                        ) -> list[float | None]:
    """Minutos de manejo desde el aeropuerto a cada (lat, lon), en lotes. None = ORS no encontró ruta.

    Lanza QuotaExceeded ante 401/403/429 (cuota agotada o clave inválida) y FetchError-like ante otros fallos,
    para que el llamador NO confunda una falla del servicio con "sin ruta".
    """
    out: list[float | None] = []
    for i in range(0, len(points), MATRIX_CHUNK):
        chunk = points[i:i + MATRIX_CHUNK]
        r = client.post(f"{ORS}/v2/matrix/driving-car", headers=_headers(), json={
            "locations": [[ap.longitude, ap.latitude]] + [[lon, lat] for lat, lon in chunk],
            "sources": [0], "destinations": list(range(1, len(chunk) + 1)), "metrics": ["duration"]})
        if r.status_code in (401, 403, 429):
            raise QuotaExceeded(f"ORS {r.status_code}: {r.text[:120]}")
        r.raise_for_status()
        out.extend(round(d / 60, 1) if d is not None else None for d in r.json()["durations"][0])
        time.sleep(MATRIX_PAUSE_S)  # límite público de ORS: 40 pedidos de matriz por minuto
    return out


def _fill_cache(session: Session, client: httpx.Client, ap: Airport, needed: set[Point_]) -> int:
    """Pide a ORS solo los puntos que no están en el caché. Devuelve cuántos agregó."""
    have = {(c.lat_e4, c.lon_e4) for c in session.scalars(
        select(DriveTimeCache).where(DriveTimeCache.airport_code == ap.code))}
    missing = sorted(needed - have)
    if not missing:
        return 0
    added = 0
    for i in range(0, len(missing), MATRIX_CHUNK):
        chunk = missing[i:i + MATRIX_CHUNK]
        mins = _drive_minutes_many(client, ap, [(la / 1e4, lo / 1e4) for la, lo in chunk])
        for (la, lo), m in zip(chunk, mins, strict=True):
            session.add(DriveTimeCache(airport_code=ap.code, lat_e4=la, lon_e4=lo, minutes=m))
        session.flush()  # lo obtenido queda guardado aunque un lote posterior falle por cuota
        added += len(chunk)
    return added


def analyze_properties(session: Session, max_minutes: int | None = None) -> dict[str, int]:
    """Tiempo de manejo a cada aeropuerto y pertenencia al radio (config: max_drive_minutes, p. ej. 150).

    Las isócronas públicas de ORS llegan a 60 min, así que el radio se decide con la matriz de tiempos, con
    caché por punto (cada coordenada se consulta una sola vez):
    - coordenadas exactas: tiempo puntual (drive_minutes, confianza 0.9);
    - aproximadas o solo localidad: tiempo al centro de la zona, guardado como rango (min/max) con menor
      confianza; nunca se presenta como tiempo exacto.
    Si ORS falla (cuota, red) se conservan los resultados anteriores: nunca se pisa un dato con vacío.
    """
    max_minutes = max_minutes or load_yaml("airports.yaml").get("geography", {}).get("max_drive_minutes", 150)
    airports = session.scalars(select(Airport).where(Airport.enabled.is_(True))).all()
    props = [p for p in session.scalars(select(Property).where(Property.location.is_not(None)))
             if p.latitude is not None and p.longitude is not None]
    needed = {_key(p.latitude, p.longitude) for p in props}
    stats = {"properties": len(props), "points": len(needed), "ors_points": 0, "updated": 0, "kept": 0}
    if get_settings().ors_api_key:
        with httpx.Client(timeout=60) as client:
            for ap in airports:
                try:
                    stats["ors_points"] += _fill_cache(session, client, ap, needed)
                except QuotaExceeded as exc:
                    log.warning("routing.quota", airport=ap.code, error=str(exc))
                    stats["quota_exceeded"] = 1
                    break
                except httpx.HTTPError as exc:
                    log.warning("routing.ors_error", airport=ap.code, error=str(exc))
    for ap in airports:
        cache = {(c.lat_e4, c.lon_e4): c.minutes for c in session.scalars(
            select(DriveTimeCache).where(DriveTimeCache.airport_code == ap.code))}
        existing = {g.property_id: g for g in session.scalars(
            select(PropertyGeoAnalysis).where(PropertyGeoAnalysis.airport_code == ap.code))}
        for prop in props:
            k = _key(prop.latitude, prop.longitude)
            if k not in cache:
                stats["kept"] += 1  # sin dato nuevo: se deja lo anterior tal cual
                continue
            mins = cache[k]
            ga = existing.get(prop.id) or PropertyGeoAnalysis(property_id=prop.id, airport_code=ap.code)
            ga.within_isochrone = (mins <= max_minutes) if mins is not None else None
            if prop.geo_precision == "exact":
                ga.drive_minutes, ga.drive_minutes_min, ga.drive_minutes_max = mins, mins, mins
                ga.confidence = 0.9 if mins is not None else 0.2
            else:
                # Centro de zona/localidad: margen de ±15 min (aprox.) o ±25 min (solo localidad).
                slack = 15 if prop.geo_precision == "approximate" else 25
                ga.drive_minutes = None
                ga.drive_minutes_min = max(0.0, mins - slack) if mins is not None else None
                ga.drive_minutes_max = mins + slack if mins is not None else None
                ga.confidence = 0.5 if prop.geo_precision == "approximate" else 0.35
            session.add(ga)
            stats["updated"] += 1
    return stats


def point_within(geojson: dict[str, Any], lat: float, lon: float) -> bool:
    return shape(geojson).contains(Point(lon, lat))


def run_geo() -> dict[str, Any]:
    """Job 'geo': isócronas para el mapa (si faltan) + tiempo de manejo y radio por propiedad."""
    from patagonia_land.db.session import session_scope

    with session_scope() as s:
        try:
            iso = 0 if s.scalar(text("SELECT count(*) FROM airport_isochrones")) else fetch_isochrones(s)
        except httpx.HTTPError as exc:  # el mapa puede esperar; los tiempos por propiedad no dependen de esto
            log.warning("isochrones.failed", error=str(exc))
            iso = 0
    with session_scope() as s:
        stats = analyze_properties(s)
    return {"isochrones": iso, **stats}


if __name__ == "__main__":
    print(run_geo())
