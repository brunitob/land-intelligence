import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, Change, DedupItem, DedupSide, Job } from "../api";
import { ListingDrawer } from "../components/ListingDrawer";
import { ErrorBox, Loading, Spinner, useToast } from "../components/ui";
import { area, CHANGE_LABELS, dateTime, JOB_KIND, JOB_STATUS, money, num, num1 } from "../format";

export function MonitorPage() {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="stack" style={{ gap: 16 }}>
      <Jobs />
      <Changes onOpen={setOpen} />
      <Dedup />
      {open !== null && <ListingDrawer id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function jobBadge(j: Job) {
  if (j.status === "queued" && j.not_before) return <span className="badge">⏸ Espera hasta {dateTime(j.not_before)}</span>;
  const cls = j.status === "done" ? "good" : j.status === "failed" ? "bad" : j.status === "running" ? "accent" : "";
  return <span className={`badge ${cls}`}>{JOB_STATUS[j.status] ?? j.status}</span>;
}

function Jobs() {
  const q = useQuery({ queryKey: ["jobs"], queryFn: () => api.get<Job[]>("/jobs", { limit: 40 }), refetchInterval: 5000 });
  return (
    <>
      <h2 className="row">Trabajos {q.isFetching && <Spinner />}</h2>
      <div className="card table-wrap">
        {q.isLoading ? (
          <Loading />
        ) : q.error ? (
          <div className="card-pad"><ErrorBox error={q.error} /></div>
        ) : (
          <table className="t">
            <thead>
              <tr>
                <th>#</th>
                <th>Tipo</th>
                <th>Fuente</th>
                <th>Estado</th>
                <th>Progreso</th>
                <th>Creado</th>
                <th>Terminó</th>
              </tr>
            </thead>
            <tbody>
              {(q.data ?? []).map((j) => (
                <tr key={j.id}>
                  <td className="muted">{j.id}</td>
                  <td>{JOB_KIND[j.kind] ?? j.kind}</td>
                  <td>{j.source_id ?? "—"}</td>
                  <td>{jobBadge(j)}</td>
                  <td className="small ink2">
                    {j.error ? (
                      <span style={{ color: "var(--critical)" }} title={j.error}>
                        {j.error.slice(0, 90)}
                      </span>
                    ) : j.status === "running" ? (
                      progress(j.progress)
                    ) : j.not_before ? (
                      j.progress?.reason
                    ) : (
                      ""
                    )}
                  </td>
                  <td className="nowrap muted">{dateTime(j.created_at)}</td>
                  <td className="nowrap muted">{dateTime(j.finished_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function progress(p: Record<string, any>): string {
  if (!p) return "";
  const stage = { discovering: "Recorriendo el sitio", extracting: "Extrayendo avisos", inspecting: "Inspeccionando" }[p.stage as string] ?? p.stage ?? "";
  const bits = [stage];
  if (p.pages_visited != null) bits.push(`${p.pages_visited} páginas`);
  if (p.details != null) bits.push(`${p.details} fichas`);
  return bits.filter(Boolean).join(" · ");
}

function Changes({ onOpen }: { onOpen: (id: number) => void }) {
  const [type, setType] = useState<string>("");
  const q = useQuery({
    queryKey: ["changes", type],
    queryFn: () => api.get<Change[]>("/changes", { change_types: type ? [type] : undefined, limit: 100 }),
    placeholderData: (p) => p,
  });
  return (
    <>
      <div className="section-title spread">
        <h2 className="row">Cambios recientes {q.isFetching && <Spinner />}</h2>
        <select className="select" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">Todos los cambios</option>
          {Object.entries(CHANGE_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </div>
      <div className="card table-wrap" style={{ maxHeight: 480, overflowY: "auto" }}>
        {q.isLoading ? (
          <Loading />
        ) : (
          <table className="t">
            <thead>
              <tr>
                <th>Detectado</th>
                <th>Cambio</th>
                <th className="num">%</th>
                <th>Aviso</th>
                <th>Localidad</th>
                <th>Fuente</th>
              </tr>
            </thead>
            <tbody>
              {(q.data ?? []).map((c) => (
                <tr key={c.id} className="clickable" onClick={() => onOpen(c.listing_id)}>
                  <td className="nowrap muted">{dateTime(c.detected_at)}</td>
                  <td className="nowrap">{CHANGE_LABELS[c.change_type] ?? c.change_type}</td>
                  <td className="num">{c.pct_change != null ? `${c.pct_change > 0 ? "+" : ""}${num1(c.pct_change)} %` : ""}</td>
                  <td className="title">
                    <span className="clip">{c.title}</span>
                  </td>
                  <td>{c.locality ?? "—"}</td>
                  <td className="small ink2">{c.source_id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {q.data?.length === 0 && <div className="empty">Sin cambios.</div>}
      </div>
    </>
  );
}

const DEDUP_PAGE = 20;

function Dedup() {
  const qc = useQueryClient();
  const toast = useToast();
  const [offset, setOffset] = useState(0);
  const q = useQuery({
    queryKey: ["dedup", offset],
    queryFn: () => api.get<{ total: number; items: DedupItem[] }>("/dedup/pending", { limit: DEDUP_PAGE, offset }),
    placeholderData: (p) => p,
  });
  const decide = useMutation({
    mutationFn: ({ id, decision }: { id: number; decision: "merge" | "reject" }) => api.post(`/dedup/${id}`, { decision }),
    onSuccess: (_, v) => {
      toast(v.decision === "merge" ? "Unidos como la misma propiedad" : "Marcados como distintos");
      qc.invalidateQueries({ queryKey: ["dedup"] });
    },
    onError: (e) => toast(String(e instanceof Error ? e.message : e), true),
  });
  const total = q.data?.total ?? 0;
  return (
    <>
      <div className="section-title spread">
        <h2 className="row">
          Posibles duplicados {q.data && <span className="muted">({num(total)})</span>} {q.isFetching && <Spinner />}
        </h2>
        {total > DEDUP_PAGE && (
          <div className="row small">
            <span className="muted">
              {offset + 1}–{Math.min(total, offset + DEDUP_PAGE)}
            </span>
            <button className="btn sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - DEDUP_PAGE))}>
              ←
            </button>
            <button className="btn sm" disabled={offset + DEDUP_PAGE >= total} onClick={() => setOffset(offset + DEDUP_PAGE)}>
              →
            </button>
          </div>
        )}
      </div>
      <div className="muted small">Avisos de distintas inmobiliarias que podrían ser la misma propiedad. Unir no borra nada: los agrupa.</div>
      <div className="stack" style={{ gap: 8 }}>
        {q.isLoading && <Loading />}
        {q.data?.items.length === 0 && <div className="empty card">No hay duplicados pendientes.</div>}
        {(q.data?.items ?? []).map((c) => (
          <div key={c.id} className="card card-pad" style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 16, alignItems: "center" }}>
            <Side s={c.a} />
            <Side s={c.b} />
            <div className="stack" style={{ gap: 6, alignItems: "stretch" }}>
              <span className="small muted" style={{ textAlign: "center" }}>
                similitud {Math.round(c.score * 100)}%
              </span>
              <button className="btn sm primary" disabled={decide.isPending} onClick={() => decide.mutate({ id: c.id, decision: "merge" })}>
                Misma propiedad
              </button>
              <button className="btn sm" disabled={decide.isPending} onClick={() => decide.mutate({ id: c.id, decision: "reject" })}>
                Distintas
              </button>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

function Side({ s }: { s: DedupSide }) {
  return (
    <div style={{ minWidth: 0 }}>
      <a href={s.url} target="_blank" rel="noreferrer" style={{ fontWeight: 500 }}>
        {s.title ?? "Sin título"}
      </a>
      <div className="small ink2">
        {money(s.price, s.currency)} · {area(s.area_m2)} · {s.locality ?? "—"}
      </div>
      <div className="small muted">{s.source_id}</div>
    </div>
  );
}
