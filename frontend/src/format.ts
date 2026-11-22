// Formato argentino y etiquetas en castellano.

const nf = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 });

export const num = (n: number | null | undefined) => (n === null || n === undefined ? "—" : nf.format(n));
export const num1 = (n: number | null | undefined) => (n === null || n === undefined ? "—" : nf1.format(n));

export function money(n: number | null | undefined, currency?: string | null): string {
  if (n === null || n === undefined) return "—";
  const sym = currency === "ARS" ? "$" : currency === "USD" || !currency ? "US$" : currency + " ";
  return `${sym} ${nf.format(n)}`;
}

export function area(m2: number | null | undefined): string {
  if (m2 === null || m2 === undefined) return "—";
  if (m2 >= 10_000) return `${nf2.format(m2 / 10_000)} ha`;
  return `${nf.format(m2)} m²`;
}

export const pct = (x: number | null | undefined, digits = 0) =>
  x === null || x === undefined ? "—" : `${new Intl.NumberFormat("es-AR", { maximumFractionDigits: digits }).format(x * 100)} %`;

const TZ = "America/Argentina/Buenos_Aires";
export function dateTime(s: string | null | undefined): string {
  if (!s) return "—";
  return new Date(s).toLocaleString("es-AR", { timeZone: TZ, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
}
export function date(s: string | null | undefined): string {
  if (!s) return "—";
  return new Date(s).toLocaleDateString("es-AR", { timeZone: TZ, day: "2-digit", month: "2-digit", year: "2-digit" });
}
export function ago(s: string | null | undefined): string {
  if (!s) return "—";
  const min = Math.round((Date.now() - new Date(s).getTime()) / 60000);
  if (min < 1) return "recién";
  if (min < 60) return `hace ${min} min`;
  const h = Math.round(min / 60);
  if (h < 48) return `hace ${h} h`;
  return `hace ${Math.round(h / 24)} días`;
}
export function dayLabel(d: string): string {
  const [, m, dd] = d.split("-");
  return `${dd}/${m}`;
}

export const PROPERTY_TYPES = ["terreno", "lote", "chacra", "campo", "casa", "cabaña", "departamento", "local", "otro"];
export const LAND_TYPES = ["terreno", "lote", "chacra", "campo"];
export const AIRPORTS = ["BRC", "CPC", "EQS"];
export const AIRPORT_NAMES: Record<string, string> = { BRC: "Bariloche", CPC: "Chapelco", EQS: "Esquel" };

export const WATER: Record<string, string> = {
  waterfront_confirmed: "Costa confirmada",
  waterfront_claimed: "Costa (según aviso)",
  waterfront_possible: "Posible costa",
  water_nearby: "Agua cerca",
  water_view_only: "Vista al agua",
  unknown: "Sin dato",
};

export const GEO: Record<string, string> = { exact: "Exacta", approximate: "Aproximada", locality: "Localidad", unknown: "Desconocida" };

export const CHANGE_LABELS: Record<string, string> = {
  new_listing: "Nuevo",
  price_decreased: "Bajó el precio",
  price_increased: "Subió el precio",
  removed: "Dado de baja",
  area_changed: "Cambió superficie",
  status_changed: "Cambió estado",
  description_changed: "Cambió descripción",
  relisted: "Republicado",
  photos_changed: "Cambiaron fotos",
  title_changed: "Cambió título",
};

export const JOB_KIND: Record<string, string> = { crawl: "Crawl", inspect: "Inspección", geo: "Tiempos de manejo", watch: "Seguimiento" };
export const JOB_STATUS: Record<string, string> = { queued: "En cola", running: "Corriendo", done: "Listo", failed: "Falló" };
export const RUN_STATUS: Record<string, string> = { success: "OK", partial: "Parcial", failed: "Falló", running: "Corriendo" };
export const REGIONS: Record<string, string> = { bariloche: "Bariloche", chapelco: "Chapelco", esquel: "Esquel" };
