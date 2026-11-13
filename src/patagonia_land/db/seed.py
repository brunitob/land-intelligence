"""Carga idempotente de aeropuertos (solo BRC/CPC/EQS) y fuentes de config/sources.yaml."""

from __future__ import annotations

from sqlalchemy import select

from patagonia_land.config import load_yaml
from patagonia_land.db.models import Airport, Source
from patagonia_land.db.session import session_scope

ALLOWED_AIRPORTS = {"BRC", "CPC", "EQS"}


def seed() -> None:
    airports = load_yaml("airports.yaml").get("airports", [])
    sources = load_yaml("sources.yaml").get("sources", [])
    with session_scope() as s:
        for a in airports:
            if a["code"] not in ALLOWED_AIRPORTS:
                raise ValueError(f"Aeropuerto {a['code']} no permitido en V1")
            obj = s.get(Airport, a["code"]) or Airport(code=a["code"])
            obj.name = a["name"]
            obj.region = a.get("region")
            obj.latitude = a["latitude"]
            obj.longitude = a["longitude"]
            obj.location = f"SRID=4326;POINT({a['longitude']} {a['latitude']})"
            obj.enabled = a.get("enabled", True)
            s.add(obj)
        for src in sources:
            if s.scalar(select(Source).where(Source.id == src["id"])):
                continue  # nunca pisar lo editado por el usuario
            s.add(Source(**{k: v for k, v in src.items() if k in Source.__table__.columns}))
    print(f"seed ok: {len(airports)} aeropuertos, {len(sources)} fuentes en config")


if __name__ == "__main__":
    seed()
