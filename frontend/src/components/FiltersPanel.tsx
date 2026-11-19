import { useEffect, useState } from "react";
import { AIRPORT_NAMES, AIRPORTS, PROPERTY_TYPES, WATER } from "../format";
import { Filters, useFilters, useZones } from "../filters";
import { Chips } from "./ui";

function useDebounced<T>(value: T, ms: number, apply: (v: T) => void) {
  useEffect(() => {
    const t = setTimeout(() => apply(value), ms);
    return () => clearTimeout(t);
  }, [value]);
}

export function FiltersPanel({ maxMinutes }: { maxMinutes: number }) {
  const { filters, setFilters, reset } = useFilters();
  const zones = useZones();
  const set = (patch: Partial<Filters>) => setFilters({ ...filters, ...patch });

  // Campos de texto/número: se aplican al dejar de escribir.
  const [q, setQ] = useState(filters.q);
  const [price, setPrice] = useState(filters.max_price_usd?.toString() ?? "");
  const [areaMin, setAreaMin] = useState(filters.min_area_m2?.toString() ?? "");
  useEffect(() => {
    setQ(filters.q);
    setPrice(filters.max_price_usd?.toString() ?? "");
    setAreaMin(filters.min_area_m2?.toString() ?? "");
  }, [filters.q, filters.max_price_usd, filters.min_area_m2]);
  useDebounced(q, 400, (v) => v !== filters.q && set({ q: v }));
  useDebounced(price, 500, (v) => {
    const n = v ? Number(v) : null;
    if (n !== filters.max_price_usd && (n === null || !Number.isNaN(n))) set({ max_price_usd: n });
  });
  useDebounced(areaMin, 500, (v) => {
    const n = v ? Number(v) : null;
    if (n !== filters.min_area_m2 && (n === null || !Number.isNaN(n))) set({ min_area_m2: n });
  });

  return (
    <div className="card card-pad filters">
      <div className="stack">
        <div className="spread">
          <h3>Filtros</h3>
          <button className="btn ghost sm" onClick={reset}>
            Restablecer
          </button>
        </div>
        <label className="check small">
          <input type="checkbox" checked={filters.only_new} onChange={(e) => set({ only_new: e.target.checked })} />
          Solo nuevos sin revisar
        </label>
        <label className="field">
          Buscar en título o descripción
          <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="lago, bosque, Villa…" />
        </label>
        <div className="field">
          <span>Tipo</span>
          <Chips options={PROPERTY_TYPES} value={filters.property_types} onChange={(v) => set({ property_types: v })} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <label className="field">
            Precio máx. (USD)
            <input className="input" inputMode="numeric" value={price} onChange={(e) => setPrice(e.target.value.replace(/\D/g, ""))} placeholder="sin límite" />
          </label>
          <label className="field">
            Sup. mín. (m²)
            <input className="input" inputMode="numeric" value={areaMin} onChange={(e) => setAreaMin(e.target.value.replace(/\D/g, ""))} placeholder="sin mínimo" />
          </label>
        </div>
        <label className="check small">
          <input type="checkbox" checked={filters.include_no_price} onChange={(e) => set({ include_no_price: e.target.checked })} />
          Incluir avisos sin precio
        </label>
        <div className="field">
          <span>Aeropuertos (≤ {maxMinutes} min de manejo)</span>
          <Chips options={AIRPORTS} value={filters.airports} onChange={(v) => set({ airports: v })} label={(a) => `${a} · ${AIRPORT_NAMES[a]}`} />
        </div>
        <div className="field">
          <span>Zona {filters.zones.length > 0 && <button className="btn ghost sm" onClick={() => set({ zones: [] })}>limpiar</button>}</span>
          <Chips options={(zones.data ?? []).map((z) => z.zone)} value={filters.zones} onChange={(v) => set({ zones: v })} />
          <span className="muted small">Por localidad detectada; sin zona elegida se muestran todas.</span>
        </div>
        <div className="field">
          <span>Agua</span>
          <Chips options={Object.keys(WATER)} value={filters.water_classes} onChange={(v) => set({ water_classes: v })} label={(w) => WATER[w]} />
        </div>
        <label className="check small">
          <input type="checkbox" checked={filters.waterfront_only} onChange={(e) => set({ waterfront_only: e.target.checked })} />
          Solo costa (declarada o confirmada)
        </label>
        <label className="check small">
          <input type="checkbox" checked={filters.include_unknown_location} onChange={(e) => set({ include_unknown_location: e.target.checked })} />
          Incluir ubicación desconocida
        </label>
      </div>
    </div>
  );
}
