import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api, Stats } from "../api";
import { HBar, StackedColumns } from "../components/charts";
import { ErrorBox, Loading, Meter, RunBadge, Sort, sortRows, Spinner, Th } from "../components/ui";
import { AIRPORT_NAMES, CHANGE_LABELS, dateTime, dayLabel, money, num, num1, pct, REGIONS } from "../format";

const GOOD = "var(--good)";
const CRITICAL = "var(--critical)";
const SERIES = "var(--series-1)";

export function StatsPage({ maxMinutes }: { maxMinutes: number }) {
  const [days, setDays] = useState(14);
  const q = useQuery({ queryKey: ["stats", days], queryFn: () => api.get<Stats>("/stats", { days }), placeholderData: (p) => p });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const S = q.data!;
  const k = S.kpis;
  const geoPct = k.props_located ? k.props_with_drive_time / k.props_located : 0;

  const newByDay = S.changes_by_day.filter((c) => c.change_type === "new_listing");

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="spread">
        <h2 className="row">Operación {q.isFetching && <Spinner />}</h2>
        <div className="chips" role="group" aria-label="Período">
          {[7, 14, 30].map((d) => (
            <button key={d} className={`chip${days === d ? " on" : ""}`} aria-pressed={days === d} onClick={() => setDays(d)}>
              {d} días
            </button>
          ))}
        </div>
      </div>
      <div className="tiles">
        <Tile k="Avisos activos" v={num(k.listings_active)} />
        <Tile k="Tierra en venta" v={num(k.land_active)} hint="Terrenos, lotes, chacras y campos." />
        <Tile k="Fuentes activas" v={`${k.sources_enabled}/${k.sources_total}`} />
        <Tile
          k="Corridas 24 h"
          v={num(k.runs_24h)}
          d={k.runs_failed_24h ? <span style={{ color: "var(--critical)" }}>✕ {k.runs_failed_24h} con error</span> : <span className="ink2">✓ sin errores</span>}
        />
        <Tile k="Última corrida" v={dateTime(k.last_run_at)} />
        <Tile k="Con tiempo de manejo" v={pct(geoPct)} hint="Propiedades con coordenadas que ya tienen tiempo de manejo a los aeropuertos." />
        <Tile k="Nuevos 7 días" v={num(k.new_7d)} hint="Sin contar la carga inicial de cada fuente." />
        <Tile k="Bajas de precio 7 días" v={num(k.price_drops_7d)} />
        <Tile k="Dados de baja 7 días" v={num(k.removed_7d)} />
        <Tile k="Duplicados a revisar" v={num(k.dedup_pending)} hint="Pares de avisos de distintas inmobiliarias que podrían ser la misma propiedad (ver Monitoreo)." />
      </div>
      {k.runs_broken_24h > 0 && (
        <div className="alert small">⚠ {k.runs_broken_24h} fuente(s) con posible rotura en las últimas 24 h (ver tabla de fuentes).</div>
      )}

      <div className="grid2">
        <div className="card card-pad">
          <div className="chart-title">Corridas por día</div>
          <StackedColumns
            series={[
              { name: "OK", color: GOOD },
              { name: "Con error", color: CRITICAL },
            ]}
            days={S.runs_by_day.map((r) => ({
              label: dayLabel(r.day),
              values: [r.ok, r.failed],
              extra: r.avg_minutes != null ? <div>Duración media: {num1(r.avg_minutes)} min</div> : null,
            }))}
            format={num}
          />
        </div>
        <div className="card card-pad">
          <div className="chart-title">Avisos nuevos por día</div>
          <StackedColumns series={[{ name: "Nuevos", color: SERIES }]} days={newByDay.map((r) => ({ label: dayLabel(r.day), values: [r.n] }))} format={num} />
          <div className="muted small" style={{ marginTop: 6 }}>Sin la carga inicial de cada fuente.</div>
        </div>
      </div>

      <h2 className="section-title">Mercado de tierra por zona</h2>
      <div className="grid2">
        <div className="card card-pad">
          <div className="chart-title">Avisos activos por zona</div>
          <HBar rows={S.zones} label={(z) => z.zone} value={(z) => z.listings} format={num} />
        </div>
        <div className="card card-pad">
          <div className="chart-title">Precio mediano por zona (USD)</div>
          <HBar
            rows={S.zones.filter((z) => z.with_price >= 3 && z.median_price_usd != null).sort((a, b) => b.median_price_usd! - a.median_price_usd!)}
            label={(z) => z.zone}
            value={(z) => z.median_price_usd!}
            format={(n) => `US$ ${num(n)}`}
            tooltip={(z) => (
              <div>
                <strong>{z.zone}</strong>
                <div>Mediana: US$ {num(z.median_price_usd)}</div>
                <div>{z.with_price} avisos con precio</div>
              </div>
            )}
          />
          <div className="muted small" style={{ marginTop: 6 }}>Solo zonas con 3 o más avisos con precio.</div>
        </div>
      </div>
      <ZoneTable zones={S.zones} />

      <div className="grid2">
        <div className="card card-pad">
          <div className="chart-title">Cambios detectados (7 días)</div>
          <HBar rows={S.changes_7d} label={(c) => CHANGE_LABELS[c.change_type] ?? c.change_type} value={(c) => c.n} format={num} />
        </div>
        <div className="card card-pad">
          <div className="chart-title">Avisos activos por tipo (sin alquileres)</div>
          <HBar rows={S.types} label={(t) => t.property_type} value={(t) => t.n} format={num} />
        </div>
      </div>

      <h2 className="section-title">Movimientos de precio</h2>
      <div className="card">
        {S.price_moves.length === 0 ? (
          <div className="empty">Sin cambios de precio en el período.</div>
        ) : (
          <div className="table-wrap">
            <table className="t">
              <thead>
                <tr>
                  <th>Detectado</th>
                  <th>Cambio</th>
                  <th className="num">%</th>
                  <th>Aviso</th>
                  <th className="num">Precio actual</th>
                  <th>Localidad</th>
                  <th>Fuente</th>
                </tr>
              </thead>
              <tbody>
                {S.price_moves.map((m, i) => (
                  <tr key={i}>
                    <td className="nowrap muted">{dateTime(m.detected_at)}</td>
                    <td className="nowrap">{m.change_type === "price_decreased" ? "▼ Bajó" : "▲ Subió"}</td>
                    <td className="num">{m.pct_change != null ? `${m.pct_change > 0 ? "+" : ""}${num1(m.pct_change)} %` : "—"}</td>
                    <td className="title">
                      <a className="clip" href={m.url} target="_blank" rel="noreferrer">
                        {m.title}
                      </a>
                    </td>
                    <td className="num nowrap">{money(m.price, m.currency)}</td>
                    <td>{m.locality ?? "—"}</td>
                    <td className="small ink2">{m.source_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <SourcesTable sources={S.sources} />

      <h2 className="section-title">Propiedades dentro de {maxMinutes} min por aeropuerto</h2>
      <div className="card" style={{ maxWidth: 560 }}>
        <table className="t">
          <thead>
            <tr>
              <th>Aeropuerto</th>
              <th className="num">Dentro</th>
              <th className="num">Fuera</th>
              <th className="num">Sin ruta</th>
            </tr>
          </thead>
          <tbody>
            {S.drive.map((d) => (
              <tr key={d.airport_code}>
                <td>
                  {d.airport_code} · {AIRPORT_NAMES[d.airport_code]}
                </td>
                <td className="num">{num(d.within)}</td>
                <td className="num">{num(d.outside)}</td>
                <td className="num">{num(d.unknown)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Tile({ k, v, d, hint }: { k: string; v: string; d?: React.ReactNode; hint?: string }) {
  return (
    <div className="card tile" title={hint}>
      <div className="k">
        {k}
        {hint && <span className="muted">ⓘ</span>}
      </div>
      <div className="v">{v}</div>
      {d && <div className="d">{d}</div>}
    </div>
  );
}

function ZoneTable({ zones }: { zones: Stats["zones"] }) {
  const [sort, setSort] = useState<Sort | null>({ key: "listings", dir: -1 });
  const rows = useMemo(() => sortRows(zones, sort), [zones, sort]);
  const p = { sort, setSort };
  return (
    <details className="card card-pad">
      <summary>Tabla por zona</summary>
      <div className="table-wrap" style={{ marginTop: 8 }}>
        <table className="t">
          <thead>
            <tr>
              <Th k="zone" {...p}>Zona</Th>
              <Th k="listings" num {...p}>Avisos</Th>
              <Th k="with_price" num {...p}>Con precio</Th>
              <Th k="median_price_usd" num {...p}>Mediana USD</Th>
              <Th k="median_usd_per_ha" num {...p}>Mediana USD/ha</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((z) => (
              <tr key={z.zone}>
                <td>{z.zone}</td>
                <td className="num">{num(z.listings)}</td>
                <td className="num">{num(z.with_price)}</td>
                <td className="num">{num(z.median_price_usd)}</td>
                <td className="num">{num(z.median_usd_per_ha)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function SourcesTable({ sources }: { sources: Stats["sources"] }) {
  const [onlyOn, setOnlyOn] = useState(true);
  const [sort, setSort] = useState<Sort | null>({ key: "active", dir: -1 });
  const rows = useMemo(() => sortRows(onlyOn ? sources.filter((s) => s.enabled) : sources, sort), [sources, onlyOn, sort]);
  const p = { sort, setSort };
  return (
    <>
      <div className="section-title spread">
        <h2>Fuentes</h2>
        <label className="check small">
          <input type="checkbox" checked={onlyOn} onChange={(e) => setOnlyOn(e.target.checked)} /> Solo activas
        </label>
      </div>
      <div className="card">
        <div className="table-wrap">
          <table className="t">
            <thead>
              <tr>
                <Th k="name" {...p}>Fuente</Th>
                <Th k="last_status" {...p}>Último crawl</Th>
                <Th k="last_run_at" {...p}>Cuándo</Th>
                <Th k="region" {...p}>Región</Th>
                <Th k="active" num {...p}>Activos</Th>
                <Th k="land" num {...p}>Tierra</Th>
                <Th k="pct_price" {...p}>Precio</Th>
                <Th k="pct_area" {...p}>Superficie</Th>
                <Th k="pct_locality" {...p}>Localidad</Th>
                <Th k="pct_coords" {...p}>Coordenadas</Th>
                <Th k="new_7d" num {...p}>Nuevos 7d</Th>
                <Th k="price_changes_7d" num {...p}>Precio 7d</Th>
                <Th k="removed_7d" num {...p}>Bajas 7d</Th>
                <Th k="last_minutes" num {...p}>Min</Th>
                <Th k="last_errors" num {...p}>Errores</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id}>
                  <td className="nowrap">
                    <a href={s.base_url} target="_blank" rel="noreferrer">
                      {s.name}
                    </a>
                  </td>
                  <td>
                    <RunBadge status={s.last_status} broken={s.possibly_broken} />
                  </td>
                  <td className="nowrap muted">{dateTime(s.last_run_at)}</td>
                  <td>{REGIONS[s.region ?? ""] ?? "—"}</td>
                  <td className="num">{num(s.active)}</td>
                  <td className="num">{num(s.land)}</td>
                  <td><Meter value={s.pct_price} /></td>
                  <td><Meter value={s.pct_area} /></td>
                  <td><Meter value={s.pct_locality} /></td>
                  <td><Meter value={s.pct_coords} /></td>
                  <td className="num">{num(s.new_7d)}</td>
                  <td className="num">{num(s.price_changes_7d)}</td>
                  <td className="num">{num(s.removed_7d)}</td>
                  <td className="num">{num1(s.last_minutes)}</td>
                  <td className="num">{num(s.last_errors)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="muted small card-pad" style={{ paddingTop: 8 }}>
          Cobertura = % de avisos activos de la fuente que tienen ese dato. Coordenadas = punto publicado (exacto o zona aproximada).
        </div>
      </div>
    </>
  );
}
