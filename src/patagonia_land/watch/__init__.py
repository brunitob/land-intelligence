"""Seguimiento de fichas puntuales (links que pasa el usuario).

Cada ficha se visita con el mismo fetcher que los crawls (robots.txt, ritmo por host, sin evadir bloqueos) y se
procesa con el mismo extractor. Si el sitio no es una fuente cargada se crea una fuente deshabilitada para ese
dominio: así el aviso tiene dueño, pero el scheduler no crawlea el sitio entero.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from patagonia_land.adapters.generic import extract_listing
from patagonia_land.crawling.fetcher import (
    BlockedError,
    Fetcher,
    FetchError,
    OutsideVisitTime,
    RobotsDisallowed,
)
from patagonia_land.crawling.page import Page
from patagonia_land.db.models import Listing, ListingChange, Source, WatchedUrl
from patagonia_land.db.session import session_scope
from patagonia_land.monitoring.changes import ChangeType
from patagonia_land.monitoring.notifications import queue_alerts

log = structlog.get_logger()


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def source_for(s: Session, url: str) -> Source:
    host = _host(url)
    for src in s.scalars(select(Source)):
        if _host(src.base_url) == host:
            return src
    sid = re.sub(r"[^a-z0-9]+", "_", host).strip("_")[:100]
    parts = urlsplit(url)
    src = Source(id=sid, name=host, base_url=f"{parts.scheme}://{parts.netloc}", start_urls=[], enabled=False,
                 manual_overrides={})
    s.add(src)
    s.flush()
    log.info("watch.source_created", source=sid)
    return src


async def run_watch(job_id: int | None = None, fetcher_factory: Any = Fetcher, use_llm: bool = True,
                    only_ids: list[int] | None = None) -> dict[str, Any]:
    from patagonia_land.pipeline import active_profile, upsert_listing

    with session_scope() as s:
        q = select(WatchedUrl.id, WatchedUrl.url).order_by(WatchedUrl.id)
        if only_ids:
            q = q.where(WatchedUrl.id.in_(only_ids))
        targets = s.execute(q).all()
    counts: dict[str, int] = {}
    async with fetcher_factory() as f:
        for wid, url in targets:
            status, error, listing_id = "ok", None, None
            try:
                with session_scope() as s:
                    src = source_for(s, url)
                    profile, _ = active_profile(s, src)
                    sid, base, region, overrides = src.id, src.base_url, src.region, dict(src.manual_overrides or {})
                res = await f.get(url)
                if res.status in (404, 410):
                    status, error = "gone", f"HTTP {res.status}: el aviso ya no está publicado"
                elif res.status >= 400:
                    status, error = "error", f"HTTP {res.status}"
                else:
                    page = Page(url=res.url, html=res.text, base_url=base)
                    e = await extract_listing(sid, page, profile, overrides, use_llm=use_llm, region=region)
                    with session_scope() as s:
                        listing, _ = upsert_listing(s, sid, e, res.text, None, datetime.now(UTC))
                        s.flush()
                        listing_id = listing.id
            except OutsideVisitTime as exc:
                status, error = "pending", str(exc)
            except RobotsDisallowed as exc:
                status, error = "robots", str(exc)
            except BlockedError as exc:
                status, error = "blocked", str(exc)
            except FetchError as exc:
                status, error = "error", str(exc)
            except Exception as exc:  # una ficha rota no frena las demás
                log.exception("watch.error", url=url)
                status, error = "error", repr(exc)[:500]
            with session_scope() as s:
                w = s.get(WatchedUrl, wid)
                if not w:
                    continue
                w.status, w.last_error, w.last_checked_at = status, error, datetime.now(UTC)
                if listing_id:
                    w.listing_id = listing_id
                if status == "gone" and w.listing_id:
                    lst = s.get(Listing, w.listing_id)
                    if lst and lst.status != "removed":
                        lst.status = "removed"
                        s.add(ListingChange(listing_id=lst.id, change_type=ChangeType.REMOVED,
                                            old_value={"last_seen_at": lst.last_seen_at.isoformat()}))
            counts[status] = counts.get(status, 0) + 1
    with session_scope() as s:
        pending = s.scalars(select(ListingChange).where(ListingChange.notified.is_(False))).all()
        alerts = queue_alerts(s, list(pending))
    return {"checked": len(targets), "by_status": counts, "alerts_queued": alerts}
