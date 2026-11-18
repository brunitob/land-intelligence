import { ReactNode, useEffect, useMemo, useState } from "react";
import { Listing } from "../api";
import { area, GEO, money, num, WATER } from "../format";
import { Sort, sortRows, Th } from "./ui";

const PAGE = 50;

// Tabla de avisos: orden por columna, paginado local, selección con casillas y click para ver el detalle.
export function ListingTable({
  rows,
  selected,
  onSelect,
  onOpen,
  extraCol,
  showSource = true,
}: {
  rows: Listing[];
  selected?: Set<number>;
  onSelect?: (s: Set<number>) => void;
  onOpen: (id: number) => void;
  extraCol?: { header: string; cell: (l: Listing) => ReactNode };
  showSource?: boolean;
}) {
  const [sort, setSort] = useState<Sort | null>(null);
  const [page, setPage] = useState(0);
  const sorted = useMemo(() => sortRows(rows, sort), [rows, sort]);
  const pages = Math.max(1, Math.ceil(sorted.length / PAGE));
  useEffect(() => setPage(0), [rows.length, sort]);
  const view = sorted.slice(page * PAGE, page * PAGE + PAGE);
  const sel = selected ?? new Set<number>();
  const allOnPage = view.length > 0 && view.every((r) => sel.has(r.id));

  const toggle = (id: number) => {
    if (!onSelect) return;
    const s = new Set(sel);
    if (s.has(id)) s.delete(id);
    else s.add(id);
    onSelect(s);
  };
  const togglePage = () => {
    if (!onSelect) return;
    const s = new Set(sel);
    view.forEach((r) => (allOnPage ? s.delete(r.id) : s.add(r.id)));
    onSelect(s);
  };
  const p = { sort, setSort };

  return (
    <>
      <div className="table-wrap">
        <table className="t">
          <thead>
            <tr>
              {onSelect && (
                <th style={{ width: 32 }}>
                  <input type="checkbox" checked={allOnPage} onChange={togglePage} aria-label="Elegir todos los de esta página" />
                </th>
              )}
              {extraCol && <th>{extraCol.header}</th>}
              <Th k="title" {...p}>Aviso</Th>
              <Th k="property_type" {...p}>Tipo</Th>
              <Th k="price_usd" num {...p}>Precio</Th>
              <Th k="area_m2" num {...p}>Superficie</Th>
              <Th k="price_per_ha_usd" num {...p}>USD/ha</Th>
              <Th k="locality" {...p}>Localidad</Th>
              <Th k="water_class" {...p}>Agua</Th>
              {showSource && <Th k="source_id" {...p}>Fuente</Th>}
              <th />
            </tr>
          </thead>
          <tbody>
            {view.map((l) => (
              <tr key={l.id} className={`clickable${sel.has(l.id) ? " selected" : ""}`} onClick={() => onOpen(l.id)}>
                {onSelect && (
                  <td onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={sel.has(l.id)} onChange={() => toggle(l.id)} aria-label={`Elegir ${l.title}`} />
                  </td>
                )}
                {extraCol && <td onClick={(e) => e.stopPropagation()}>{extraCol.cell(l)}</td>}
                <td className="title">
                  <span className="clip" title={l.title ?? ""}>
                    {l.title ?? <span className="muted">Sin título</span>}
                  </span>
                  {l.status === "missing" && <span className="badge warn small">no visto en la última corrida</span>}
                </td>
                <td>{l.property_type ?? "—"}</td>
                <td className="num nowrap">{money(l.price, l.currency)}</td>
                <td className="num nowrap">{area(l.area_m2)}</td>
                <td className="num nowrap">{l.price_per_ha_usd ? num(l.price_per_ha_usd) : "—"}</td>
                <td className="nowrap">
                  {l.locality ?? <span className="muted">—</span>}
                  {l.geo_precision === "exact" && <span className="muted small" title={GEO.exact}> 📍</span>}
                </td>
                <td className="small ink2 nowrap">{l.water_class && l.water_class !== "unknown" ? WATER[l.water_class] ?? l.water_class : ""}</td>
                {showSource && <td className="small ink2 nowrap">{l.source_id}</td>}
                <td onClick={(e) => e.stopPropagation()}>
                  <a href={l.url} target="_blank" rel="noreferrer" title="Abrir aviso original">
                    ↗
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <div className="empty">No hay avisos con estos filtros.</div>}
      </div>
      {pages > 1 && (
        <div className="pager small">
          <span className="muted">
            {page * PAGE + 1}–{Math.min(sorted.length, (page + 1) * PAGE)} de {num(sorted.length)}
          </span>
          <button className="btn sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
            ← Anterior
          </button>
          <button className="btn sm" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>
            Siguiente →
          </button>
        </div>
      )}
    </>
  );
}
