"""Isócronas y tiempos de manejo vía OpenRouteService (Fase 4).

Sin ORS_API_KEY no se calcula nada: nunca se sustituye el tiempo de manejo por distancia en línea recta.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog
from shapely.geometry import MultiPolygon, Point, shape
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from patagonia_land.config import get_settings, load_yaml
from patagonia_land.db.models import Airport, AirportIsochrone, Property, PropertyGeoAnalysis

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


def _drive_minutes(client: httpx.Client, ap: Airport, lat: float, lon: float) -> float | None:
    r = client.post(f"{ORS}/v2/matrix/driving-car", headers=_headers(), json={
        "locations": [[ap.longitude, ap.latitude], [lon, lat]], "sources": [0], "destinations": [1],
        "metrics": ["duration"]})
    if r.status_code != 200:
        return None
    d = r.json()["durations"][0][0]
    return round(d / 60, 1) if d is not None else None


def analyze_properties(session: Session, max_minutes: int | None = None) -> int:
    """Pertenencia a isócronas (PostGIS) + tiempo punto a punto solo para coordenadas exactas."""
    max_minutes = max_minutes or load_yaml("airports.yaml").get("geography", {}).get("max_drive_minutes", 60)
    has_key = bool(get_settings().ors_api_key)
    airports = session.scalars(select(Airport).where(Airport.enabled.is_(True))).all()
    n = 0
    client = httpx.Client(timeout=30) if has_key else None
    try:
        for prop in session.scalars(select(Property).where(Property.location.is_not(None))):
            for ap in airports:
                within = session.execute(text(
                    "SELECT ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)) FROM airport_isochrones "
                    "WHERE airport_code = :code AND minutes = :m LIMIT 1"),
                    {"lon": prop.longitude, "lat": prop.latitude, "code": ap.code, "m": max_minutes}).scalar()
                ga = session.scalar(select(PropertyGeoAnalysis).where(
                    PropertyGeoAnalysis.property_id == prop.id, PropertyGeoAnalysis.airport_code == ap.code))
                ga = ga or PropertyGeoAnalysis(property_id=prop.id, airport_code=ap.code)
                ga.within_isochrone = within
                if prop.geo_precision == "exact" and client:
                    ga.drive_minutes = _drive_minutes(client, ap, prop.latitude, prop.longitude)
                    ga.confidence = 0.9
                else:
                    ga.drive_minutes = None  # ubicación aproximada: sin tiempo exacto
                    ga.confidence = 0.4 if prop.geo_precision == "locality" else 0.2
                session.add(ga)
                n += 1
    finally:
        if client:
            client.close()
    return n


def point_within(geojson: dict[str, Any], lat: float, lon: float) -> bool:
    return shape(geojson).contains(Point(lon, lat))
