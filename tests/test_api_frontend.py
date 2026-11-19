"""Endpoints que usa la app web: estado del encabezado y duplicados paginados."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import requires_db


@requires_db
def test_status_and_paginated_dedup():
    from patagonia_land.api.main import app

    c = TestClient(app)
    st = c.get("/status").json()
    assert {"last_run_at", "queued", "running", "running_jobs"} <= set(st)
    page = c.get("/dedup/pending", params={"limit": 2}).json()
    assert set(page) == {"total", "items"} and len(page["items"]) <= 2
    for it in page["items"]:
        assert {"id", "score", "a", "b"} <= set(it) and {"title", "url", "price", "area_m2"} <= set(it["a"])


@requires_db
def test_review_marks_listing_out_of_new():
    from patagonia_land.api.main import app

    c = TestClient(app)
    base = {"limit": 2000, "include_rentals": True}
    allp = c.get("/properties", params=base).json()
    if not allp["items"]:
        return
    lid = allp["items"][0]["id"]
    try:
        assert c.post("/listings/review", json={"ids": [lid], "reviewed": False}).status_code == 200
        new = c.get("/properties", params={**base, "only_new": True}).json()
        assert lid in {x["id"] for x in new["items"]} and all(x["is_new"] for x in new["items"])
        assert new["total"] == new["new_count"]
        assert c.get(f"/listings/{lid}").json()["is_new"] is True
        assert c.post("/listings/review", json={"ids": [lid, lid], "reviewed": True}).json() == {"reviewed": 1}
        # dos veces no rompe (on conflict do nothing)
        assert c.post("/listings/review", json={"ids": [lid]}).status_code == 200
        new2 = c.get("/properties", params={**base, "only_new": True}).json()
        assert lid not in {x["id"] for x in new2["items"]} and new2["new_count"] == new["new_count"] - 1
        assert c.get(f"/listings/{lid}").json()["is_new"] is False
    finally:
        c.post("/listings/review", json={"ids": [lid], "reviewed": True})
