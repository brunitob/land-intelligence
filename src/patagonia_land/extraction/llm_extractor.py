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
# Si la API rechaza el pedido por configuración (400/401/403/404), no tiene sentido reintentar en cada ficha:
# se apaga el fallback para el resto del proceso y queda registrado.
_disabled: str | None = None

SYSTEM = """Sos un extractor de datos de fichas inmobiliarias de la Patagonia argentina.
Devolvé SOLO datos que aparezcan explícitamente en el texto. Si un dato no está, devolvé "" (texto),
0 (número) o "desconocido" (categoría).
No infieras coordenadas, precios ni superficies. Para cada valor, copiá en *_evidence el fragmento
literal (máx. 150 caracteres) del texto que lo respalda. Distinguí: costa propia sobre el agua,
acceso al agua, solo vista al agua y cercanía al agua; no los confundas."""


# Esquema plano y sin uniones con null: la API rechaza esquemas con muchos campos opcionales ("Schema is too
# complex"). "No está en el texto" se expresa con "" (textos), 0 (números) o "desconocido" (enums).
class LLMListing(BaseModel):
    property_type: Literal["terreno", "lote", "chacra", "campo", "casa", "departamento", "cabaña", "local", "otro",
                           "desconocido"]
    property_type_evidence: str
    price: float = Field(description="Precio total publicado; 0 si no figura")
    currency: Literal["USD", "ARS", "desconocido"]
    price_evidence: str
    area_m2: float = Field(description="Superficie del terreno en m² (1 ha = 10000 m²); 0 si no figura")
    area_evidence: str
    locality: str
    location_reference: str = Field(description="Barrio, paraje, km de ruta, etc.; vacío si no figura")
    location_evidence: str
    water_relation: Literal["costa_propia", "acceso", "vista", "cercania", "ninguna_mencion"]
    water_name: str
    water_evidence: str


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
    global _disabled
    if not settings.llm_available or not missing or _disabled:
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
            # Extracción simple: sin razonamiento extendido (más barato y rápido; Haiku 5.5 lo admite).
            **({"thinking": {"type": "disabled"}} if "haiku" in settings.llm_model else {}),
            messages=[{"role": "user", "content": f"Campos faltantes prioritarios: {', '.join(missing)}\n\n{body}"}],
            output_format=LLMListing,
        )
    except anthropic.APIStatusError as exc:
        d.warnings.append(f"LLM error {exc.status_code}")
        log.warning("llm.error", status=exc.status_code, error=str(exc))
        if exc.status_code in (400, 401, 403, 404):
            _disabled = f"{exc.status_code}: {str(exc)[:200]}"
            log.error("llm.disabled", reason=_disabled)
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
    if out.property_type != "desconocido" and _supported(out.property_type_evidence, full):
        d.offer("property_type", out.property_type, m, out.property_type_evidence, 0.7)
    if out.price and _supported(out.price_evidence, full):
        d.offer("price", out.price, m, out.price_evidence, 0.7)
        if out.currency != "desconocido":
            d.offer("currency", out.currency, m, out.price_evidence, 0.65)
    if out.area_m2 and _supported(out.area_evidence, full):
        d.offer("area_m2", out.area_m2, m, out.area_evidence, 0.7)
    if out.locality and _supported(out.location_evidence, full):
        d.offer("locality_hint", out.locality, m, out.location_evidence, 0.65)
        if out.location_reference:
            d.offer("location_text", out.location_reference, m, out.location_evidence, 0.6)
    if out.water_relation and out.water_relation != "ninguna_mencion" and _supported(out.water_evidence, full):
        d.offer("llm_water", {"relation": out.water_relation, "name": out.water_name or None}, m,
                out.water_evidence, 0.6)
    for k in ("price", "area_m2"):
        ev = getattr(out, "price_evidence" if k == "price" else "area_evidence")
        if getattr(out, k) and not _supported(ev, full):
            d.warnings.append(f"LLM propuso {k} sin evidencia literal: descartado")
    return True
