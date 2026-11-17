"""Vertical slice: inspección → discovery → extracción → validación → persistencia → cambios → alertas."""

from __future__ import annotations

import gzip
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from patagonia_land.adapters.generic import extract_listing
from patagonia_land.config import get_settings
from patagonia_land.crawling.discovery import DiscoveryResult, SourceConfig, discover_properties
from patagonia_land.crawling.fetcher import Fetcher
from patagonia_land.crawling.inspector import inspect_site
from patagonia_land.db.models import (
    CrawledPage,
    CrawlRun,
    DedupCandidate,
    Job,
    Listing,
    ListingChange,
    ListingSnapshot,
    Property,
    SiteProfile,
    Source,
)
from patagonia_land.db.session import session_scope
from patagonia_land.extraction.schemas import ExtractedListing
from patagonia_land.extraction.validation import demote_shared_coordinates
from patagonia_land.intelligence.deduplication import ListingFeatures, decide, score_pair
from patagonia_land.intelligence.normalization import to_usd
from patagonia_land.jobs import Deferred
from patagonia_land.monitoring.changes import ChangeType, content_hash, diff_snapshots
from patagonia_land.monitoring.notifications import queue_alerts, send_pending

log = structlog.get_logger()


# --------------------------------------------------------------------------- perfiles
def active_profile(session: Session, source: Source) -> tuple[dict[str, Any], int | None]:
    """Perfil manual (si existe) tiene prioridad; si no, el último auto-generado."""
    profiles = session.scalars(select(SiteProfile).where(SiteProfile.source_id == source.id,
                                                         SiteProfile.active.is_(True))
                               .order_by(SiteProfile.version.desc())).all()
    manual = next((p for p in profiles if p.origin == "manual"), None)
    chosen = manual or (profiles[0] if profiles else None)
    if not chosen:
        return {}, None
    profile = dict(chosen.profile)
    # Overrides manuales del source se superponen sin ser pisados por perfiles auto.
    for k, v in (source.manual_overrides or {}).items():
        if k != "selectors":
            profile[k] = v
    return profile, chosen.version


def save_auto_profile(session: Session, source_id: str, profile: dict[str, Any]) -> SiteProfile:
    last = session.scalar(select(func.max(SiteProfile.version)).where(SiteProfile.source_id == source_id)) or 0
    prev_auto = session.scalar(select(SiteProfile).where(SiteProfile.source_id == source_id,
                                                         SiteProfile.origin == "auto", SiteProfile.active.is_(True))
                               .order_by(SiteProfile.version.desc()))
    if prev_auto and {k: v for k, v in prev_auto.profile.items() if k != "profile_version"} == profile:
        return prev_auto  # sin cambios → no versionar
    if prev_auto:
        prev_auto.active = False
    profile = {**profile, "profile_version": last + 1}
    sp = SiteProfile(source_id=source_id, version=last + 1, origin="auto", profile=profile,
                     confidence=profile.get("confidence"), active=True)
    session.add(sp)
    session.flush()
    return sp


def _source_config(s: Session, src: Source) -> SourceConfig:
    known: dict[str, float] = {}
    for url, canon, checked in s.execute(select(Listing.url, Listing.canonical_url, Listing.last_checked_at).where(
            Listing.source_id == src.id, Listing.status.in_(("active", "missing")))):
        ts = checked.timestamp() if checked else 0.0
        for u in {url, canon}:
            if u:
                known[u] = ts
    return SourceConfig(id=src.id, base_url=src.base_url, start_urls=list(src.start_urls or []),
                        max_pages_per_run=src.max_pages_per_run, max_depth=src.max_depth, known_details=known)


def _progress(job_id: int | None):
    def cb(p: dict[str, Any]) -> None:
        if job_id is None:
            return
        with session_scope() as s:
            job = s.get(Job, job_id)
            if job:
                job.progress = {**(job.progress or {}), **p}
    return cb


# --------------------------------------------------------------------------- inspección
FetcherFactory = Callable[[], Fetcher]


async def run_inspect(source_id: str, job_id: int | None = None,
                      fetcher_factory: FetcherFactory = Fetcher) -> dict[str, Any]:
    with session_scope() as s:
        src = s.get(Source, source_id)
        if not src:
            raise ValueError(f"fuente inexistente {source_id}")
        base_url, start_urls = src.base_url, list(src.start_urls or [])
    async with fetcher_factory() as f:
        opens_at = await f.next_visit_start(base_url)
    if opens_at is not None:
        raise Deferred(opens_at, "robots.txt solo permite visitas en otra franja horaria")
    _progress(job_id)({"stage": "inspecting"})
    async with fetcher_factory() as f:
        report = await inspect_site(f, source_id, base_url, start_urls)
    with session_scope() as s:
        sp = save_auto_profile(s, source_id, report.profile)
        version = sp.version
    return {"profile_version": version, "profile": report.profile, "notes": report.notes,
            "errors": report.errors, "sample_detail_urls": report.sample_detail_urls}


