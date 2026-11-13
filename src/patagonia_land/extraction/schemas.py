"""Esquemas Pydantic de la ficha extraída. Desconocido = None; nunca se inventan valores."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PropertyType(StrEnum):
    TERRENO = "terreno"
    LOTE = "lote"
    CHACRA = "chacra"
    CAMPO = "campo"
    CASA = "casa"
    DEPARTAMENTO = "departamento"
    CABANA = "cabaña"
    LOCAL = "local"
    OTRO = "otro"


LAND_TYPES = {PropertyType.TERRENO, PropertyType.LOTE, PropertyType.CHACRA, PropertyType.CAMPO}


class GeoPrecision(StrEnum):
    EXACT = "exact"  # coordenadas publicadas por la ficha (mapa / JSON-LD)
    APPROXIMATE = "approximate"  # referencia (barrio, km de ruta) geocodificada
    LOCALITY = "locality"  # solo localidad: centroide de la localidad
    UNKNOWN = "unknown"


class WaterClass(StrEnum):
    WATERFRONT_CONFIRMED = "waterfront_confirmed"
    WATERFRONT_CLAIMED = "waterfront_claimed"
    WATERFRONT_POSSIBLE = "waterfront_possible"
    WATER_NEARBY = "water_nearby"
    WATER_VIEW_ONLY = "water_view_only"
    UNKNOWN = "unknown"


class Provenance(BaseModel):
    method: str  # json_ld | meta | selector | html | regex | gazetteer | llm | manual
    evidence: str | None = None
    confidence: float = Field(ge=0, le=1)


class Location(BaseModel):
    province: str | None = None
    locality: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    precision: GeoPrecision = GeoPrecision.UNKNOWN


class WaterInfo(BaseModel):
    water_class: WaterClass = WaterClass.UNKNOWN
    waterfront_claimed: bool | None = None
    water_access: bool | None = None
    water_view: bool | None = None
    water_type: str | None = None  # lake | river | stream | spring | reservoir
    water_name: str | None = None
    distance_m_mentioned: float | None = None
    evidence: str | None = None
    confidence: float = 0.0


class Features(BaseModel):
    access: str | None = None
    services: list[str] = Field(default_factory=list)
    electricity: bool | None = None
    gas: bool | None = None
    water_supply: bool | None = None
    improvements: list[str] = Field(default_factory=list)
    buildings: str | None = None
    topography: str | None = None
    vegetation: str | None = None


class ExtractedListing(BaseModel):
    # Identidad
    source_id: str
    url: str
    canonical_url: str
    external_listing_id: str | None = None
    title: str | None = None
    status_text: str | None = None  # "vendido", "reservado"... según la ficha
    # Comercial
    property_type: PropertyType | None = None
    operation: str | None = None  # venta | alquiler
    price: float | None = None
    currency: str | None = None  # USD | ARS
    price_raw: str | None = None
    price_on_request: bool = False
    expenses: float | None = None
    published_at: str | None = None
    updated_at: str | None = None
    # Superficie
    area_m2: float | None = None
    area_raw: str | None = None
    area_original_unit: str | None = None  # m2 | ha
    built_area_m2: float | None = None
    # Ubicación / características / agua
    location: Location = Field(default_factory=Location)
    features: Features = Field(default_factory=Features)
    water: WaterInfo = Field(default_factory=WaterInfo)
    # Contenido
    description: str | None = None
    photos: list[str] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)
    # Proveniencia
    provenance: dict[str, Provenance] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    extraction_methods: list[str] = Field(default_factory=list)

    def snapshot_payload(self) -> dict[str, Any]:
        """Campos relevantes para detectar cambios (excluye proveniencia/metadata volátil)."""
        return {
            "title": self.title,
            "property_type": self.property_type,
            "price": self.price,
            "currency": self.currency,
            "price_on_request": self.price_on_request,
            "area_m2": self.area_m2,
            "status_text": self.status_text,
            "operation": self.operation,
            "locality": self.location.locality,
            "latitude": self.location.latitude,
            "longitude": self.location.longitude,
            "description": self.description,
            "photos": sorted(self.photos)[:30],
            "water_class": self.water.water_class,
        }
