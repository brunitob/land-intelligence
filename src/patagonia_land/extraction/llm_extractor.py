"""Fallback LLM con salida estructurada para campos faltantes o ambiguos.

Solo completa lo que los parsers determinísticos no encontraron, exige evidencia textual literal
y descarta cualquier valor cuya evidencia no aparezca en la página (anti-alucinación).
"""

from __future__ import annotations

import re
from typing import Literal

import structlog
from pydantic import BaseModel, Field

from patagonia_land.config import get_settings
from patagonia_land.extraction.draft import Draft

log = structlog.get_logger()

SYSTEM = """Sos un extractor de datos de fichas inmobiliarias de la Patagonia argentina.
Devolvé SOLO datos que aparezcan explícitamente en el texto. Si un dato no está, devolvé null.
No infieras coordenadas, precios ni superficies. Para cada valor, copiá en *_evidence el fragmento
literal (máx. 150 caracteres) del texto que lo respalda. Distinguí: costa propia sobre el agua,
acceso al agua, solo vista al agua y cercanía al agua; no los confundas."""


class LLMListing(BaseModel):
    property_type: Literal["terreno", "lote", "chacra", "campo", "casa", "departamento", "cabaña", "local", "otro"] | None = None
    property_type_evidence: str | None = None
    price: float | None = None
    currency: Literal["USD", "ARS"] | None = None
    price_evidence: str | None = None
    area_m2: float | None = Field(default=None, description="Superficie del terreno en m² (1 ha = 10000 m²)")
    area_evidence: str | None = None
    locality: str | None = None
    location_reference: str | None = Field(default=None, description="Barrio, paraje, km de ruta, etc.")
    location_evidence: str | None = None
    water_relation: Literal["costa_propia", "acceso", "vista", "cercania", "ninguna_mencion"] | None = None
    water_name: str | None = None
    water_evidence: str | None = None
    services: list[str] = Field(default_factory=list)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _supported(evidence: str | None, text: str) -> bool:
    if not evidence:
        return False
    ev = _norm(evidence)
    return len(ev) >= 4 and ev[:60] in _norm(text)


def needs_llm(d: Draft) -> list[str]:
    missing = [k for k in ("price", "area_m2", "property_type") if not d.has(k) and not
               (k == "price" and d.get("price_on_request"))]
    if not d.has("locality") and not d.has("latitude"):
        missing.append("location")
    return missing


async def extract_llm(text: str, title: str, d: Draft) -> bool:
    """Completa campos faltantes. Devuelve True si se llamó al LLM."""
    settings = get_settings()
    missing = needs_llm(d)
    if not settings.llm_available or not missing:
        return False
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    body = f"TÍTULO: {title}\n\nTEXTO DE LA FICHA:\n{text[:40_000]}"
    try:
        resp = await client.messages.parse(
            model=settings.llm_model,
            max_tokens=4000,
            system=SYSTEM,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": f"Campos faltantes prioritarios: {', '.join(missing)}\n\n{body}"}],
            output_format=LLMListing,
        )
    except anthropic.APIStatusError as exc:
        d.warnings.append(f"LLM error {exc.status_code}")
        log.warning("llm.error", status=exc.status_code, error=str(exc))
        return True
    except anthropic.APIConnectionError as exc:
        d.warnings.append("LLM sin conexión")
        log.warning("llm.connection_error", error=str(exc))
        return True
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        d.warnings.append(f"LLM sin salida ({resp.stop_reason})")
        return True
    out = resp.parsed_output
    full = f"{title} {text}"
    m = "llm"
    if out.property_type and _supported(out.property_type_evidence, full):
        d.offer("property_type", out.property_type, m, out.property_type_evidence, 0.7)
    if out.price and _supported(out.price_evidence, full):
        d.offer("price", out.price, m, out.price_evidence, 0.7)
        d.offer("currency", out.currency, m, out.price_evidence, 0.65)
    if out.area_m2 and _supported(out.area_evidence, full):
        d.offer("area_m2", out.area_m2, m, out.area_evidence, 0.7)
    if out.locality and _supported(out.location_evidence, full):
        d.offer("locality_hint", out.locality, m, out.location_evidence, 0.65)
        d.offer("location_text", out.location_reference, m, out.location_evidence, 0.6)
    if out.water_relation and out.water_relation != "ninguna_mencion" and _supported(out.water_evidence, full):
        d.offer("llm_water", {"relation": out.water_relation, "name": out.water_name}, m, out.water_evidence, 0.6)
    for k in ("price", "area_m2"):
        ev = getattr(out, "price_evidence" if k == "price" else "area_evidence")
        if getattr(out, k) and not _supported(ev, full):
            d.warnings.append(f"LLM propuso {k} sin evidencia literal: descartado")
    return True