# --------------------------------------------------------------------------- crawl
async def run_crawl(source_id: str, job_id: int | None = None, fetcher_factory: FetcherFactory = Fetcher,
                    use_llm: bool = True) -> dict[str, Any]:
    started = time.monotonic()
    with session_scope() as s:
        src = s.get(Source, source_id)
        if not src:
            raise ValueError(f"fuente inexistente {source_id}")
        profile, version = active_profile(s, src)
        overrides = dict(src.manual_overrides or {})
        cfg = _source_config(s, src)
        region = src.region

    # robots.txt con Visit-time: fuera de la franja no se visita; el job espera a que abra (sin corrida fallida).
    async with fetcher_factory() as f:
        opens_at = await f.next_visit_start(cfg.base_url)
    if opens_at is not None:
        raise Deferred(opens_at, "robots.txt solo permite visitas en otra franja horaria")

    with session_scope() as s:
        run = CrawlRun(source_id=source_id, job_id=job_id, profile_version=version, status="running")
        s.add(run)
        s.flush()
        run_id = run.id

    if not profile:  # Primera vez: inspeccionar automáticamente.
        insp = await run_inspect(source_id, job_id, fetcher_factory)
        profile, version = insp["profile"], insp["profile_version"]

    progress = _progress(job_id)
    progress({"stage": "discovering", "crawl_run_id": run_id})
    async with fetcher_factory() as f:
        disc = await discover_properties(f, cfg, profile, progress=progress)

    progress({"stage": "extracting", "details": len(disc.details)})
    extracted: list[tuple[ExtractedListing, str]] = []
    errors = list(disc.errors)
    for url, page in disc.details.items():
        try:
            listing = await extract_listing(source_id, page, profile, overrides, use_llm=use_llm, region=region)
            extracted.append((listing, disc.detail_fetch[url].text))
        except Exception as exc:  # una ficha rota no debe tumbar la corrida
            log.exception("extract.error", url=url)
            errors.append({"url": url, "stage": "extract", "error": repr(exc)[:500]})

    demoted = demote_shared_coordinates([e for e, _ in extracted])
    if demoted:
        disc.notes.append(f"{demoted} fichas con coordenadas compartidas (probable oficina) pasadas a nivel localidad")

    with session_scope() as s:
        _persist_pages(s, source_id, disc)
        stats = _persist_listings(s, source_id, run_id, extracted, disc)
        run = s.get(CrawlRun, run_id)
        n = len(extracted)
        run.profile_version = version
        run.pages_visited = disc.pages_visited
        run.candidate_urls = disc.candidate_urls
        run.details_discovered = len(disc.details)
        run.details_processed = n
        run.valid_properties = sum(1 for e, _ in extracted if e.title and (e.price or e.area_m2))
        run.errors_count = len(errors)
        run.errors = ([{"stage": "note", "error": n} for n in disc.notes] + errors)[:200]
        run.pct_with_price = round(100 * sum(1 for e, _ in extracted if e.price) / n, 1) if n else None
        run.pct_with_area = round(100 * sum(1 for e, _ in extracted if e.area_m2) / n, 1) if n else None
        run.duration_seconds = round(time.monotonic() - started, 1)
        run.finished_at = datetime.now(UTC)
        run.possibly_broken = stats["possibly_broken"]
        run.status = "failed" if disc.blocked or (n == 0 and errors) else "partial" if (
            stats["possibly_broken"] or errors) else "success"
        if run.status in ("success", "partial") and n:
            s.get(Source, source_id).last_success_at = run.finished_at
        new_changes = s.scalars(select(ListingChange).where(ListingChange.notified.is_(False))).all()
        stats["alerts_queued"] = queue_alerts(s, list(new_changes))
        result = {"crawl_run_id": run_id, "status": run.status, "pages_visited": run.pages_visited,
                  "details_discovered": run.details_discovered, "details_processed": n,
                  "valid_properties": run.valid_properties, "pct_with_price": run.pct_with_price,
                  "pct_with_area": run.pct_with_area, "errors": len(errors), **stats}
    with session_scope() as s:
        result["alerts_sent"] = send_pending(s)
    log.info("crawl.done", source=source_id, **{k: v for k, v in result.items() if not isinstance(v, list)})
    return result


