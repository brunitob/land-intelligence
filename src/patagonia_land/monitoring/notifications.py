"""Alertas por Telegram, configurables en config/alerts.yaml."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from patagonia_land.config import get_settings, load_yaml
from patagonia_land.db.models import Alert, Listing, ListingChange, PropertyGeoAnalysis

log = structlog.get_logger()

EMOJI = {"new_listing": "🆕", "price_decreased": "📉", "price_increased": "📈", "removed": "❌",
         "relisted": "♻️", "area_changed": "📐", "description_changed": "✏️", "status_changed": "🏷️"}


def _rules() -> list[dict[str, Any]]:
    return load_yaml("alerts.yaml").get("alerts", [])


def _matches(rule: dict[str, Any], change: ListingChange, listing: Listing, airports: set[str]) -> bool:
    if rule.get("change_types") and change.change_type not in rule["change_types"]:
        return False
    if rule.get("property_types") and listing.property_type not in rule["property_types"]:
        return False
    if rule.get("max_price_usd") and listing.price_usd and float(listing.price_usd) > rule["max_price_usd"]:
        return False
    if rule.get("min_area_m2") and (listing.area_m2 or 0) < rule["min_area_m2"]:
        return False
    if rule.get("water_classes") and listing.water_class not in rule["water_classes"]:
        return False
    if rule.get("min_pct_change") and change.pct_change is not None \
            and abs(change.pct_change) < rule["min_pct_change"]:
        return False
    if rule.get("airports") and airports and not (set(rule["airports"]) & airports):
        return False
    return True


def format_message(change: ListingChange, listing: Listing) -> str:
    parts = [f"{EMOJI.get(change.change_type, '•')} *{change.change_type.replace('_', ' ')}* — {listing.title or ''}"]
    if listing.price:
        parts.append(f"Precio: {listing.currency or ''} {float(listing.price):,.0f}".replace(",", "."))
    if change.pct_change is not None:
        parts.append(f"Variación: {change.pct_change:+.1f}%")
    if listing.area_m2:
        ha = listing.area_m2 / 10_000
        parts.append(f"Superficie: {ha:,.2f} ha" if ha >= 1 else f"Superficie: {listing.area_m2:,.0f} m²")
    if listing.locality:
        parts.append(f"Ubicación: {listing.locality} ({listing.geo_precision})")
    if listing.water_class and listing.water_class != "unknown":
        parts.append(f"Agua: {listing.water_class}")
    parts.append(listing.url)
    if listing.latitude and listing.geo_precision == "exact":
        parts.append(f"https://www.openstreetmap.org/?mlat={listing.latitude}&mlon={listing.longitude}#map=15/"
                     f"{listing.latitude}/{listing.longitude}")
    return "\n".join(parts)


def queue_alerts(session: Session, changes: list[ListingChange]) -> int:
    rules = _rules()
    n = 0
    for ch in changes:
        listing = session.get(Listing, ch.listing_id)
        if not listing:
            continue
        airports: set[str] = set()
        if listing.property_id:
            airports = {g.airport_code for g in session.scalars(select(PropertyGeoAnalysis).where(
                PropertyGeoAnalysis.property_id == listing.property_id, PropertyGeoAnalysis.within_isochrone.is_(True)))}
        if any(_matches(r, ch, listing, airports) for r in rules):
            session.add(Alert(change_id=ch.id, message=format_message(ch, listing)))
            n += 1
        ch.notified = True
    return n


def send_pending(session: Session, limit: int = 30) -> int:
    s = get_settings()
    pending = session.scalars(select(Alert).where(Alert.status == "pending").limit(limit)).all()
    if not pending:
        return 0
    if not (s.telegram_bot_token and s.telegram_chat_id):
        for a in pending:
            a.status = "skipped"
            a.error = "Telegram no configurado"
        return 0
    sent = 0
    with httpx.Client(timeout=15) as client:
        for a in pending:
            try:
                r = client.post(f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
                                json={"chat_id": s.telegram_chat_id, "text": a.message, "parse_mode": "Markdown",
                                      "disable_web_page_preview": False})
                r.raise_for_status()
                a.status, a.sent_at = "sent", datetime.now(UTC)
                sent += 1
            except httpx.HTTPError as exc:
                a.status, a.error = "failed", str(exc)[:500]
                log.warning("telegram.error", error=str(exc))
    return sent
