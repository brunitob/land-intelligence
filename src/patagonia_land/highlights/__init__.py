"""Destacados: listas con nombre, filtros editables y asignación manual de anuncios."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import and_, false, func, literal, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from patagonia_land.db.models import Highlight, HighlightListing, Listing
from patagonia_land.geo.localities import zones as zone_index
from patagonia_land.intelligence.normalization import strip_accents

ACTIVE_STATUSES = ("active", "missing")
_ACCENTED, _PLAIN = "áéíóúüñàèìòù", "aeiouunaeiou"


def normalize_keyword(k: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(k.lower())).strip()


def _plain_text() -> ColumnElement[str]:
    """Título + descripción en minúsculas y sin tildes (sin depender de la extensión unaccent)."""
    txt = func.coalesce(Listing.title, "") + literal(" ") + func.coalesce(Listing.description, "")
    return func.translate(func.lower(txt), _ACCENTED, _PLAIN)


def keyword_regex(k: str) -> str:
    """Palabra completa, admitiendo plural: 'lago' → lago/lagos; 'hectarea' → hectareas. Nunca 'ha' en 'hay'."""
    return rf"\m{re.escape(normalize_keyword(k))}(s|es)?\M"


def filter_condition(h: Highlight) -> ColumnElement[bool] | None:
    """Condición SQL de los filtros del destacado; None si no tiene filtros (solo anuncios fijados)."""
    conds: list[ColumnElement[bool]] = []
    kws = [normalize_keyword(k) for k in h.keywords or [] if normalize_keyword(k)]
    if kws:
        text = _plain_text()
        parts = [text.op("~")(keyword_regex(k)) for k in kws]
        conds.append(and_(*parts) if h.match_mode == "all" else or_(*parts))
    if h.zones:
        idx = zone_index()
        names = [n for z in h.zones for n in idx.get(z, [])]
        conds.append(Listing.locality.in_(names) if names else false())
    if h.property_types:
        conds.append(Listing.property_type.in_(h.property_types))
    if h.water_classes:
        conds.append(Listing.water_class.in_(h.water_classes))
    if h.max_price_usd:
        conds.append(Listing.price_usd <= h.max_price_usd)
    if h.min_area_m2:
        conds.append(Listing.area_m2 >= h.min_area_m2)
    if not conds:
        return None
    if not h.include_rentals:
        conds.append(or_(Listing.operation.is_(None), Listing.operation != "alquiler"))
    return and_(*conds)


def highlight_listings(s: Session, h: Highlight) -> list[tuple[Listing, str]]:
    """Anuncios del destacado con su origen: 'fijado' (manual) o 'filtro'. Los excluidos a mano no aparecen."""
    manual = {r.listing_id: r.mode for r in s.scalars(select(HighlightListing)
                                                     .where(HighlightListing.highlight_id == h.id))}
    pinned = [lid for lid, m in manual.items() if m == "pinned"]
    excluded = [lid for lid, m in manual.items() if m == "excluded"]
    cond = filter_condition(h)
    parts = [Listing.id.in_(pinned)] if pinned else []
    if cond is not None:
        parts.append(and_(cond, Listing.id.not_in(excluded)) if excluded else cond)
    if not parts:
        return []
    rows = s.scalars(select(Listing).where(Listing.status.in_(ACTIVE_STATUSES), or_(*parts))
                     .order_by(Listing.last_seen_at.desc())).all()
    return [(lst, "fijado" if manual.get(lst.id) == "pinned" else "filtro") for lst in rows]


def counts(s: Session, h: Highlight) -> dict[str, Any]:
    rows = highlight_listings(s, h)
    return {"total": len(rows), "fijados": sum(o == "fijado" for _, o in rows),
            "excluidos": s.scalar(select(func.count()).select_from(HighlightListing).where(
                HighlightListing.highlight_id == h.id, HighlightListing.mode == "excluded")) or 0}