def _persist_pages(s: Session, source_id: str, disc: DiscoveryResult) -> None:
    now = datetime.now(UTC)
    rows = [{
        "source_id": source_id, "url": r.url, "page_type": str(r.page_type), "status": r.status,
        "http_status": r.http_status, "depth": r.depth, "parent_url": r.parent_url,
        "content_hash": r.content_hash, "error": r.error,
        "last_fetched_at": now if r.status == "fetched" else None,
    } for r in disc.records.values()]
    for i in range(0, len(rows), 500):
        stmt = pg_insert(CrawledPage).values(rows[i:i + 500])
        stmt = stmt.on_conflict_do_update(
            index_elements=["source_id", "url"],
            set_={c: stmt.excluded[c] for c in ("page_type", "status", "http_status", "content_hash", "error")}
            | {"last_fetched_at": func.coalesce(stmt.excluded.last_fetched_at, CrawledPage.last_fetched_at)},
        )
        s.execute(stmt)


def _apply(listing: Listing, e: ExtractedListing) -> None:
    listing.url = e.url
    listing.title = e.title
    listing.external_listing_id = e.external_listing_id or listing.external_listing_id
    listing.property_type = e.property_type.value if e.property_type else None
    listing.operation = e.operation
    listing.price = e.price
    listing.currency = e.currency
    listing.price_usd = to_usd(e.price, e.currency)
    listing.area_m2 = e.area_m2
    listing.locality = e.location.locality
    listing.province = e.location.province
    listing.latitude = e.location.latitude
    listing.longitude = e.location.longitude
    listing.geo_precision = e.location.precision.value
    listing.water_class = e.water.water_class.value
    listing.description = e.description
    listing.photos = e.photos
    listing.data = e.model_dump(mode="json", exclude={"provenance"})
    listing.provenance = {k: v.model_dump() for k, v in e.provenance.items()}
    listing.confidence = e.confidence


def _find_existing(s: Session, source_id: str, e: ExtractedListing) -> Listing | None:
    if e.external_listing_id:
        hit = s.scalar(select(Listing).where(Listing.source_id == source_id,
                                             Listing.external_listing_id == e.external_listing_id))
        if hit:
            return hit
    return s.scalar(select(Listing).where(Listing.source_id == source_id, Listing.canonical_url == e.canonical_url))


