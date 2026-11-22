import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, Change, Watched } from "../api";
import { ListingDrawer } from "../components/ListingDrawer";
import { ErrorBox, Loading, Spinner, useToast } from "../components/ui";
import { ago, area, CHANGE_LABELS, dateTime, money } from "../format";

// Fichas puntuales que el worker revisa cada 6 h. Resalta las que cambiaron desde la última vez que se marcaron vistas.

const STATUS: Record<Watched["status"], [string, string]> = {
  pending: ["Pendiente", ""],
  ok: ["OK", "good"],
  blocked: ["Bloqueado", "bad"],
  robots: ["No permitido (robots.txt)", "bad"],
  gone: ["Ya no está publicado", "warn"],
  error: ["Error", "bad"],
};

function host(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function changeText(c: Change) {
  const label = CHANGE_LABELS[c.change_type] ?? c.change_type;
  const pct = c.pct_change != null ? ` ${c.pct_change > 0 ? "+" : ""}${c.pct_change.toFixed(1)} %` : "";
  const nv = c.new_value as { price?: number; currency?: string } | null;
  const ov = c.old_value as { price?: number; currency?: string } | null;
  const prices = c.change_type.startsWith("price_") && ov?.price != null && nv?.price != null
    ? ` (${money(ov.price, ov.currency)} → ${money(nv.price, nv.currency)})` : "";
  return `${label}${pct}${prices}`;
}

export function WatchPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState<number | null>(null);
  const [text, setText] = useState("");
  const q = useQuery({
    queryKey: ["watch"],
    queryFn: () => api.get<Watched[]>("/watch"),
    refetchInterval: (query) => ((query.state.data ?? []).some((w) => w.status === "pending") ? 5000 : 60_000),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["watch"] });
    qc.invalidateQueries({ queryKey: ["status"] });
  };

  const urls = Array.from(new Set((text.match(/https?:\/\/[^\s)\]>"']+/g) ?? []).map((u) => u.replace(/[.,;]+$/, ""))));
  const add = useMutation({
    mutationFn: () => api.post<{ added: string[]; existing: string[]; rejected: { url: string; error: string }[] }>("/watch", { urls }),
    onSuccess: (r) => {
      const parts = [`${r.added.length} agregados`];
      if (r.existing.length) parts.push(`${r.existing.length} ya estaban`);
      if (r.rejected.length) parts.push(`${r.rejected.length} rechazados`);
      toast(parts.join(" · ") + (r.added.length ? ". Se revisan en unos minutos." : ""), r.rejected.length > 0 && !r.added.length);
      setText("");
      refresh();
    },
    onError: (e) => toast(`No se pudieron agregar: ${e instanceof Error ? e.message : e}`, true),
  });
  const seen = useMutation({
    mutationFn: (ids?: number[]) => api.post("/watch/seen", { ids: ids ?? null }),
    onSuccess: refresh,
  });
  const check = useMutation({
    mutationFn: () => api.post("/watch/check"),
    onSuccess: () => toast("Revisión encolada: tarda unos minutos"),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/watch/${id}`),
    onSuccess: () => {
      toast("Quitado del seguimiento");
      refresh();
    },
  });

  const rows = q.data ?? [];
  const changed = rows.filter((w) => w.unseen > 0).length;

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="spread">
        <h2 className="row">
          📌 Seguimiento {q.isFetching && <Spinner />}
        </h2>
        <div className="row">
          {changed > 0 && (
            <button className="btn sm" disabled={seen.isPending} onClick={() => seen.mutate(undefined)}>
              ✓ Marcar todo como visto ({changed})
            </button>
          )}
          <button className="btn sm" disabled={check.isPending || !rows.length} onClick={() => check.mutate()}>
            ↻ Revisar ahora
          </button>
        </div>
      </div>
      <div className="muted small">
        Cada ficha se revisa automáticamente cada 6 horas. Las que cambiaron (precio, superficie, descripción, baja) quedan resaltadas hasta que las marques como vistas.
      </div>

      <div className="card card-pad stack watch-add" style={{ gap: 8 }}>
        <strong>Agregar links</strong>
        <textarea
          className="input"
          placeholder="Pegá uno o varios links de fichas, uno por línea"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="row">
          <button className="btn primary" disabled={!urls.length || add.isPending} onClick={() => add.mutate()}>
            {add.isPending ? <Spinner /> : "📌"} Seguir {urls.length > 0 ? `${urls.length} link${urls.length > 1 ? "s" : ""}` : ""}
          </button>
          <span className="muted small">Zonaprop y Argenprop bloquean a los bots: esos links quedan como “Bloqueado”.</span>
        </div>
      </div>

      <div className="card table-wrap">
        {q.isLoading ? (
          <Loading />
        ) : q.error ? (
          <div className="card-pad">
            <ErrorBox error={q.error} />
          </div>
        ) : rows.length === 0 ? (
          <div className="empty">Todavía no hay fichas en seguimiento.</div>
        ) : (
          <table className="t">
            <thead>
              <tr>
                <th>Ficha</th>
                <th className="num">Precio</th>
                <th className="num">Superficie</th>
                <th>Estado</th>
                <th>Último cambio</th>
                <th>Revisada</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((w) => {
                const l = w.listing;
                const [label, cls] = STATUS[w.status] ?? [w.status, ""];
                const last = w.changes.find((c) => c.change_type !== "new_listing");
                return (
                  <tr key={w.id} className={`${l ? "clickable" : ""}${w.unseen ? " changed" : ""}`} onClick={() => l && setOpen(l.id)}>
                    <td className="title">
                      <span className="clip" title={l?.title ?? w.url}>
                        {l?.title ?? <span className="muted">{w.url}</span>}
                      </span>
                      <div className="small muted">
                        {host(w.url)}
                        {l?.locality ? ` · ${l.locality}` : ""}
                      </div>
                    </td>
                    <td className="num nowrap">{l ? money(l.price, l.currency) : "—"}</td>
                    <td className="num nowrap">{l ? area(l.area_m2) : "—"}</td>
                    <td>
                      <span className={`badge ${cls}`} title={w.last_error ?? ""}>
                        {label}
                      </span>
                    </td>
                    <td className="small">
                      {last ? (
                        <>
                          {w.unseen > 0 && <span className="badge warn">nuevo</span>} {changeText(last)}
                          <div className="muted">{dateTime(last.detected_at)}</div>
                        </>
                      ) : (
                        <span className="muted">Sin cambios</span>
                      )}
                    </td>
                    <td className="small muted nowrap">{w.last_checked_at ? ago(w.last_checked_at) : "todavía no"}</td>
                    <td className="nowrap" onClick={(e) => e.stopPropagation()}>
                      {w.unseen > 0 && (
                        <button className="btn sm" title="Marcar como visto" onClick={() => seen.mutate([w.id])}>
                          ✓
                        </button>
                      )}{" "}
                      <a href={w.url} target="_blank" rel="noreferrer" title="Abrir ficha original">
                        ↗
                      </a>{" "}
                      <button
                        className="btn ghost sm"
                        title="Dejar de seguir"
                        onClick={() => confirm("¿Dejar de seguir esta ficha?") && remove.mutate(w.id)}
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      {open !== null && <ListingDrawer id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
