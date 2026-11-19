import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, Highlight } from "../api";
import { FiltersPanel } from "../components/FiltersPanel";
import { ListingDrawer } from "../components/ListingDrawer";
import { ListingTable } from "../components/ListingTable";
import { ErrorBox, Loading, Spinner, useToast } from "../components/ui";
import { useFilters, useProperties } from "../filters";
import { useMarkReviewed } from "../reviews";
import { num } from "../format";

const NEW = "__new__";

export function PropertiesPage({ maxMinutes }: { maxMinutes: number }) {
  const { filters, setFilters } = useFilters();
  const props = useProperties(filters);
  const mark = useMarkReviewed();
  const newCount = props.data?.new_count ?? 0;
  const shownNew = (props.data?.items ?? []).filter((l) => l.is_new).map((l) => l.id);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [open, setOpen] = useState<number | null>(null);

  return (
    <div className="props-layout">
      <FiltersPanel maxMinutes={maxMinutes} />
      <div className="stack">
        <div className="spread">
          <h2 className="row">
            {props.data ? `${num(props.data.total)} avisos` : "Avisos"}
            {props.isFetching && <Spinner />}
          </h2>
          <div className="row">
            <button
              className={`chip${filters.only_new ? " on" : ""}`}
              onClick={() => setFilters({ ...filters, only_new: !filters.only_new })}
              title="Avisos que todavía no marcaste como revisados"
            >
              🆕 Nuevos sin revisar: {num(newCount)}
            </button>
            {filters.only_new && shownNew.length > 0 && (
              <button
                className="btn sm"
                disabled={mark.isPending}
                onClick={() => {
                  if (confirm(`¿Marcar los ${shownNew.length} avisos de esta lista como revisados?`)) mark.mutate({ ids: shownNew, reviewed: true });
                }}
              >
                ✓ Marcar todos como revisados
              </button>
            )}
          </div>
        </div>
        <div className="muted small">Click en un aviso para ver el detalle · tildá para agregar a un destacado o marcar como revisado</div>
        {props.data?.airport_filter_mode === "region" && (
          <div className="alert info small">Todavía no hay tiempos de manejo calculados: el filtro por aeropuerto usa la región.</div>
        )}
        <div className="card">
          {selected.size > 0 && <BulkBar ids={[...selected]} onDone={() => setSelected(new Set())} />}
          {props.isLoading ? (
            <Loading />
          ) : props.error ? (
            <div className="card-pad">
              <ErrorBox error={props.error} />
            </div>
          ) : (
            <ListingTable rows={props.data?.items ?? []} selected={selected} onSelect={setSelected} onOpen={setOpen} />
          )}
        </div>
      </div>
      {open !== null && <ListingDrawer id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function BulkBar({ ids, onDone }: { ids: number[]; onDone: () => void }) {
  const qc = useQueryClient();
  const mark = useMarkReviewed();
  const toast = useToast();
  const hls = useQuery({ queryKey: ["highlights"], queryFn: () => api.get<Highlight[]>("/highlights") });
  const [dest, setDest] = useState<string>("");
  const [name, setName] = useState("");
  const target = dest || (hls.data?.[0] ? String(hls.data[0].id) : NEW);

  const add = useMutation({
    mutationFn: async () => {
      let h: Highlight;
      if (target === NEW) h = await api.post<Highlight>("/highlights", { name: name.trim() });
      else h = hls.data!.find((x) => String(x.id) === target)!;
      await Promise.all(ids.map((id) => api.put(`/highlights/${h.id}/listings/${id}`, { mode: "pinned" })));
      return h;
    },
    onSuccess: (h) => {
      toast(`${ids.length} ${ids.length === 1 ? "aviso agregado" : "avisos agregados"} a “${h.name}”`);
      qc.invalidateQueries({ queryKey: ["highlights"] });
      qc.invalidateQueries({ queryKey: ["hl-listings"] });
      qc.invalidateQueries({ queryKey: ["listing-hl"] });
      setName("");
      onDone();
    },
    onError: (e) => toast(`No se pudo agregar: ${e instanceof Error ? e.message : e}`, true),
  });

  return (
    <div className="bulkbar">
      <strong>{ids.length} elegidos</strong>
      <span className="ink2">Agregar a</span>
      <select className="select" value={target} onChange={(e) => setDest(e.target.value)}>
        {(hls.data ?? []).map((h) => (
          <option key={h.id} value={h.id}>
            ⭐ {h.name}
          </option>
        ))}
        <option value={NEW}>➕ Nuevo destacado…</option>
      </select>
      {target === NEW && (
        <input className="input" autoFocus placeholder="Nombre, p. ej. Casa para envejecer" value={name} onChange={(e) => setName(e.target.value)} />
      )}
      <button className="btn primary" disabled={add.isPending || (target === NEW && !name.trim())} onClick={() => add.mutate()}>
        {add.isPending ? <Spinner /> : "⭐"} Agregar
      </button>
      <button className="btn" disabled={mark.isPending} onClick={() => mark.mutate({ ids, reviewed: true }, { onSuccess: onDone })}>
        ✓ Marcar revisados
      </button>
      <button className="btn ghost" onClick={onDone}>
        Cancelar
      </button>
    </div>
  );
}
