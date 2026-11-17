"""Radio de 150 min (matriz de ORS, no isócronas) y zonas del gazetteer."""

from __future__ import annotations

import json

import httpx

from patagonia_land.config import load_yaml
from patagonia_land.geo import routing
from patagonia_land.geo.localities import LOCALITIES, find_locality, zones


def test_radius_is_150_and_map_isochrones_within_ors_limit():
    geo = load_yaml("airports.yaml")["geography"]
    assert geo["max_drive_minutes"] == 150
    assert max(geo["isochrone_minutes"]) <= 60  # la API pública de ORS no da isócronas en auto de más de 1 h
    assert load_yaml("search.yaml")["search"]["max_drive_minutes"] == 150


def test_requested_zones_exist_and_every_locality_has_one():
    z = zones()
    for name in ("Villa La Angostura", "Traful", "Meliquina"):
        assert name in z
    assert "Puerto Manzano" in z["Villa La Angostura"] and "Cuyín Manzano" in z["Traful"]
    assert sum(len(v) for v in z.values()) == len(LOCALITIES)
    assert len({loc.name for loc in LOCALITIES}) == len(LOCALITIES)


def test_new_localities_are_found_in_text():
    assert find_locality("Lote en Puerto Manzano con vista", region="bariloche")[0].name == "Puerto Manzano"
    assert find_locality("Chacra en Cuyín Manzano", region="bariloche")[0].name == "Cuyín Manzano"
    assert find_locality("Campo en El Maitén", region="esquel")[0].name == "El Maitén"


def test_matrix_batches_and_parses_minutes(monkeypatch):
    monkeypatch.setattr(routing, "MATRIX_CHUNK", 2)
    monkeypatch.setattr(routing, "MATRIX_PAUSE_S", 0)
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        calls.append(len(body["destinations"]))
        # 1 h por destino salvo uno sin ruta
        return httpx.Response(200, json={"durations": [[None if i == 3 else 3600.0 * i
                                                        for i in body["destinations"]]]})

    ap = type("Ap", (), {"longitude": -71.15, "latitude": -41.15, "code": "BRC"})()
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        mins = routing._drive_minutes_many(c, ap, [(-41.0, -71.0)] * 3)
    assert calls == [2, 1]
    assert mins == [60.0, 120.0, 60.0]


def test_llm_schema_has_no_nullable_unions():
    # La API rechaza esquemas con muchos campos opcionales ("Schema is too complex").
    from patagonia_land.extraction.llm_extractor import LLMListing

    schema = json.dumps(LLMListing.model_json_schema())
    assert "anyOf" not in schema and '"null"' not in schema
    assert set(LLMListing.model_json_schema()["required"]) == set(LLMListing.model_fields)


def test_matrix_quota_raises_instead_of_returning_no_route(monkeypatch):
    import pytest

    monkeypatch.setattr(routing, "MATRIX_PAUSE_S", 0)
    ap = type("Ap", (), {"longitude": -71.15, "latitude": -41.15, "code": "BRC"})()
    t = httpx.MockTransport(lambda req: httpx.Response(403, json={"error": "Quota exceeded"}))
    with httpx.Client(transport=t) as c, pytest.raises(routing.QuotaExceeded):
        routing._drive_minutes_many(c, ap, [(-41.0, -71.0)])
