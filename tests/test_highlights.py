"""Destacados: filtros editables (palabra completa, sin tildes, plural) + fijar/sacar anuncios a mano."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from patagonia_land.highlights import keyword_regex, normalize_keyword
from tests.conftest import requires_db


def test_keyword_normalization():
    assert normalize_keyword("  Hectárea ") == "hectarea"
    assert keyword_regex("Lago").startswith(r"\mlago")


@requires_db
def test_highlight_filters_pins_and_exclusions():
    from patagonia_land.api.main import app
    from patagonia_land.db.models import Listing, Source
    from patagonia_land.db.session import session_scope

    sid = f"hl_{uuid.uuid4().hex[:8]}"
    with session_scope() as s:
        s.add(Source(id=sid, name=sid, base_url=f"https://{sid}.test", region="bariloche", enabled=False))
        s.flush()

        def mk(title: str, desc: str = "", **kw):
            lst = Listing(source_id=sid, url=f"https://{sid}.test/{uuid.uuid4().hex}", title=title,
                          description=desc, status="active", photos=[], data={}, provenance={}, missed_runs=0, **kw)
            lst.canonical_url = lst.url
            s.add(lst)
            s.flush()
            return lst.id

        costa = mk("Lote con costa de LAGOS", "Acceso a playa", locality="Villa La Angostura", area_m2=1200)
        hect = mk("Chacra de 3 hectáreas", "Hay agua de vertiente", locality="El Bolsón", area_m2=30000)
        otro = mk("Departamento céntrico", "Vista a la cordillera", locality="San Carlos de Bariloche")
        alq = mk("Casa sobre el lago", "", operation="alquiler", locality="Villa La Angostura")

    c = TestClient(app)
    name = f"Lago {sid}"
    h = c.post("/highlights", json={"name": name, "keywords": ["lago", "playa"]}).json()
    ids = lambda: {i["id"]: i["origin"] for i in c.get(f"/highlights/{h['id']}/listings").json()["items"]  # noqa: E731
                   if i["source_id"] == sid}
    assert ids() == {costa: "filtro"}  # 'LAGOS' coincide sin mayúsculas y en plural; el alquiler queda afuera

    # 'ha' no matchea 'hay'; superficie mínima + zona
    c.patch(f"/highlights/{h['id']}", json={"keywords": [], "min_area_m2": 10000, "zones": ["Comarca Andina"]})
    assert ids() == {hect: "filtro"}
    assert c.patch(f"/highlights/{h['id']}", json={"zones": ["Narnia"]}).status_code == 400

    # fijar a mano un anuncio que no cumple el filtro, y sacar uno que sí
    c.put(f"/highlights/{h['id']}/listings/{otro}", json={"mode": "pinned"})
    c.put(f"/highlights/{h['id']}/listings/{hect}", json={"mode": "excluded"})
    res = c.get(f"/highlights/{h['id']}/listings").json()
    assert {i["id"] for i in res["items"] if i["source_id"] == sid} == {otro}
    assert [x["id"] for x in res["excluded"]] == [hect]
    assert {x["name"] for x in c.get(f"/listings/{otro}/highlights").json()} >= {name}

    # restaurar: vuelve por el filtro
    c.delete(f"/highlights/{h['id']}/listings/{hect}")
    assert ids() == {otro: "fijado", hect: "filtro"}
    assert alq  # el alquiler nunca entró
    assert c.post("/highlights", json={"name": name}).status_code == 409
    assert c.delete(f"/highlights/{h['id']}").status_code == 204


def test_db_session_commits_before_response():
    # Regresión: el cliente creaba un destacado y al instante le agregaba avisos → 404 (commit tardío).
    from patagonia_land.api.main import DB

    assert DB.scope == "function"


@requires_db
def test_geo_analysis_uses_cache_and_never_clobbers_on_quota(monkeypatch):
    from sqlalchemy import delete, select

    from patagonia_land.db.models import DriveTimeCache, Property, PropertyGeoAnalysis
    from patagonia_land.db.seed import seed
    from patagonia_land.db.session import session_scope
    from patagonia_land.geo import routing

    seed()
    monkeypatch.setattr(routing, "MATRIX_PAUSE_S", 0)
    monkeypatch.setattr(routing, "get_settings", lambda: type("S", (), {"ors_api_key": "k"})())
    lat, lon = -41.0 - uuid.uuid4().int % 1000 / 1e5, -71.3  # punto único por corrida de test
    with session_scope() as s:
        s.execute(delete(DriveTimeCache))
        p = Property(latitude=lat, longitude=lon, geo_precision="exact", location=f"SRID=4326;POINT({lon} {lat})")
        s.add(p)
        s.flush()
        pid = p.id
    calls = []

    def ok(client, ap, points):
        calls.append((ap.code, len(points)))
        return [90.0 if ap.code == "BRC" else 400.0 for _ in points]

    monkeypatch.setattr(routing, "_drive_minutes_many", ok)
    with session_scope() as s:
        routing.analyze_properties(s)
    first = len(calls)
    with session_scope() as s:
        routing.analyze_properties(s)  # todo en caché: ningún pedido nuevo
    assert len(calls) == first

    def quota(client, ap, points):
        raise routing.QuotaExceeded("403")

    monkeypatch.setattr(routing, "_drive_minutes_many", quota)
    with session_scope() as s:
        s.execute(delete(DriveTimeCache))
        stats = routing.analyze_properties(s)
    assert stats.get("quota_exceeded") == 1
    with session_scope() as s:
        brc = s.scalar(select(PropertyGeoAnalysis).where(PropertyGeoAnalysis.property_id == pid,
                                                        PropertyGeoAnalysis.airport_code == "BRC"))
        assert brc.within_isochrone is True and brc.drive_minutes == 90.0  # se conservó el dato anterior
        s.delete(s.get(Property, pid))
