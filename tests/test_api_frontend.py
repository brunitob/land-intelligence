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
