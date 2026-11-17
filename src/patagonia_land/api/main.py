"""API FastAPI (sección 11). Procesos largos se encolan como jobs consultables."""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session

from patagonia_land import highlights as hl
from patagonia_land import jobs
from patagonia_land.config import get_settings, load_yaml
from patagonia_land.crawling.fetcher import FetchError, assert_public_url
from patagonia_land.db.models import (
    Airport,
    CrawlRun,
    DedupCandidate,
    Highlight,
    HighlightListing,
    Job,
    Listing,
    ListingChange,
    ListingSnapshot,
    PropertyGeoAnalysis,
    SiteProfile,
    Source,
)
from patagonia_land.db.session import get_session
from patagonia_land.geo.localities import LOCALITIES
from patagonia_land.geo.localities import zones as zone_index

app = FastAPI(title="Patagonia Land Intelligence", version="0.1.0")


def auth(authorization: str | None = Header(default=None)) -> None:
    token = get_settings().api_token
    if token and token != "change-me" and authorization != f"Bearer {token}":
        raise HTTPException(401, "token inválido")


# scope="function": commit ANTES de responder. Con el default el commit corría después de enviar la respuesta y
# un pedido inmediato del cliente (crear destacado → agregarle avisos) no veía lo recién creado (404).
DB = Depends(get_session, scope="function")
AUTH = [Depends(auth)]


