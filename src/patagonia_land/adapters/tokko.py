"""Adaptador para sitios de Tokko Broker (TFW), detectados por huella en el perfil (profile.platform == 'tokko').

Lo que el genérico no obtiene:
- Ubicación del mapa Leaflet. Tokko suele publicar un CÍRCULO (radio en metros) alrededor de la zona, no el
  punto exacto: se guarda como precisión 'approximate'. Solo un marcador (L.marker) cuenta como 'exact'.
- Campo "Ubicación" de la ficha (barrio/zona) como texto de ubicación.
"""

from __future__ import annotations

import re
from typing import Any

from patagonia_land.adapters.base import SiteAdapter, register
from patagonia_land.crawling.page import Page
from patagonia_land.extraction.draft import Draft

NUM = r"(-?\d{1,2}\.\d{3,})"
CIRCLE_RE = re.compile(rf"L\.circle\(\s*\[\s*{NUM}\s*,\s*{NUM}\s*\]\s*,\s*(\d+)")
MARKER_RE = re.compile(rf"L\.marker\(\s*\[\s*{NUM}\s*,\s*{NUM}\s*\]")


@register
class TokkoAdapter(SiteAdapter):
    platforms = ("tokko",)

    def extract(self, page: Page, draft: Draft, profile: dict[str, Any]) -> None:
        mapa = page.soup.select_one("#ficha_mapa")
        scripts = " ".join(s.get_text() for s in (mapa.find_all("script") if mapa else []))
        m = MARKER_RE.search(scripts)
        c = CIRCLE_RE.search(scripts)
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
            draft.offer("latitude", lat, "adapter:tokko", f"L.marker([{lat}, {lon}])", 0.85)
            draft.offer("longitude", lon, "adapter:tokko", f"L.marker([{lat}, {lon}])", 0.85)
            draft.offer("geo_precision", "exact", "adapter:tokko", confidence=0.7)
        elif c:
            lat, lon, radius = float(c.group(1)), float(c.group(2)), int(c.group(3))
            ev = f"L.circle([{lat}, {lon}], {radius} m): zona aproximada publicada por el sitio"
            draft.offer("latitude", lat, "adapter:tokko", ev, 0.6)
            draft.offer("longitude", lon, "adapter:tokko", ev, 0.6)
            draft.offer("geo_precision", "approximate", "adapter:tokko", ev, 0.6)
            draft.offer("geo_radius_m", radius, "adapter:tokko", ev, 0.6)
        for item in page.soup.select(".ficha_detalle_item"):
            b = item.find("b")
            if b and b.get_text(strip=True).lower() == "ubicación":
                val = item.get_text(" ", strip=True)[len(b.get_text(strip=True)):].strip()
                draft.offer("location_text", val, "adapter:tokko", f"Ubicación: {val}", 0.85)
                break
