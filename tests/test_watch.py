"""Seguimiento de fichas puntuales: se visitan con el fetcher normal y sus cambios quedan para la sección Seguimiento."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select, text

from patagonia_land.db.models import Listing, ListingChange, Source, WatchedUrl
from patagonia_land.db.session import session_scope
from patagonia_land.watch import run_watch
from tests.conftest import requires_db
from tests.fixtures.sites import A_ITEMS
from tests.test_monitoring import clean_db  # noqa: F401  (fixture)


def _url(pid: int) -> str:
    it = next(i for i in A_ITEMS if i.id == pid)
    return f"https://inmoa.test/propiedad/{it.id}-{it.locality.lower().replace(' ', '-')}/"


@requires_db
async def test_watch_detects_changes_and_removal(clean_db, fetcher_factory, site_state):  # noqa: F811
    with session_scope() as s:
        s.execute(text("TRUNCATE watched_urls RESTART IDENTITY"))
        s.add(WatchedUrl(url=_url(101), status="pending"))
        s.add(WatchedUrl(url="https://otro.test/aviso/9", status="pending"))

    res = await run_watch(fetcher_factory=fetcher_factory, use_llm=False)
    assert res["checked"] == 2
    with session_scope() as s:
        w = s.scalar(select(WatchedUrl).where(WatchedUrl.url == _url(101)))
        assert w.status == "ok" and w.listing_id
        lst = s.get(Listing, w.listing_id)
        assert lst.source_id == "inmoa" and lst.price
        other = s.scalar(select(WatchedUrl).where(WatchedUrl.url.contains("otro.test")))
        assert other.status == "gone" and other.listing_id is None
        # dominio desconocido: fuente creada pero deshabilitada (no se crawlea el sitio entero)
        assert s.get(Source, "otro_test").enabled is False

    from patagonia_land.api.main import app
    c = TestClient(app)
    assert c.get("/status").json()["watch_unseen"] == 0  # el alta del aviso no cuenta como cambio

    site_state["prices"] = {101: "USD 76.500"}
    await run_watch(fetcher_factory=fetcher_factory, use_llm=False)
    rows = {r["url"]: r for r in c.get("/watch").json()}
    row = rows[_url(101)]
    assert row["unseen"] == 1 and row["changes"][0]["change_type"] == "price_decreased"
    assert c.get("/status").json()["watch_unseen"] == 1
    assert c.post("/watch/seen", json={}).json()["seen"] == 2
    assert c.get("/status").json()["watch_unseen"] == 0

    site_state["hidden"] = {101}
    await run_watch(fetcher_factory=fetcher_factory, use_llm=False)
    with session_scope() as s:
        w = s.scalar(select(WatchedUrl).where(WatchedUrl.url == _url(101)))
        assert w.status == "gone"
        assert s.get(Listing, w.listing_id).status == "removed"
        assert s.scalar(select(ListingChange.change_type).where(ListingChange.listing_id == w.listing_id)
                        .order_by(ListingChange.id.desc())) == "removed"


@requires_db
def test_add_watch_cleans_tracking_and_dedups(monkeypatch):
    from patagonia_land.api import main
    from patagonia_land.api.main import app
    from patagonia_land.crawling.fetcher import FetchError

    def fake_check(url: str) -> None:  # sin DNS en los tests: solo IPs privadas literales
        if "127.0.0.1" in url:
            raise FetchError("IP privada")
    monkeypatch.setattr(main, "assert_public_url", fake_check)
    with session_scope() as s:
        s.execute(text("TRUNCATE watched_urls RESTART IDENTITY"))
    c = TestClient(app)
    r = c.post("/watch", json={"urls": ["https://example.com/p/1?n_src=Listado&n_pg=1&utm_source=x&id=7",
                                        "https://example.com/p/1?id=7"]}).json()
    assert r["added"] == ["https://example.com/p/1?id=7"] and r["existing"] == ["https://example.com/p/1?id=7"]
    assert c.post("/watch", json={"urls": ["http://127.0.0.1/x"]}).json()["rejected"]
    with session_scope() as s:
        s.execute(text("TRUNCATE watched_urls RESTART IDENTITY"))
        s.execute(text("DELETE FROM jobs WHERE kind = 'watch'"))


def test_redirect_to_home_means_gone():
    from patagonia_land.watch import _redirected_home
    assert _redirected_home("https://x.test/p/123-lote", "https://x.test/")
    assert not _redirected_home("https://x.test/p/123-lote", "https://x.test/p/123-lote-en-venta")
    assert not _redirected_home("https://x.test/", "https://x.test/")