# ----------------------------------------------------------------------------- utilidades
def _row(obj: Any, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    out = {}
    for c in obj.__table__.columns:
        if c.name in exclude or c.name in ("location", "geom", "raw_html_gz"):
            continue
        v = getattr(obj, c.name)
        out[c.name] = float(v) if v is not None and c.type.__class__.__name__ == "Numeric" else v
    return out


def _slug(url: str) -> str:
    host = urlsplit(url).netloc.lower().removeprefix("www.")
    return re.sub(r"[^a-z0-9]+", "_", host).strip("_")[:100]


# ----------------------------------------------------------------------------- health
@app.get("/health")
def health(s: Session = DB) -> dict[str, Any]:
    s.execute(text("SELECT 1"))
    return {"status": "ok"}


# ----------------------------------------------------------------------------- sources
class SourceIn(BaseModel):
    base_url: HttpUrl
    name: str | None = None
    id: str | None = Field(default=None, pattern=r"^[a-z0-9_]{3,100}$")
    start_urls: list[HttpUrl] = []
    region: str | None = Field(default=None, pattern=r"^(bariloche|chapelco|esquel)$")
    crawl_interval_hours: int = Field(default=24, ge=1, le=24 * 30)
    max_pages_per_run: int = Field(default=200, ge=5, le=5000)
    max_depth: int = Field(default=5, ge=1, le=12)
    enabled: bool = True
    inspect_now: bool = True


class SourcePatch(BaseModel):
    name: str | None = None
    start_urls: list[HttpUrl] | None = None
    enabled: bool | None = None
    crawl_interval_hours: int | None = Field(default=None, ge=1)
    max_pages_per_run: int | None = Field(default=None, ge=5, le=5000)
    max_depth: int | None = Field(default=None, ge=1, le=12)
    manual_overrides: dict[str, Any] | None = None


@app.post("/sources", dependencies=AUTH, status_code=201)
def create_source(body: SourceIn, s: Session = DB) -> dict[str, Any]:
    base = str(body.base_url).rstrip("/")
    try:
        assert_public_url(base)
    except FetchError as exc:
        raise HTTPException(400, f"URL no permitida: {exc}") from exc
    sid = body.id or _slug(base)
    if s.get(Source, sid):
        raise HTTPException(409, f"ya existe la fuente {sid}")
    src = Source(id=sid, name=body.name or urlsplit(base).netloc, base_url=base,
                 start_urls=[str(u) for u in body.start_urls], region=body.region, enabled=body.enabled,
                 crawl_interval_hours=body.crawl_interval_hours, max_pages_per_run=body.max_pages_per_run,
                 max_depth=body.max_depth, manual_overrides={})
    s.add(src)
    s.flush()
    out = _row(src)
    if body.inspect_now:
        out["job"] = _row(jobs.enqueue(s, "inspect", sid))
    return out


@app.get("/sources", dependencies=AUTH)
def list_sources(s: Session = DB) -> list[dict[str, Any]]:
    out = []
    for src in s.scalars(select(Source).order_by(Source.created_at)):
        row = _row(src)
        last = s.scalar(select(CrawlRun).where(CrawlRun.source_id == src.id).order_by(CrawlRun.started_at.desc()))
        row["last_run"] = _row(last, exclude=("errors",)) if last else None
        row["active_listings"] = s.scalar(select(func.count()).select_from(Listing).where(
            Listing.source_id == src.id, Listing.status == "active"))
        prof = s.scalar(select(SiteProfile).where(SiteProfile.source_id == src.id, SiteProfile.active.is_(True))
                        .order_by(SiteProfile.version.desc()))
        row["profile"] = {"version": prof.version, "origin": prof.origin, "confidence": prof.confidence} if prof else None
        out.append(row)
    return out


def _source_or_404(s: Session, source_id: str) -> Source:
    src = s.get(Source, source_id)
    if not src:
        raise HTTPException(404, "fuente no encontrada")
    return src


@app.get("/sources/{source_id}", dependencies=AUTH)
def get_source(source_id: str, s: Session = DB) -> dict[str, Any]:
    src = _source_or_404(s, source_id)
    row = _row(src)
    row["profiles"] = [_row(p) for p in s.scalars(select(SiteProfile).where(SiteProfile.source_id == source_id)
                                                  .order_by(SiteProfile.version.desc()).limit(10))]
    row["page_types"] = dict(s.execute(text(
        "SELECT page_type, count(*) FROM crawled_pages WHERE source_id = :s GROUP BY page_type"),
        {"s": source_id}).all())
    return row


@app.patch("/sources/{source_id}", dependencies=AUTH)
def patch_source(source_id: str, body: SourcePatch, s: Session = DB) -> dict[str, Any]:
    src = _source_or_404(s, source_id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(src, k, [str(u) for u in v] if k == "start_urls" else v)
    return _row(src)


@app.post("/sources/{source_id}/inspect", dependencies=AUTH, status_code=202)
def inspect_source(source_id: str, s: Session = DB) -> dict[str, Any]:
    _source_or_404(s, source_id)
    return _row(jobs.enqueue(s, "inspect", source_id))


@app.post("/sources/{source_id}/crawl", dependencies=AUTH, status_code=202)
def crawl_source(source_id: str, s: Session = DB) -> dict[str, Any]:
    _source_or_404(s, source_id)
    return _row(jobs.enqueue(s, "crawl", source_id))


@app.get("/sources/{source_id}/runs", dependencies=AUTH)
def source_runs(source_id: str, limit: int = 20, s: Session = DB) -> list[dict[str, Any]]:
    return [_row(r) for r in s.scalars(select(CrawlRun).where(CrawlRun.source_id == source_id)
                                       .order_by(CrawlRun.started_at.desc()).limit(limit))]


@app.post("/sources/{source_id}/profile", dependencies=AUTH, status_code=201)
def set_manual_profile(source_id: str, profile: dict[str, Any], s: Session = DB) -> dict[str, Any]:
    """Override manual del SiteProfile: nunca será pisado por perfiles auto-generados."""
    _source_or_404(s, source_id)
    last = s.scalar(select(func.max(SiteProfile.version)).where(SiteProfile.source_id == source_id)) or 0
    sp = SiteProfile(source_id=source_id, version=last + 1, origin="manual", profile=profile,
                     confidence=1.0, active=True)
    s.add(sp)
    s.flush()
    return _row(sp)


# ----------------------------------------------------------------------------- jobs
@app.get("/jobs/{job_id}", dependencies=AUTH)
def get_job(job_id: int, s: Session = DB) -> dict[str, Any]:
    job = s.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job no encontrado")
    return _row(job)


@app.get("/jobs", dependencies=AUTH)
def list_jobs(limit: int = 30, s: Session = DB) -> list[dict[str, Any]]:
    return [_row(j, exclude=("result",)) for j in s.scalars(select(Job).order_by(Job.created_at.desc()).limit(limit))]


# ----------------------------------------------------------------------------- properties
def _search_defaults() -> dict[str, Any]:
    return load_yaml("search.yaml").get("search", {})


@app.get("/search/defaults", dependencies=AUTH)
def search_defaults() -> dict[str, Any]:
    return _search_defaults()


@app.get("/properties", dependencies=AUTH)
def list_properties(
    s: Session = DB,
    property_types: list[str] | None = Query(default=None),
    max_price_usd: float | None = None,
    min_area_m2: float | None = None,
    airports: list[str] | None = Query(default=None),
    water_classes: list[str] | None = Query(default=None),
    waterfront_only: bool = False,
    include_unknown_location: bool = True,
    include_no_price: bool = True,
    include_rentals: bool = False,
    status: list[str] | None = Query(default=None),
    source_id: str | None = None,
    zones: list[str] | None = Query(default=None),
    q: str | None = None,
    limit: int = Query(default=200, le=2000),
    offset: int = 0,
) -> dict[str, Any]:
    """Filtros sobre datos ya recopilados: cambiarlos no requiere volver a scrapear."""
    stmt = select(Listing)
    stmt = stmt.where(Listing.status.in_(status or ["active", "missing"]))
    if not include_rentals:
        stmt = stmt.where(or_(Listing.operation.is_(None), Listing.operation != "alquiler"))
    if property_types:
        stmt = stmt.where(Listing.property_type.in_(property_types))
    if max_price_usd:
        cond = Listing.price_usd <= max_price_usd
        stmt = stmt.where(or_(cond, Listing.price_usd.is_(None)) if include_no_price else cond)
    if min_area_m2:
        stmt = stmt.where(Listing.area_m2 >= min_area_m2)
    if waterfront_only:
        stmt = stmt.where(Listing.water_class.in_(["waterfront_confirmed", "waterfront_claimed"]))
    elif water_classes:
        stmt = stmt.where(Listing.water_class.in_(water_classes))
    if not include_unknown_location:
        stmt = stmt.where(Listing.geo_precision.in_(["exact", "approximate"]))
    if source_id:
        stmt = stmt.where(Listing.source_id == source_id)
    if zones:
        by_zone = zone_index()
        bad = [z for z in zones if z not in by_zone]
        if bad:
            raise HTTPException(400, f"Zonas desconocidas: {bad}")
        stmt = stmt.where(Listing.locality.in_([name for z in zones for name in by_zone[z]]))
    if q:
        stmt = stmt.where(or_(Listing.title.ilike(f"%{q}%"), Listing.description.ilike(f"%{q}%")))
    allowed = {"BRC", "CPC", "EQS"}
    if airports:
        bad = set(airports) - allowed
        if bad:
            raise HTTPException(400, f"Aeropuertos no habilitados en V1: {sorted(bad)}")
        has_iso = _has_drive_analysis(s)
        if has_iso:
            # Dentro del tiempo máximo de manejo (config/airports.yaml) de alguno de los aeropuertos elegidos.
            sub = select(PropertyGeoAnalysis.property_id).where(
                PropertyGeoAnalysis.airport_code.in_(airports), PropertyGeoAnalysis.within_isochrone.is_(True))
            cond = Listing.property_id.in_(sub)
            stmt = stmt.where(or_(cond, Listing.geo_precision == "unknown") if include_unknown_location else cond)
        else:
            # Sin tiempos de manejo aún (falta ORS_API_KEY): aproximación declarada. Con localidad, cuenta la región
            # de la localidad en el gazetteer; sin localidad, la región de la inmobiliaria.
            regions = {"BRC": "bariloche", "CPC": "chapelco", "EQS": "esquel"}
            wanted = {regions[a] for a in airports}
            names = [loc.name for loc in LOCALITIES if loc.region in wanted]
            src_ids = select(Source.id).where(Source.region.in_(wanted))
            stmt = stmt.where(or_(Listing.locality.in_(names),
                                  and_(Listing.locality.is_(None), Listing.source_id.in_(src_ids))))
    total = s.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = s.scalars(stmt.order_by(Listing.last_seen_at.desc()).offset(offset).limit(limit)).all()
    items = []
    for lst in rows:
        r = _row(lst, exclude=("data", "provenance", "description"))
        r["price_per_ha_usd"] = round(float(lst.price_usd) / (lst.area_m2 / 10_000), 0) \
            if lst.price_usd and lst.area_m2 else None
        r["warnings"] = (lst.data or {}).get("warnings", [])
        items.append(r)
    return {"total": total, "items": items, "airport_filter_mode": "isochrone" if airports and
            _has_drive_analysis(s) else "region" if airports else None}


@app.get("/properties/{property_id}", dependencies=AUTH)
def get_property(property_id: int, s: Session = DB) -> dict[str, Any]:
    listings = s.scalars(select(Listing).where(Listing.property_id == property_id)).all()
    if not listings:
        raise HTTPException(404, "propiedad no encontrada")
    geo = s.scalars(select(PropertyGeoAnalysis).where(PropertyGeoAnalysis.property_id == property_id)).all()
    return {"property_id": property_id, "listings": [_row(x) for x in listings], "geo": [_row(g) for g in geo]}


@app.get("/properties/{property_id}/history", dependencies=AUTH)
def property_history(property_id: int, s: Session = DB) -> list[dict[str, Any]]:
    ids = select(Listing.id).where(Listing.property_id == property_id)
    snaps = s.scalars(select(ListingSnapshot).where(ListingSnapshot.listing_id.in_(ids))
                      .order_by(ListingSnapshot.captured_at)).all()
    return [{"listing_id": x.listing_id, "captured_at": x.captured_at, "price": x.data.get("price"),
             "currency": x.data.get("currency"), "area_m2": x.data.get("area_m2")} for x in snaps]


@app.get("/listings/{listing_id}", dependencies=AUTH)
def get_listing(listing_id: int, s: Session = DB) -> dict[str, Any]:
    lst = s.get(Listing, listing_id)
    if not lst:
        raise HTTPException(404, "anuncio no encontrado")
    out = _row(lst)
    out["changes"] = [_row(c) for c in s.scalars(select(ListingChange).where(ListingChange.listing_id == listing_id)
                                                 .order_by(ListingChange.detected_at.desc()))]
    out["snapshots"] = [{"id": x.id, "captured_at": x.captured_at, "content_hash": x.content_hash, "data": x.data}
                        for x in s.scalars(select(ListingSnapshot).where(ListingSnapshot.listing_id == listing_id)
                                           .order_by(ListingSnapshot.captured_at.desc()))]
    return out


@app.get("/changes", dependencies=AUTH)
def list_changes(change_types: list[str] | None = Query(default=None), limit: int = 100,
                 s: Session = DB) -> list[dict[str, Any]]:
    stmt = select(ListingChange, Listing).join(Listing, Listing.id == ListingChange.listing_id)
    if change_types:
        stmt = stmt.where(ListingChange.change_type.in_(change_types))
    out = []
    for ch, lst in s.execute(stmt.order_by(ListingChange.detected_at.desc()).limit(limit)):
        r = _row(ch)
        r.update(title=lst.title, url=lst.url, source_id=lst.source_id, locality=lst.locality)
        out.append(r)
    return out


@app.get("/dedup/pending", dependencies=AUTH)
def dedup_pending(s: Session = DB) -> list[dict[str, Any]]:
    out = []
    for c in s.scalars(select(DedupCandidate).where(DedupCandidate.status == "pending").order_by(
            DedupCandidate.score.desc())):
        a, b = s.get(Listing, c.listing_a_id), s.get(Listing, c.listing_b_id)
        out.append({**_row(c), "a": {"id": a.id, "title": a.title, "url": a.url, "source_id": a.source_id},
                    "b": {"id": b.id, "title": b.title, "url": b.url, "source_id": b.source_id}})
    return out


class DedupDecision(BaseModel):
    decision: str = Field(pattern=r"^(merge|reject)$")


@app.post("/dedup/{candidate_id}", dependencies=AUTH)
def dedup_decide(candidate_id: int, body: DedupDecision, s: Session = DB) -> dict[str, Any]:
    c = s.get(DedupCandidate, candidate_id)
    if not c:
        raise HTTPException(404)
    if body.decision == "merge":
        a, b = s.get(Listing, c.listing_a_id), s.get(Listing, c.listing_b_id)
        b.property_id = a.property_id  # los anuncios e historiales se conservan
        c.status = "merged"
    else:
        c.status = "rejected"
    return _row(c)


@app.get("/airports", dependencies=AUTH)
def list_airports(s: Session = DB) -> list[dict[str, Any]]:
    return [_row(a) for a in s.scalars(select(Airport).order_by(Airport.code))]


@app.post("/geo/analyze", dependencies=AUTH, status_code=202)
def geo_analyze(s: Session = DB) -> dict[str, Any]:
    """Encola el cálculo de tiempos de manejo a los aeropuertos (OpenRouteService)."""
    job = jobs.enqueue(s, "geo", None)
    return {"job_id": job.id, "status": job.status}


@app.get("/stats", dependencies=AUTH)
def stats(days: int = Query(default=14, ge=1, le=90), s: Session = DB) -> dict[str, Any]:
    """Métricas operativas (crawls, fuentes, cobertura) y de mercado (zonas, cambios de precio)."""
    from patagonia_land.stats import compute

    return compute(s, days)


@app.get("/zones", dependencies=AUTH)
def list_zones() -> list[dict[str, Any]]:
    return [{"zone": z, "localities": names} for z, names in zone_index().items()]


def _has_drive_analysis(s: Session) -> bool:
    return bool(s.scalar(text("SELECT count(*) FROM property_geo_analysis WHERE within_isochrone IS NOT NULL")))


@app.get("/airports/isochrones", dependencies=AUTH)
def isochrones(minutes: int = 60, s: Session = DB) -> list[dict[str, Any]]:
    rows = s.execute(text("SELECT airport_code, minutes, ST_AsGeoJSON(geom) FROM airport_isochrones "
                          "WHERE minutes = :m"), {"m": minutes}).all()
    import json

    return [{"airport_code": r[0], "minutes": r[1], "geometry": json.loads(r[2])} for r in rows]


# ----------------------------------------------------------------------------- destacados
class HighlightIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    keywords: list[str] = Field(default_factory=list)
    match_mode: Literal["any", "all"] = "any"
    zones: list[str] = Field(default_factory=list)
    property_types: list[str] = Field(default_factory=list)
    water_classes: list[str] = Field(default_factory=list)
    max_price_usd: float | None = None
    min_area_m2: float | None = None
    include_rentals: bool = False
    position: int = 0


class HighlightPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    keywords: list[str] | None = None
    match_mode: Literal["any", "all"] | None = None
    zones: list[str] | None = None
    property_types: list[str] | None = None
    water_classes: list[str] | None = None
    max_price_usd: float | None = None
    min_area_m2: float | None = None
    include_rentals: bool | None = None
    position: int | None = None


class HighlightAssign(BaseModel):
    mode: Literal["pinned", "excluded"] = "pinned"
    note: str | None = None


def _check_zones(zs: list[str] | None) -> None:
    bad = [z for z in zs or [] if z not in zone_index()]
    if bad:
        raise HTTPException(400, f"Zonas desconocidas: {bad}")


def _highlight_or_404(s: Session, highlight_id: int) -> Highlight:
    h = s.get(Highlight, highlight_id)
    if not h:
        raise HTTPException(404, "destacado no encontrado")
    return h


def _highlight_out(s: Session, h: Highlight) -> dict[str, Any]:
    return {**_row(h), **hl.counts(s, h)}


@app.get("/highlights", dependencies=AUTH)
def list_highlights(s: Session = DB) -> list[dict[str, Any]]:
    return [_highlight_out(s, h) for h in s.scalars(select(Highlight).order_by(Highlight.position, Highlight.id))]


@app.post("/highlights", dependencies=AUTH, status_code=201)
def create_highlight(body: HighlightIn, s: Session = DB) -> dict[str, Any]:
    _check_zones(body.zones)
    if s.scalar(select(Highlight).where(Highlight.name == body.name)):
        raise HTTPException(409, "ya existe un destacado con ese nombre")
    h = Highlight(**body.model_dump())
    s.add(h)
    s.flush()
    return _highlight_out(s, h)


@app.patch("/highlights/{highlight_id}", dependencies=AUTH)
def update_highlight(highlight_id: int, body: HighlightPatch, s: Session = DB) -> dict[str, Any]:
    h = _highlight_or_404(s, highlight_id)
    changes = body.model_dump(exclude_unset=True)
    _check_zones(changes.get("zones"))
    for k, v in changes.items():
        setattr(h, k, v)
    s.flush()
    return _highlight_out(s, h)


@app.delete("/highlights/{highlight_id}", dependencies=AUTH, status_code=204)
def delete_highlight(highlight_id: int, s: Session = DB) -> None:
    s.delete(_highlight_or_404(s, highlight_id))


@app.get("/highlights/{highlight_id}/listings", dependencies=AUTH)
def highlight_listing_items(highlight_id: int, s: Session = DB) -> dict[str, Any]:
    h = _highlight_or_404(s, highlight_id)
    items = []
    for lst, origin in hl.highlight_listings(s, h):
        r = _row(lst, exclude=("data", "provenance", "description"))
        r["origin"] = origin
        r["price_per_ha_usd"] = round(float(lst.price_usd) / (lst.area_m2 / 10_000), 0) \
            if lst.price_usd and lst.area_m2 else None
        items.append(r)
    excluded = s.execute(select(Listing.id, Listing.title, Listing.url).join(
        HighlightListing, HighlightListing.listing_id == Listing.id).where(
        HighlightListing.highlight_id == h.id, HighlightListing.mode == "excluded")).all()
    return {"highlight": _row(h), "total": len(items), "items": items,
            "excluded": [{"id": i, "title": t, "url": u} for i, t, u in excluded]}


@app.put("/highlights/{highlight_id}/listings/{listing_id}", dependencies=AUTH)
def assign_listing(highlight_id: int, listing_id: int, body: HighlightAssign, s: Session = DB) -> dict[str, Any]:
    _highlight_or_404(s, highlight_id)
    if not s.get(Listing, listing_id):
        raise HTTPException(404, "anuncio no encontrado")
    row = s.get(HighlightListing, (highlight_id, listing_id)) or HighlightListing(
        highlight_id=highlight_id, listing_id=listing_id)
    row.mode, row.note = body.mode, body.note
    s.add(row)
    return {"highlight_id": highlight_id, "listing_id": listing_id, "mode": body.mode}


@app.delete("/highlights/{highlight_id}/listings/{listing_id}", dependencies=AUTH, status_code=204)
def unassign_listing(highlight_id: int, listing_id: int, s: Session = DB) -> None:
    """Quita la asignación manual (fijado o excluido): el anuncio vuelve a depender solo del filtro."""
    row = s.get(HighlightListing, (highlight_id, listing_id))
    if row:
        s.delete(row)


@app.get("/listings/{listing_id}/highlights", dependencies=AUTH)
def listing_highlights(listing_id: int, s: Session = DB) -> list[dict[str, Any]]:
    """Destacados en los que aparece el anuncio (por filtro o fijado)."""
    out = []
    for h in s.scalars(select(Highlight).order_by(Highlight.position, Highlight.id)):
        hit = next((o for lst, o in hl.highlight_listings(s, h) if lst.id == listing_id), None)
        if hit:
            out.append({"id": h.id, "name": h.name, "origin": hit})
    return out
