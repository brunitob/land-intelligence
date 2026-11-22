// Cliente de la API. Siempre por /api (Vite en desarrollo, Caddy en producción): el navegador nunca ve el token.

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type Params = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

function qs(params?: Params): string {
  if (!params) return "";
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, String(x)));
    else sp.append(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

async function request<T>(method: string, path: string, opts: { params?: Params; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { "X-Requested-With": "fetch" }; // anti-CSRF: la API lo exige
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api${path}${qs(opts.params)}`, {
    method,
    headers,
    credentials: "same-origin",
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  // Sesión vencida o cerrada: la app vuelve a la pantalla de ingreso.
  if (res.status === 401 && path !== "/auth/login") window.dispatchEvent(new Event("auth:required"));
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* respuesta sin JSON */
    }
    throw new ApiError(res.status, msg);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const api = {
  get: <T>(path: string, params?: Params) => request<T>("GET", path, { params }),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, { body: body ?? {} }),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, { body: body ?? {} }),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, { body: body ?? {} }),
  del: (path: string) => request<void>("DELETE", path),
};

// ------------------------------------------------------------------ tipos (lo que devuelve la API)
export interface Listing {
  id: number;
  source_id: string;
  property_id: number | null;
  url: string;
  title: string | null;
  status: string;
  property_type: string | null;
  operation: string | null;
  price: number | null;
  currency: string | null;
  price_usd: number | null;
  area_m2: number | null;
  locality: string | null;
  province: string | null;
  latitude: number | null;
  longitude: number | null;
  geo_precision: string | null;
  water_class: string | null;
  confidence: number | null;
  photos: string[];
  first_seen_at: string;
  last_seen_at: string;
  price_per_ha_usd: number | null;
  warnings?: string[];
  is_new?: boolean;
  origin?: "filtro" | "fijado";
}

export interface ListingDetail extends Listing {
  description: string | null;
  data: Record<string, any>;
  provenance: Record<string, any>;
  changes: Change[];
  snapshots: { id: number; captured_at: string; content_hash: string; data: Record<string, any> }[];
}

export interface Change {
  id: number;
  listing_id: number;
  change_type: string;
  old_value: unknown;
  new_value: unknown;
  pct_change: number | null;
  detected_at: string;
  title?: string;
  url?: string;
  source_id?: string;
  locality?: string;
}

export interface PropertiesResponse {
  total: number;
  new_count: number;
  items: Listing[];
  airport_filter_mode: "isochrone" | "region" | null;
}

export interface Highlight {
  id: number;
  name: string;
  keywords: string[];
  match_mode: "any" | "all";
  zones: string[];
  property_types: string[];
  water_classes: string[];
  max_price_usd: number | null;
  min_area_m2: number | null;
  include_rentals: boolean;
  position: number;
  total: number;
  fijados: number;
  excluidos: number;
}

export interface HighlightListings {
  highlight: Highlight;
  total: number;
  items: Listing[];
  excluded: { id: number; title: string; url: string }[];
}

export interface Zone {
  zone: string;
  localities: string[];
}

export interface CrawlRun {
  id: number;
  source_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  pages_visited: number;
  candidate_urls: number;
  details_discovered: number;
  details_processed: number;
  valid_properties: number;
  errors_count: number;
  pct_with_price: number | null;
  pct_with_area: number | null;
  duration_seconds: number | null;
  possibly_broken: boolean;
  errors?: { stage?: string; url?: string; error: string }[];
}

export interface Source {
  id: string;
  name: string;
  base_url: string;
  start_urls: string[];
  region: string | null;
  enabled: boolean;
  crawl_interval_hours: number;
  max_pages_per_run: number;
  created_at: string;
  last_run: CrawlRun | null;
  active_listings: number;
  profile: { version: number; origin: string; confidence: number | null } | null;
}

export interface Job {
  id: number;
  kind: string;
  source_id: string | null;
  status: string;
  progress: Record<string, any>;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  not_before: string | null;
}

export interface Status {
  last_run_at: string | null;
  queued: number;
  running: number;
  running_jobs: { kind: string; source_id: string | null }[];
  watch_unseen: number;
}

export interface Watched {
  id: number;
  url: string;
  note: string | null;
  listing_id: number | null;
  status: "pending" | "ok" | "blocked" | "robots" | "gone" | "error";
  last_error: string | null;
  last_checked_at: string | null;
  seen_at: string;
  created_at: string;
  listing: Listing | null;
  changes: Change[];
  unseen: number;
}

export interface DedupItem {
  id: number;
  score: number;
  a: DedupSide;
  b: DedupSide;
}
export interface DedupSide {
  id: number;
  title: string | null;
  url: string;
  source_id: string;
  price: number | null;
  currency: string | null;
  area_m2: number | null;
  locality: string | null;
}

export interface Stats {
  kpis: {
    listings_active: number;
    land_active: number;
    sources_enabled: number;
    sources_total: number;
    runs_24h: number;
    runs_failed_24h: number;
    runs_broken_24h: number;
    props_located: number;
    props_with_drive_time: number;
    last_run_at: string | null;
    new_7d: number;
    price_drops_7d: number;
    removed_7d: number;
    dedup_pending: number;
  };
  runs_by_day: { day: string; ok: number; failed: number; avg_minutes: number | null }[];
  changes_by_day: { day: string; change_type: string; n: number }[];
  changes_7d: { change_type: string; n: number }[];
  types: { property_type: string; n: number }[];
  zones: { zone: string; listings: number; with_price: number; median_price_usd: number | null; median_usd_per_ha: number | null }[];
  sources: {
    id: string;
    name: string;
    enabled: boolean;
    region: string | null;
    active: number;
    land: number;
    pct_price: number | null;
    pct_area: number | null;
    pct_locality: number | null;
    pct_coords: number | null;
    new_7d: number;
    price_changes_7d: number;
    removed_7d: number;
    last_run_at: string | null;
    last_status: string | null;
    last_minutes: number | null;
    last_errors: number | null;
    possibly_broken: boolean;
    base_url: string;
  }[];
  price_moves: {
    detected_at: string;
    change_type: string;
    pct_change: number | null;
    title: string;
    price: number | null;
    currency: string | null;
    locality: string | null;
    source_id: string;
    url: string;
    listing_id?: number;
  }[];
  drive: { airport_code: string; within: number; outside: number; unknown: number }[];
}

export interface Airport {
  code: string;
  name: string;
  latitude: number;
  longitude: number;
}
