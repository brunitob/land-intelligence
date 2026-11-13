from __future__ import annotations

from fastapi.testclient import TestClient

from patagonia_land.intelligence.deduplication import ListingFeatures, decide, score_pair
from tests.conftest import requires_db


def lf(i: int, source: str, **kw) -> ListingFeatures:
    base = dict(locality="Trevelin", latitude=-43.09, longitude=-71.47, geo_precision="exact", area_m2=20_000,
                price_usd=95_000, title="Terreno 2 ha Trevelin", description="Terreno de 2 hectáreas sobre camino vecinal",
                photos=["https://a/x/foto-campo-trevelin-1.jpg", "https://a/x/foto-campo-trevelin-2.jpg"])
    base.update(kw)
    return ListingFeatures(id=i, source_id=source, **base)


def test_same_property_two_agencies_auto_merges():
    a = lf(1, "inmoa")
    b = lf(2, "inmob", price_usd=99_000, title="Hermoso terreno en Trevelin",
           photos=["https://b/up/foto-campo-trevelin-1-1024x768.jpg"])
    score, reasons = score_pair(a, b)
    assert decide(score) == "auto_merged", (score, reasons)


def test_ambiguous_goes_to_review():
    a = lf(1, "inmoa", geo_precision="locality")
    b = lf(2, "inmob", geo_precision="locality", area_m2=20_500, photos=[], description="Lote amplio con vista")
    score, reasons = score_pair(a, b)
    assert decide(score) in ("pending", "distinct"), (score, reasons)
    assert decide(score) != "auto_merged"


def test_different_area_never_merges():
    score, _ = score_pair(lf(1, "inmoa"), lf(2, "inmob", area_m2=50_000))
    assert score == 0.0


def test_same_source_never_merges():
    assert score_pair(lf(1, "inmoa"), lf(2, "inmoa"))[0] == 0.0


@requires_db
def test_api_sources_and_filters():
    from patagonia_land.api.main import app

    c = TestClient(app)
    assert c.get("/health").json() == {"status": "ok"}
    r = c.post("/sources", json={"base_url": "http://127.0.0.1:8000"})
    assert r.status_code == 400  # SSRF bloqueado al registrar
    r = c.get("/properties", params={"airports": ["AEP"]})
    assert r.status_code == 400  # solo BRC/CPC/EQS
    assert {a["code"] for a in c.get("/airports").json()} <= {"BRC", "CPC", "EQS"}