def _persist_listings(s: Session, source_id: str, run_id: int, extracted: list[tuple[ExtractedListing, str]],
                      disc: DiscoveryResult) -> dict[str, Any]:
    settings = get_settings()
    now = datetime.now(UTC)
    seen_ids: set[int] = set()
    created = updated = unchanged = 0
    touched: list[Listing] = []
    for e, raw_html in extracted:
        payload = e.snapshot_payload()
        h = content_hash(payload)
        listing = _find_existing(s, source_id, e)
        if listing is None:
            listing = Listing(source_id=source_id, canonical_url=e.canonical_url, url=e.url, status="active",
                              first_seen_at=now, last_seen_at=now, last_checked_at=now, missed_runs=0)
            _apply(listing, e)
            listing.content_hash = h
            s.add(listing)
            s.flush()
            s.add(ListingSnapshot(listing_id=listing.id, crawl_run_id=run_id, content_hash=h, data=payload,
                                  raw_html_gz=gzip.compress(raw_html.encode("utf-8", "ignore"))))
            s.add(ListingChange(listing_id=listing.id, change_type=ChangeType.NEW_LISTING,
                                new_value={"price": e.price, "currency": e.currency, "area_m2": e.area_m2}))
            created += 1
        else:
            if listing.status == "removed":
                s.add(ListingChange(listing_id=listing.id, change_type=ChangeType.RELISTED,
                                    new_value={"price": e.price, "currency": e.currency}))
            listing.status = "active"
            listing.missed_runs = 0
            listing.last_seen_at = listing.last_checked_at = now
            if listing.content_hash != h:
                last = s.scalar(select(ListingSnapshot).where(ListingSnapshot.listing_id == listing.id)
                                .order_by(ListingSnapshot.captured_at.desc()))
                for ch in diff_snapshots(last.data if last else {}, payload):
                    s.add(ListingChange(listing_id=listing.id, change_type=ch.change_type, old_value=ch.old_value,
                                        new_value=ch.new_value, pct_change=ch.pct_change))
                s.add(ListingSnapshot(listing_id=listing.id, crawl_run_id=run_id, content_hash=h, data=payload,
                                      raw_html_gz=gzip.compress(raw_html.encode("utf-8", "ignore"))))
                _apply(listing, e)
                listing.content_hash = h
                updated += 1
            else:
                unchanged += 1  # solo last_checked_at; sin snapshot duplicado
        seen_ids.add(listing.id)
        touched.append(listing)

    # --- Salud de la corrida y posibles bajas
    prev_counts = s.scalars(select(CrawlRun.details_discovered).where(
        CrawlRun.source_id == source_id, CrawlRun.status == "success", CrawlRun.id != run_id)
        .order_by(CrawlRun.started_at.desc()).limit(5)).all()
    typical = sorted(prev_counts)[len(prev_counts) // 2] if prev_counts else None
    found = len(disc.details)
    possibly_broken = bool(typical and found < typical * settings.broken_run_ratio) or disc.blocked
    budget_exhausted = disc.window_closed or \
        disc.pages_visited >= (disc.page_budget or _source_budget(s, source_id))
    missing_marked = removed = 0
    if not possibly_broken and not budget_exhausted and found > 0:
        active = s.scalars(select(Listing).where(Listing.source_id == source_id,
                                                 Listing.status.in_(("active", "missing")))).all()
        for lst in active:
            if lst.id in seen_ids:
                continue
            lst.missed_runs += 1
            lst.last_checked_at = now
            if lst.missed_runs >= settings.removal_missed_runs:
                lst.status = "removed"
                s.add(ListingChange(listing_id=lst.id, change_type=ChangeType.REMOVED,
                                    old_value={"last_seen_at": lst.last_seen_at.isoformat()}))
                removed += 1
            else:
                lst.status = "missing"
                missing_marked += 1

    s.flush()
    dedup = _link_properties(s, touched)
    return {"created": created, "updated": updated, "unchanged": unchanged, "missing": missing_marked,
            "removed": removed, "possibly_broken": possibly_broken, "typical_details": typical,
            "budget_exhausted": budget_exhausted, **dedup}


def _source_budget(s: Session, source_id: str) -> int:
    return s.get(Source, source_id).max_pages_per_run


def _features(lst: Listing) -> ListingFeatures:
    return ListingFeatures(id=lst.id, source_id=lst.source_id, locality=lst.locality, latitude=lst.latitude,
                           longitude=lst.longitude, geo_precision=lst.geo_precision, area_m2=lst.area_m2,
                           price_usd=lst.price_usd, title=lst.title, description=lst.description,
                           photos=lst.photos or [])


def _link_properties(s: Session, listings: list[Listing]) -> dict[str, int]:
    """Asigna cada anuncio a una propiedad física; duplicados fuertes se unen, ambiguos van a revisión."""
    merged = queued = 0
    for lst in listings:
        if lst.property_id:
            continue
        cands = s.scalars(select(Listing).where(
            Listing.source_id != lst.source_id, Listing.property_id.is_not(None),
            Listing.locality == lst.locality if lst.locality else Listing.id.is_(None))).all()
        best: tuple[float, Listing | None, dict[str, Any]] = (0.0, None, {})
        for c in cands:
            sc, reasons = score_pair(_features(lst), _features(c))
            if sc > best[0]:
                best = (sc, c, reasons)
            verdict = decide(sc)
            if verdict == "pending":
                a, b = sorted((lst.id, c.id))
                s.execute(pg_insert(DedupCandidate).values(listing_a_id=a, listing_b_id=b, score=sc, reasons=reasons,
                                                           status="pending").on_conflict_do_nothing())
                queued += 1
        if best[1] is not None and decide(best[0]) == "auto_merged":
            lst.property_id = best[1].property_id
            a, b = sorted((lst.id, best[1].id))
            s.execute(pg_insert(DedupCandidate).values(listing_a_id=a, listing_b_id=b, score=best[0],
                                                       reasons=best[2], status="auto_merged").on_conflict_do_nothing())
            merged += 1
        else:
            prop = Property(property_type=lst.property_type, province=lst.province, locality=lst.locality,
                            latitude=lst.latitude, longitude=lst.longitude, geo_precision=lst.geo_precision,
                            area_m2=lst.area_m2,
                            location=f"SRID=4326;POINT({lst.longitude} {lst.latitude})" if lst.latitude else None)
            s.add(prop)
            s.flush()
            lst.property_id = prop.id
    return {"dedup_auto_merged": merged, "dedup_review_queued": queued}
