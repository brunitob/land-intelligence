"""Modelo de datos (sección 5 de la especificación).

La propiedad física (`properties`) es una entidad distinta del anuncio (`listings`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}


def _now() -> Any:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    base_url: Mapped[str] = mapped_column(Text)
    start_urls: Mapped[list[Any]] = mapped_column(default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    discovery_mode: Mapped[str] = mapped_column(String(32), default="auto")
    extraction_mode: Mapped[str] = mapped_column(String(32), default="auto")
    crawl_interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    max_pages_per_run: Mapped[int] = mapped_column(Integer, default=200)
    max_depth: Mapped[int] = mapped_column(Integer, default=5)
    region: Mapped[str | None] = mapped_column(String(64))
    # Overrides manuales: nunca los pisa un perfil auto-generado.
    manual_overrides: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = _now()
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    profiles: Mapped[list[SiteProfile]] = relationship(back_populates="source", order_by="SiteProfile.version")


class SiteProfile(Base):
    __tablename__ = "site_profiles"
    __table_args__ = (UniqueConstraint("source_id", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    origin: Mapped[str] = mapped_column(String(16), default="auto")  # auto | manual
    profile: Mapped[dict[str, Any]] = mapped_column()
    confidence: Mapped[float | None] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _now()

    source: Mapped[Source] = relationship(back_populates="profiles")


class Job(Base):
    """Procesos largos (inspección, crawl) consultables por id."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # inspect | crawl
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued|running|done|failed
    progress: Mapped[dict[str, Any]] = mapped_column(default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    profile_version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|success|partial|failed
    started_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pages_visited: Mapped[int] = mapped_column(Integer, default=0)
    candidate_urls: Mapped[int] = mapped_column(Integer, default=0)
    details_discovered: Mapped[int] = mapped_column(Integer, default=0)
    details_processed: Mapped[int] = mapped_column(Integer, default=0)
    valid_properties: Mapped[int] = mapped_column(Integer, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)
    pct_with_price: Mapped[float | None] = mapped_column(Float)
    pct_with_area: Mapped[float | None] = mapped_column(Float)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    possibly_broken: Mapped[bool] = mapped_column(Boolean, default=False)
    errors: Mapped[list[Any]] = mapped_column(default=list)


class CrawledPage(Base):
    __tablename__ = "crawled_pages"
    __table_args__ = (UniqueConstraint("source_id", "url"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    page_type: Mapped[str] = mapped_column(String(24), default="UNKNOWN")
    status: Mapped[str] = mapped_column(String(16), default="discovered")  # discovered|fetched|error|skipped
    http_status: Mapped[int | None] = mapped_column(Integer)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    parent_url: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    discovered_at: Mapped[datetime] = _now()
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class Property(Base):
    """Inmueble físico deduplicado; puede tener varios anuncios en distintas fuentes."""

    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_type: Mapped[str | None] = mapped_column(String(32), index=True)
    province: Mapped[str | None] = mapped_column(String(64))
    locality: Mapped[str | None] = mapped_column(String(128), index=True)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    geo_precision: Mapped[str | None] = mapped_column(String(16))  # exact|approximate|locality|unknown
    location: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    area_m2: Mapped[float | None] = mapped_column(Float)
    region: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()

    listings: Mapped[list[Listing]] = relationship(back_populates="property")


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint("source_id", "canonical_url", name="uq_listing_source_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id", ondelete="SET NULL"), index=True)
    external_listing_id: Mapped[str | None] = mapped_column(String(128), index=True)
    url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)  # active|missing|removed
    property_type: Mapped[str | None] = mapped_column(String(32), index=True)
    operation: Mapped[str | None] = mapped_column(String(16), index=True)  # venta | alquiler | None
    price: Mapped[float | None] = mapped_column(Numeric(16, 2))
    currency: Mapped[str | None] = mapped_column(String(8))
    price_usd: Mapped[float | None] = mapped_column(Numeric(16, 2))
    area_m2: Mapped[float | None] = mapped_column(Float)
    locality: Mapped[str | None] = mapped_column(String(128))
    province: Mapped[str | None] = mapped_column(String(64))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    geo_precision: Mapped[str | None] = mapped_column(String(16))
    water_class: Mapped[str | None] = mapped_column(String(32), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    photos: Mapped[list[Any]] = mapped_column(default=list)
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)  # extracción completa normalizada
    provenance: Mapped[dict[str, Any]] = mapped_column(default=dict)  # campo -> {method, evidence, confidence}
    confidence: Mapped[float | None] = mapped_column(Float)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    missed_runs: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = _now()
    last_seen_at: Mapped[datetime] = _now()
    last_checked_at: Mapped[datetime] = _now()

    property: Mapped[Property | None] = relationship(back_populates="listings")
    snapshots: Mapped[list[ListingSnapshot]] = relationship(
        back_populates="listing", order_by="ListingSnapshot.captured_at"
    )


class ListingSnapshot(Base):
    __tablename__ = "listing_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), index=True)
    crawl_run_id: Mapped[int | None] = mapped_column(ForeignKey("crawl_runs.id", ondelete="SET NULL"))
    content_hash: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column()
    raw_html_gz: Mapped[bytes | None] = mapped_column(LargeBinary)
    captured_at: Mapped[datetime] = _now()

    listing: Mapped[Listing] = relationship(back_populates="snapshots")


class ListingChange(Base):
    __tablename__ = "listing_changes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), index=True)
    change_type: Mapped[str] = mapped_column(String(32), index=True)
    old_value: Mapped[dict[str, Any] | None] = mapped_column()
    new_value: Mapped[dict[str, Any] | None] = mapped_column()
    pct_change: Mapped[float | None] = mapped_column(Float)
    detected_at: Mapped[datetime] = _now()
    notified: Mapped[bool] = mapped_column(Boolean, default=False)


class Airport(Base):
    __tablename__ = "airports"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    region: Mapped[str | None] = mapped_column(String(64))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    location: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AirportIsochrone(Base):
    __tablename__ = "airport_isochrones"
    __table_args__ = (UniqueConstraint("airport_code", "minutes", "provider"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    airport_code: Mapped[str] = mapped_column(ForeignKey("airports.code", ondelete="CASCADE"))
    minutes: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(32))
    geom: Mapped[Any] = mapped_column(Geometry("MULTIPOLYGON", srid=4326))
    computed_at: Mapped[datetime] = _now()


class WaterFeature(Base):
    __tablename__ = "water_features"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    osm_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    name: Mapped[str | None] = mapped_column(String(255))
    water_type: Mapped[str] = mapped_column(String(32))  # lake|river|stream|reservoir|coastline
    geom: Mapped[Any] = mapped_column(Geometry("GEOMETRY", srid=4326))
    source: Mapped[str] = mapped_column(String(32), default="osm")


class PropertyGeoAnalysis(Base):
    __tablename__ = "property_geo_analysis"
    __table_args__ = (UniqueConstraint("property_id", "airport_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    airport_code: Mapped[str] = mapped_column(ForeignKey("airports.code"))
    drive_minutes: Mapped[float | None] = mapped_column(Float)
    drive_minutes_min: Mapped[float | None] = mapped_column(Float)  # rango cuando la ubicación es aproximada
    drive_minutes_max: Mapped[float | None] = mapped_column(Float)
    within_isochrone: Mapped[bool | None] = mapped_column(Boolean)
    nearest_water_id: Mapped[int | None] = mapped_column(ForeignKey("water_features.id"))
    nearest_water_distance_m: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    computed_at: Mapped[datetime] = _now()


class DedupCandidate(Base):
    """Cola de revisión manual de posibles duplicados entre inmobiliarias."""

    __tablename__ = "dedup_candidates"
    __table_args__ = (UniqueConstraint("listing_a_id", "listing_b_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_a_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    listing_b_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    score: Mapped[float] = mapped_column(Float)
    reasons: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|merged|rejected|auto_merged
    created_at: Mapped[datetime] = _now()


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    change_id: Mapped[int | None] = mapped_column(ForeignKey("listing_changes.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(16), default="telegram")
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|sent|failed|skipped
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Highlight(Base):
    """Destacado: lista con nombre y filtros editables ("Villa", "Hectárea", "Lago").

    Un anuncio está en el destacado si cumple sus filtros (si tiene alguno) o si fue fijado a mano, y no fue
    excluido a mano. Los filtros se evalúan sobre datos ya recopilados: editarlos no requiere re-scrapear.
    """

    __tablename__ = "highlights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    keywords: Mapped[list[Any]] = mapped_column(default=list)  # texto en título/descripción, sin tildes
    match_mode: Mapped[str] = mapped_column(String(8), default="any")  # any | all (entre palabras clave)
    zones: Mapped[list[Any]] = mapped_column(default=list)
    property_types: Mapped[list[Any]] = mapped_column(default=list)
    water_classes: Mapped[list[Any]] = mapped_column(default=list)
    max_price_usd: Mapped[float | None] = mapped_column(Float)
    min_area_m2: Mapped[float | None] = mapped_column(Float)
    include_rentals: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now(), nullable=False)


class HighlightListing(Base):
    """Asignación manual de un anuncio a un destacado: 'pinned' (agregado) o 'excluded' (sacado del filtro)."""

    __tablename__ = "highlight_listings"

    highlight_id: Mapped[int] = mapped_column(ForeignKey("highlights.id", ondelete="CASCADE"), primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(10))  # pinned | excluded
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class DriveTimeCache(Base):
    """Minutos de manejo aeropuerto → punto (coordenadas redondeadas a ~10 m). Evita repetir pedidos a ORS:
    los caminos no cambian entre corridas y muchos avisos comparten el centro de su localidad."""

    __tablename__ = "drive_time_cache"

    airport_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    lat_e4: Mapped[int] = mapped_column(Integer, primary_key=True)
    lon_e4: Mapped[int] = mapped_column(Integer, primary_key=True)
    minutes: Mapped[float | None] = mapped_column(Float)  # None = ORS respondió sin ruta (p. ej. sin camino)
    computed_at: Mapped[datetime] = _now()
