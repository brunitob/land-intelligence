"""Plataformas inmobiliarias conocidas: huella + pistas de rastreo que el HTML no expone.

Solo se agregan pistas verificadas a mano contra sitios reales; el resto lo resuelve el inspector genérico.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

_FINGERPRINTS = {
    # Tokko Broker "TFW": listados server-side en /Venta, /Terrenos…; fichas /p/<id>-slug; scroll infinito
    # que pide ?p=N (fragmento HTML de tarjetas) hasta devolver "--NoMoreProperties--".
    "tokko": re.compile(r"static\.tokkobroker\.com/tfw/", re.IGNORECASE),
}

_HINTS: dict[str, dict[str, Any]] = {
    "tokko": {
        "entry_paths": ["/Venta"],
        "pagination": {"type": "query_parameter", "parameter": "p", "source": "platform:tokko"},
        "listing_patterns": ["/p/"],
        # Solo fichas /p/…; no seguir el menú de categorías (todas están contenidas en /Venta).
        "detail_pattern_strict": True,
        "follow_links": "cards_and_pagination",
    },
}


def detect_platform(html: str) -> str | None:
    for name, rx in _FINGERPRINTS.items():
        if rx.search(html):
            return name
    return None


def platform_hints(platform: str | None, base_url: str) -> dict[str, Any]:
    if not platform or platform not in _HINTS:
        return {}
    h = dict(_HINTS[platform])
    h["entry_urls"] = [urljoin(base_url.rstrip("/") + "/", p.lstrip("/")) for p in h.pop("entry_paths", [])]
    return h
