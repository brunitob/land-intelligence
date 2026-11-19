import { useQuery } from "@tanstack/react-query";
import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import { api, PropertiesResponse, Zone } from "./api";
import { AIRPORTS, LAND_TYPES } from "./format";

// Filtros de búsqueda compartidos entre Propiedades y Mapa; se recuerdan en este navegador.

export interface Filters {
  property_types: string[];
  max_price_usd: number | null;
  min_area_m2: number | null;
  airports: string[];
  zones: string[];
  water_classes: string[];
  waterfront_only: boolean;
  include_unknown_location: boolean;
  include_no_price: boolean;
  only_new: boolean;
  q: string;
}

export const DEFAULT_FILTERS: Filters = {
  property_types: LAND_TYPES,
  max_price_usd: 500000,
  min_area_m2: null,
  airports: AIRPORTS,
  zones: [],
  water_classes: [],
  waterfront_only: false,
  include_unknown_location: true,
  include_no_price: true,
  only_new: false,
  q: "",
};

const KEY = "land.filters.v1";
const Ctx = createContext<{ filters: Filters; setFilters: (f: Filters) => void; reset: () => void }>(null!);

function load(): Filters | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...DEFAULT_FILTERS, ...JSON.parse(raw) } : null;
  } catch {
    return null;
  }
}

export function FiltersProvider({ children }: { children: ReactNode }) {
  const defaults = useQuery({ queryKey: ["search-defaults"], queryFn: () => api.get<Record<string, any>>("/search/defaults") });
  const [filters, setFilters] = useState<Filters>(() => load() ?? DEFAULT_FILTERS);
  const [touched, setTouched] = useState(() => load() !== null);

  // Sin filtros guardados: tomar los defaults del servidor (config/search.yaml).
  useEffect(() => {
    if (touched || !defaults.data) return;
    const d = defaults.data;
    setFilters((f) => ({
      ...f,
      property_types: d.property_types ?? f.property_types,
      max_price_usd: d.max_price_usd ?? f.max_price_usd,
      min_area_m2: d.min_area_m2 || null,
      waterfront_only: d.waterfront_only ?? f.waterfront_only,
      include_unknown_location: d.include_unknown_location ?? f.include_unknown_location,
    }));
  }, [defaults.data, touched]);

  const set = (f: Filters) => {
    setTouched(true);
    setFilters(f);
    try {
      localStorage.setItem(KEY, JSON.stringify(f));
    } catch {
      /* almacenamiento no disponible */
    }
  };
  const reset = () => {
    try {
      localStorage.removeItem(KEY);
    } catch {
      /* nada */
    }
    setTouched(false);
    setFilters(DEFAULT_FILTERS);
  };
  return <Ctx.Provider value={{ filters, setFilters: set, reset }}>{children}</Ctx.Provider>;
}

export const useFilters = () => useContext(Ctx);

export function useProperties(filters: Filters) {
  return useQuery({
    queryKey: ["properties", filters],
    queryFn: () =>
      api.get<PropertiesResponse>("/properties", {
        property_types: filters.property_types,
        max_price_usd: filters.max_price_usd,
        min_area_m2: filters.min_area_m2,
        airports: filters.airports,
        zones: filters.zones,
        water_classes: filters.water_classes,
        waterfront_only: filters.waterfront_only,
        include_unknown_location: filters.include_unknown_location,
        include_no_price: filters.include_no_price,
        only_new: filters.only_new,
        q: filters.q.trim() || null,
        limit: 2000,
      }),
    placeholderData: (prev) => prev,
  });
}

export function useZones() {
  return useQuery({ queryKey: ["zones"], queryFn: () => api.get<Zone[]>("/zones"), staleTime: Infinity });
}
