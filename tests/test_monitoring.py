"""End-to-end del vertical slice contra PostgreSQL/PostGIS (base de test separada)."""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from patagonia_land.db.models import CrawlRun, Listing, ListingChange, ListingSnapshot, Source
from patagonia_land.db.session import session_scope
from patagonia_land.monitoring.changes import ChangeType, diff_snapshots
from patagonia_land.pipeline import run_crawl
from tests.conftest import requires_db


def test_diff_price_decrease():
    ch = diff_snapshots({"price": 100_000, "currency": "USD"}, {"price": 90_000, "currency": "USD"})
    assert ch[0].change_type == ChangeType.PRICE_DECREASED and ch[0].pct_change == -10.0


def test_diff_no_changes():
    snap = {"price": 1, "currency": "USD", "description": "Hola  mundo"}
    assert diff_snapshots(snap, {**snap, "description": "hola mundo"}) == []


@pytest.fixture
def clean_db():
    with session_scope() as s:
        s.execute(text("TRUNCATE sources, jobs, crawl_runs, crawled_pages, listings, listing_snapshots, "
                       "listing_changes, properties, dedup_candidates, alerts, site_profiles RESTART IDENTITY CASCADE"))
        for sid, url, start, region in (("inmoa", "https://inmoa.test", ["https://inmoa.test/propiedades"], "bariloche"),
                                        ("inmob", "https://inmob.test", [], "esquel"),
                                        ("inmoc", "https://inmoc.test", ["https://inmoc.test/venta"], "chapelco")):
            s.add(Source(id=sid, name=sid, base_url=url, start_urls=start, region=region, max_pages_per_run=60,
                         max_depth=5, manual_overrides={}))
    yield


def _changes(listing_url_part: str) -> list[str]:
    with session_scope() as s:
        lst = s.scalar(select(Listing).where(Listing.canonical_url.contains(listing_url_part)))
        return [c.change_type for c in s.scalars(select(ListingChange).where(ListingChange.listing_id == lst.id)
                                                 .order_by(ListingChange.id))]


@requires_db
async def test_full_slice_three_sites(clean_db, fetcher_factory):
    totals = {}
    for sid in ("inmoa", "inmob", "inmoc"):
        res = await run_crawl(sid, fetcher_factory=fetcher_factory, use_llm=False)
        assert res["status"] == "success", res
        totals[sid] = res["details_processed"]
    assert totals == {"inmoa": 5, "inmob": 4, "inmoc": 4}
    with session_scope() as s:
        n_snap = s.scalar(text("SELECT count(*) FROM listing_snapshots"))
        assert n_snap == 13
        assert s.scalar(text("SELECT count(*) FROM site_profiles")) == 3  # auto-inspección en el 1er crawl
        assert s.scalar(text("SELECT count(*) FROM crawled_pages WHERE page_type = 'PROPERTY_DETAIL'")) == 13


@requires_db
async def test_unchanged_recrawl_does_not_duplicate_snapshots(clean_db, fetcher_factory):
    await run_crawl("inmoa", fetcher_factory=fetcher_factory, use_llm=False)
    res = await run_crawl("inmoa", fetcher_factory=fetcher_factory, use_llm=False)
    assert res["unchanged"] == 5 and res["created"] == 0
    with session_scope() as s:
        assert s.scalar(select(text("count(*)")).select_from(ListingSnapshot)) == 5


@requires_db
async def test_price_change_detected(clean_db, fetcher_factory, site_state):
    await run_crawl("inmoa", fetcher_factory=fetcher_factory, use_llm=False)
    site_state["prices"] = {101: "USD 76.500"}
    res = await run_crawl("inmoa", fetcher_factory=fetcher_factory, use_llm=False)
    assert res["updated"] == 1
    assert _changes("/101-")[-1] == ChangeType.PRICE_DECREASED
    with session_scope() as s:
        ch = s.scalar(select(ListingChange).where(ListingChange.change_type == "price_decreased"))
        assert ch.pct_change == -10.0
        assert float(s.scalar(select(Listing.price).where(Listing.canonical_url.contains("/101-")))) == 76_500


@requires_db
async def test_removal_requires_repeated_absence(clean_db, fetcher_factory, site_state):
    await run_crawl("inmoa", fetcher_factory=fetcher_factory, use_llm=False)
    site_state["hidden"] = {104}
    statuses = []
    for _ in range(3):
        await run_crawl("inmoa", fetcher_factory=fetcher_factory, use_llm=False)
        with session_scope() as s:
            statuses.append(s.scalar(select(Listing.status).where(Listing.canonical_url.contains("/104-"))))
    assert statuses == ["missing", "missing", "removed"]
    site_state["hidden"] = set()
    await run_crawl("inmoa", fetcher_factory=fetcher_factory, use_llm=False)
    assert _changes("/104-")[-1] == ChangeType.RELISTED


@requires_db
async def test_broken_run_does_not_mark_removals(clean_db, fetcher_factory, site_state):
    await run_crawl("inmoa", fetcher_factory=fetcher_factory, use_llm=False)
    await run_crawl("inmoa", fetcher_factory=fetcher_factory, use_llm=False)
    site_state["hidden"] = {101, 102, 103, 104}  # el sitio "se rompe": solo queda 1 de 5
    res = await run_crawl("inmoa", fetcher_factory=fetcher_factory, use_llm=False)
    assert res["possibly_broken"] is True and res["missing"] == 0 and res["removed"] == 0
    with session_scope() as s:
        assert s.scalar(select(CrawlRun.possibly_broken).order_by(CrawlRun.id.desc())) is True
        assert s.scalar(text("SELECT count(*) FROM listings WHERE status = 'active'")) == 5
