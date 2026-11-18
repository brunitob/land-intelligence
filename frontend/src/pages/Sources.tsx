import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useMemo, useState } from "react";
import { api, CrawlRun, Job, Source } from "../api";
import { ErrorBox, Loading, RunBadge, Sort, sortRows, Spinner, Th, useToast } from "../components/ui";
import { ago, dateTime, num, num1, REGIONS } from "../format";

export function SourcesPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["sources"], queryFn: () => api.get<Source[]>("/sources"), refetchInterval: 30_000 });
  const [open, setOpen] = useState<string | null>(null);
  const [onlyOn, setOnlyOn] = useState(false);
  const [sort, setSort] = useState<Sort | null>(null);
  const rows = useMemo(() => {
    const r = (q.data ?? []).map((s) => ({ ...s, _status: s.last_run?.status ?? "", _last: s.last_run?.started_at ?? "" }));
    return sortRows(onlyOn ? r.filter((s) => s.enabled) : r, sort ?? { key: "created_at", dir: -1 });
  }, [q.data, onlyOn, sort]);
  const p = { sort, setSort };

  return (
    <div className="stack" style={{ gap: 16 }}>
      <AddSource onAdded={() => qc.invalidateQueries({ queryKey: ["sources"] })} />
      <div className="spread">
        <h2 className="row">
          Inmobiliarias {q.data && <span className="muted">({q.data.length})</span>} {q.isFetching && <Spinner />}
        </h2>
        <label className="check small">
          <input type="checkbox" checked={onlyOn} onChange={(e) => setOnlyOn(e.target.checked)} /> Solo activas
        </label>
      </div>
      {q.isLoading ? (
        <Loading />
      ) : q.error ? (
        <ErrorBox error={q.error} />
      ) : (
        <div className="card table-wrap">
          <table className="t">
            <thead>
              <tr>
                <Th k="name" {...p}>Fuente</Th>
                <Th k="enabled" {...p}>Estado</Th>
                <Th k="_status" {...p}>Último crawl</Th>
                <Th k="_last" {...p}>Cuándo</Th>
                <Th k="active_listings" num {...p}>Avisos activos</Th>
                <Th k="region" {...p}>Región</Th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <Fragment key={s.id}>
                  <tr className="clickable" onClick={() => setOpen(open === s.id ? null : s.id)}>
                    <td>
                      <div style={{ fontWeight: 500 }}>{s.name}</div>
                      <div className="small muted">{s.base_url.replace(/^https?:\/\//, "")}</div>
                    </td>
                    <td>{s.enabled ? <span className="badge good">Activa</span> : <span className="badge">Pausada</span>}</td>
                    <td>
                      <RunBadge status={s.last_run?.status} broken={s.last_run?.possibly_broken} />
                    </td>
                    <td className="nowrap muted" title={dateTime(s.last_run?.started_at)}>
                      {ago(s.last_run?.started_at)}
                    </td>
                    <td className="num">{num(s.active_listings)}</td>
                    <td>{REGIONS[s.region ?? ""] ?? "—"}</td>
                    <td className="num muted">{open === s.id ? "▲" : "▼"}</td>
                  </tr>
                  {open === s.id && (
                    <tr>
                      <td colSpan={7} style={{ background: "var(--surface-2)" }}>
                        <SourceDetail s={s} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function AddSource({ onAdded }: { onAdded: () => void }) {
  const toast = useToast();
  const [url, setUrl] = useState("");
  const [start, setStart] = useState("");
  const [region, setRegion] = useState("bariloche");
  const add = useMutation({
    mutationFn: () => api.post<Source & { job?: Job }>("/sources", { base_url: url.trim(), region, start_urls: start.trim() ? [start.trim()] : [] }),
    onSuccess: (s) => {
      toast(`“${s.name}” agregada. La inspección arranca en breve; después corre el primer crawl.`);
      setUrl("");
      setStart("");
      onAdded();
    },
    onError: (e) => toast(`No se pudo agregar: ${e instanceof Error ? e.message : e}`, true),
  });
  return (
    <form
      className="card card-pad stack"
      onSubmit={(e) => {
        e.preventDefault();
        if (url.trim()) add.mutate();
      }}
    >
      <h3>Agregar inmobiliaria</h3>
      <div className="form-grid">
        <label className="field">
          URL del sitio
          <input className="input" type="url" required placeholder="https://www.inmobiliaria.com.ar" value={url} onChange={(e) => setUrl(e.target.value)} />
        </label>
        <label className="field">
          URL del listado de terrenos (opcional)
          <input className="input" type="url" placeholder="https://…/propiedades?tipo=terreno" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label className="field">
          Región
          <select className="select" value={region} onChange={(e) => setRegion(e.target.value)}>
            {Object.entries(REGIONS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div>
        <button className="btn primary" disabled={add.isPending || !url.trim()}>
          {add.isPending && <Spinner />} Agregar e inspeccionar
        </button>
      </div>
    </form>
  );
}

function SourceDetail({ s }: { s: Source }) {
  const qc = useQueryClient();
  const toast = useToast();
  const runs = useQuery({ queryKey: ["runs", s.id], queryFn: () => api.get<CrawlRun[]>(`/sources/${s.id}/runs`, { limit: 10 }) });
  const action = useMutation({
    mutationFn: (what: "inspect" | "crawl" | "toggle") =>
      what === "toggle" ? api.patch(`/sources/${s.id}`, { enabled: !s.enabled }) : api.post<Job>(`/sources/${s.id}/${what}`),
    onSuccess: (_, what) => {
      toast(what === "toggle" ? (s.enabled ? "Fuente pausada" : "Fuente activada") : what === "crawl" ? "Crawl en cola" : "Inspección en cola");
      qc.invalidateQueries({ queryKey: ["sources"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["status"] });
    },
    onError: (e) => toast(String(e instanceof Error ? e.message : e), true),
  });
  const last = runs.data?.[0];
  const errs = (last?.errors ?? []).filter((e) => e.stage !== "note");
  const notes = (last?.errors ?? []).filter((e) => e.stage === "note");

  return (
    <div className="stack" style={{ padding: "6px 2px" }}>
      <div className="row">
        <button className="btn sm" onClick={() => action.mutate("crawl")} disabled={action.isPending}>
          Crawlear ahora
        </button>
        <button className="btn sm" onClick={() => action.mutate("inspect")} disabled={action.isPending}>
          Volver a inspeccionar
        </button>
        <button className={`btn sm${s.enabled ? " danger" : ""}`} onClick={() => action.mutate("toggle")} disabled={action.isPending}>
          {s.enabled ? "Pausar" : "Activar"}
        </button>
        <a className="btn sm ghost" href={s.base_url} target="_blank" rel="noreferrer">
          Abrir sitio ↗
        </a>
        <span className="small muted">
          Cada {s.crawl_interval_hours} h · hasta {s.max_pages_per_run} páginas
          {s.profile ? ` · perfil v${s.profile.version} (${s.profile.origin})` : " · sin perfil todavía"}
        </span>
      </div>
      {notes.length > 0 && <div className="small ink2">{notes.map((n) => n.error).join(" · ")}</div>}
      {errs.length > 0 && (
        <details>
          <summary className="small">Errores de la última corrida ({errs.length})</summary>
          <ul className="small" style={{ margin: "6px 0", paddingLeft: 18 }}>
            {errs.slice(0, 20).map((e, i) => (
              <li key={i}>
                {e.url && <span className="muted">{e.url} — </span>}
                {e.error}
              </li>
            ))}
          </ul>
        </details>
      )}
      {runs.isLoading ? (
        <Loading />
      ) : (
        <div className="table-wrap">
          <table className="t small">
            <thead>
              <tr>
                <th>Inicio</th>
                <th>Estado</th>
                <th className="num">Páginas</th>
                <th className="num">Fichas</th>
                <th className="num">Válidas</th>
                <th className="num">% precio</th>
                <th className="num">% sup.</th>
                <th className="num">Errores</th>
                <th className="num">Min</th>
              </tr>
            </thead>
            <tbody>
              {(runs.data ?? []).map((r) => (
                <tr key={r.id}>
                  <td className="nowrap">{dateTime(r.started_at)}</td>
                  <td>
                    <RunBadge status={r.status} broken={r.possibly_broken} />
                  </td>
                  <td className="num">{num(r.pages_visited)}</td>
                  <td className="num">{num(r.details_discovered)}</td>
                  <td className="num">{num(r.valid_properties)}</td>
                  <td className="num">{num1(r.pct_with_price)}</td>
                  <td className="num">{num1(r.pct_with_area)}</td>
                  <td className="num">{num(r.errors_count)}</td>
                  <td className="num">{r.duration_seconds != null ? num1(r.duration_seconds / 60) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {runs.data?.length === 0 && <div className="empty">Todavía no corrió.</div>}
        </div>
      )}
    </div>
  );
}
