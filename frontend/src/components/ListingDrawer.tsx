import { useQuery } from "@tanstack/react-query";
import { api, ListingDetail } from "../api";
import { area, CHANGE_LABELS, dateTime, GEO, money, num, WATER } from "../format";
import { useMarkReviewed } from "../reviews";
import { AddToHighlight } from "./AddToHighlight";
import { Drawer, ErrorBox, Loading } from "./ui";

export function ListingDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const q = useQuery({ queryKey: ["listing", id], queryFn: () => api.get<ListingDetail>(`/listings/${id}`) });
  const d = q.data;
  const mark = useMarkReviewed();
  // Solo los cambios de precio (un snapshot nuevo también se guarda cuando cambia otro dato).
  const prices = (d?.snapshots ?? [])
    .map((s) => ({ at: s.captured_at, price: s.data?.price as number | null, currency: s.data?.currency as string | null }))
    .reverse()
    .filter((p, i, all) => i === 0 || p.price !== all[i - 1].price || p.currency !== all[i - 1].currency)
    .reverse();
  const water = d?.data?.water ?? {};

  return (
    <Drawer onClose={onClose}>
      <div className="drawer-head">
        <div className="grow">
          <div className="small muted">
            #{id} · {d?.source_id}
          </div>
          <h2 style={{ marginTop: 2 }}>{d?.title ?? "…"}</h2>
          {d && (
            <a href={d.url} target="_blank" rel="noreferrer" className="small">
              Ver aviso original ↗
            </a>
          )}
        </div>
        {d && (
          <button
            className={`btn sm${d.is_new ? " primary" : ""}`}
            disabled={mark.isPending}
            onClick={() => mark.mutate({ ids: [id], reviewed: !!d.is_new })}
            title={d.is_new ? "Sacarlo de “Nuevos sin revisar”" : "Volver a ponerlo en “Nuevos sin revisar”"}
          >
            {d.is_new ? "✓ Marcar revisado" : "↺ Volver a nuevo"}
          </button>
        )}
        <button className="btn ghost" onClick={onClose} aria-label="Cerrar">
          ✕
        </button>
      </div>
      <div className="drawer-body">
        {q.isLoading && <Loading />}
        {q.error && <ErrorBox error={q.error} />}
        {d && (
          <>
            <div className="facts">
              <Fact k="Precio" v={money(d.price, d.currency)} />
              <Fact k="Superficie" v={area(d.area_m2)} />
              <Fact k="USD por ha" v={d.price_usd && d.area_m2 ? `US$ ${num(d.price_usd / (d.area_m2 / 10000))}` : "—"} />
              <Fact k="Tipo" v={d.property_type ?? "—"} />
              <Fact k="Localidad" v={d.locality ?? "—"} />
              <Fact k="Ubicación" v={GEO[d.geo_precision ?? "unknown"] ?? d.geo_precision ?? "—"} />
              <Fact k="Agua" v={WATER[d.water_class ?? "unknown"] ?? d.water_class ?? "—"} />
              <Fact k="Estado" v={d.status === "active" ? "Activo" : d.status === "missing" ? "No visto en la última corrida" : d.status} />
              <Fact k="Visto por primera vez" v={dateTime(d.first_seen_at)} />
            </div>

            <div className="card card-pad stack" style={{ gap: 10 }}>
              <strong>⭐ Destacados</strong>
              <AddToHighlight listingId={id} />
            </div>

            {d.photos?.length > 0 && (
              <div className="photos">
                {d.photos.slice(0, 9).map((p) => (
                  <a key={p} href={p} target="_blank" rel="noreferrer">
                    <img
                      src={p}
                      loading="lazy"
                      alt=""
                      referrerPolicy="no-referrer"
                      onError={(e) => ((e.currentTarget.parentElement as HTMLElement).style.display = "none")}
                    />
                  </a>
                ))}
              </div>
            )}

            {water.evidence && (
              <div className="small ink2">
                <strong>Agua:</strong> {water.evidence}
              </div>
            )}
            {(d.data?.warnings ?? []).length > 0 && <div className="alert small">{d.data.warnings.join(" · ")}</div>}

            <div>
              <h3 style={{ marginBottom: 6 }}>Descripción</h3>
              <div className="desc">{d.description || <span className="muted">Sin descripción.</span>}</div>
            </div>

            {prices.length > 0 && (
              <div>
                <h3 style={{ marginBottom: 6 }}>Historial de precio</h3>
                <table className="t">
                  <tbody>
                    {prices.map((p, i) => (
                      <tr key={i}>
                        <td className="muted">{dateTime(p.at)}</td>
                        <td className="num">{money(p.price, p.currency)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {d.changes.length > 0 && (
              <div>
                <h3 style={{ marginBottom: 6 }}>Cambios detectados</h3>
                <table className="t">
                  <tbody>
                    {d.changes.map((c) => (
                      <tr key={c.id}>
                        <td className="muted nowrap">{dateTime(c.detected_at)}</td>
                        <td>{CHANGE_LABELS[c.change_type] ?? c.change_type}</td>
                        <td className="num">{c.pct_change != null ? `${c.pct_change > 0 ? "+" : ""}${c.pct_change.toFixed(1)} %` : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <details>
              <summary>Evidencia y confianza por campo</summary>
              <pre className="json">{JSON.stringify(d.provenance, null, 2)}</pre>
            </details>
          </>
        )}
      </div>
    </Drawer>
  );
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div className="fact">
      <div className="k">{k}</div>
      <div className="v">{v}</div>
    </div>
  );
}
