import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, Highlight, HighlightListings } from "../api";
import { ListingDrawer } from "../components/ListingDrawer";
import { ListingTable } from "../components/ListingTable";
import { Chips, ErrorBox, Loading, Spinner, useToast } from "../components/ui";
import { useZones } from "../filters";
import { PROPERTY_TYPES, WATER } from "../format";

export function HighlightsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const hls = useQuery({ queryKey: ["highlights"], queryFn: () => api.get<Highlight[]>("/highlights") });
  const [activeId, setActiveId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const active = hls.data?.find((h) => h.id === activeId) ?? hls.data?.[0] ?? null;

  const create = useMutation({
    mutationFn: () => api.post<Highlight>("/highlights", { name: newName.trim() }),
    onSuccess: (h) => {
      qc.invalidateQueries({ queryKey: ["highlights"] });
      setActiveId(h.id);
      setCreating(false);
      setNewName("");
      toast(`Destacado “${h.name}” creado. Agregale avisos desde Propiedades o definile filtros.`);
    },
    onError: (e) => toast(String(e instanceof Error ? e.message : e), true),
  });

  if (hls.isLoading) return <Loading />;
  if (hls.error) return <ErrorBox error={hls.error} />;

  return (
    <div className="hl-layout">
      <div className="card">
        <div className="hl-list">
          {(hls.data ?? []).map((h) => (
            <button key={h.id} className={`hl-item${active?.id === h.id ? " active" : ""}`} onClick={() => setActiveId(h.id)}>
              <span>⭐ {h.name}</span>
              <span className="muted small">{h.total}</span>
            </button>
          ))}
          {creating ? (
            <form
              className="stack"
              style={{ padding: 8, gap: 6 }}
              onSubmit={(e) => {
                e.preventDefault();
                if (newName.trim()) create.mutate();
              }}
            >
              <input className="input" autoFocus placeholder="Casa para envejecer" value={newName} onChange={(e) => setNewName(e.target.value)} />
              <div className="row">
                <button className="btn primary sm" disabled={!newName.trim() || create.isPending}>
                  Crear
                </button>
                <button type="button" className="btn ghost sm" onClick={() => setCreating(false)}>
                  Cancelar
                </button>
              </div>
            </form>
          ) : (
            <button className="hl-item ink2" onClick={() => setCreating(true)}>
              ➕ Nuevo destacado
            </button>
          )}
        </div>
      </div>
      {active ? <HighlightView key={active.id} h={active} onDeleted={() => setActiveId(null)} /> : <div className="empty">Creá tu primer destacado.</div>}
    </div>
  );
}

function HighlightView({ h, onDeleted }: { h: Highlight; onDeleted: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const items = useQuery({
    queryKey: ["hl-listings", h.id],
    queryFn: () => api.get<HighlightListings>(`/highlights/${h.id}/listings`),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["hl-listings", h.id] });
    qc.invalidateQueries({ queryKey: ["highlights"] });
    qc.invalidateQueries({ queryKey: ["listing-hl"] });
  };
  const exclude = useMutation({
    mutationFn: (id: number) => api.put(`/highlights/${h.id}/listings/${id}`, { mode: "excluded" }),
    onSuccess: () => {
      refresh();
      toast("Quitado del destacado");
    },
  });
  const restore = useMutation({
    mutationFn: (id: number) => api.del(`/highlights/${h.id}/listings/${id}`),
    onSuccess: refresh,
  });
  const hasFilter = h.keywords.length || h.zones.length || h.property_types.length || h.water_classes.length || h.max_price_usd || h.min_area_m2;

  return (
    <div className="stack">
      <div className="spread">
        <div>
          <h2 className="row">
            ⭐ {h.name} {items.isFetching && <Spinner />}
          </h2>
          <div className="small muted" style={{ marginTop: 4 }}>
            {items.data?.total ?? h.total} avisos
            {h.fijados ? ` · ${h.fijados} agregados a mano` : ""}
            {h.excluidos ? ` · ${h.excluidos} quitados a mano` : ""}
            {" · "}
            {hasFilter ? describe(h) : "sin filtro automático: solo los que agregás a mano"}
          </div>
        </div>
        <button className="btn" onClick={() => setEditing(!editing)}>
          {editing ? "Cerrar filtros" : "Editar filtros"}
        </button>
      </div>
      {editing && <HighlightForm h={h} onSaved={() => setEditing(false)} onDeleted={onDeleted} />}
      <div className="card">
        {items.isLoading ? (
          <Loading />
        ) : items.error ? (
          <div className="card-pad">
            <ErrorBox error={items.error} />
          </div>
        ) : (items.data?.items ?? []).length === 0 ? (
          <div className="empty">Todavía vacío. En Propiedades, tildá avisos y elegí “Agregar a ⭐ {h.name}”.</div>
        ) : (
          <ListingTable
            rows={items.data!.items}
            onOpen={setOpen}
            extraCol={{
              header: "",
              cell: (l) => (
                <span className="row nowrap" style={{ flexWrap: "nowrap" }}>
                  <span className={`badge ${l.origin === "fijado" ? "accent" : ""}`} title={l.origin === "fijado" ? "Agregado a mano" : "Entra por el filtro"}>
                    {l.origin === "fijado" ? "a mano" : "filtro"}
                  </span>
                  <button className="btn ghost sm" title="Quitar de este destacado" onClick={() => exclude.mutate(l.id)}>
                    ✕
                  </button>
                </span>
              ),
            }}
          />
        )}
      </div>
      {(items.data?.excluded ?? []).length > 0 && (
        <details className="card card-pad">
          <summary>Quitados a mano ({items.data!.excluded.length})</summary>
          <table className="t" style={{ marginTop: 8 }}>
            <tbody>
              {items.data!.excluded.map((x) => (
                <tr key={x.id}>
                  <td>
                    <a href={x.url} target="_blank" rel="noreferrer">
                      {x.title}
                    </a>
                  </td>
                  <td className="num">
                    <button className="btn sm" onClick={() => restore.mutate(x.id)}>
                      Restaurar
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      {open !== null && <ListingDrawer id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function describe(h: Highlight): string {
  const parts: string[] = [];
  if (h.keywords.length) parts.push(`${h.match_mode === "all" ? "todas" : "alguna"} de: ${h.keywords.join(", ")}`);
  if (h.zones.length) parts.push(h.zones.join(", "));
  if (h.property_types.length) parts.push(h.property_types.join(", "));
  if (h.max_price_usd) parts.push(`≤ US$ ${h.max_price_usd.toLocaleString("es-AR")}`);
  if (h.min_area_m2) parts.push(`≥ ${h.min_area_m2.toLocaleString("es-AR")} m²`);
  if (h.water_classes.length) parts.push(h.water_classes.map((w) => WATER[w] ?? w).join(", "));
  return `filtro: ${parts.join(" · ")}`;
}

function HighlightForm({ h, onSaved, onDeleted }: { h: Highlight; onSaved: () => void; onDeleted: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const zones = useZones();
  const [f, setF] = useState({
    name: h.name,
    keywords: h.keywords.join(", "),
    match_mode: h.match_mode,
    zones: h.zones,
    property_types: h.property_types,
    water_classes: h.water_classes,
    max_price_usd: h.max_price_usd?.toString() ?? "",
    min_area_m2: h.min_area_m2?.toString() ?? "",
    include_rentals: h.include_rentals,
  });
  useEffect(() => setF((x) => ({ ...x, name: h.name })), [h.name]);
  const save = useMutation({
    mutationFn: () =>
      api.patch(`/highlights/${h.id}`, {
        name: f.name.trim(),
        keywords: f.keywords.split(",").map((k) => k.trim()).filter(Boolean),
        match_mode: f.match_mode,
        zones: f.zones,
        property_types: f.property_types,
        water_classes: f.water_classes,
        max_price_usd: f.max_price_usd ? Number(f.max_price_usd) : null,
        min_area_m2: f.min_area_m2 ? Number(f.min_area_m2) : null,
        include_rentals: f.include_rentals,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["highlights"] });
      qc.invalidateQueries({ queryKey: ["hl-listings", h.id] });
      toast("Guardado");
      onSaved();
    },
    onError: (e) => toast(String(e instanceof Error ? e.message : e), true),
  });
  const del = useMutation({
    mutationFn: () => api.del(`/highlights/${h.id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["highlights"] });
      toast(`“${h.name}” borrado`);
      onDeleted();
    },
  });

  return (
    <form
      className="card card-pad stack"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <div className="form-grid">
        <label className="field">
          Nombre
          <input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </label>
        <label className="field">
          Palabras clave (separadas por coma)
          <input className="input" value={f.keywords} placeholder="lago, costa, playa" onChange={(e) => setF({ ...f, keywords: e.target.value })} />
        </label>
        <label className="field">
          Coincidir con
          <select className="select" value={f.match_mode} onChange={(e) => setF({ ...f, match_mode: e.target.value as "any" | "all" })}>
            <option value="any">alguna palabra</option>
            <option value="all">todas las palabras</option>
          </select>
        </label>
        <label className="field">
          Precio máx. (USD)
          <input className="input" inputMode="numeric" placeholder="sin límite" value={f.max_price_usd} onChange={(e) => setF({ ...f, max_price_usd: e.target.value.replace(/\D/g, "") })} />
        </label>
        <label className="field">
          Superficie mín. (m²)
          <input className="input" inputMode="numeric" placeholder="sin mínimo" value={f.min_area_m2} onChange={(e) => setF({ ...f, min_area_m2: e.target.value.replace(/\D/g, "") })} />
        </label>
      </div>
      <div className="field">
        <span>Tipo</span>
        <Chips options={PROPERTY_TYPES} value={f.property_types} onChange={(v) => setF({ ...f, property_types: v })} />
      </div>
      <div className="field">
        <span>Zonas</span>
        <Chips options={(zones.data ?? []).map((z) => z.zone)} value={f.zones} onChange={(v) => setF({ ...f, zones: v })} />
      </div>
      <div className="field">
        <span>Agua</span>
        <Chips options={Object.keys(WATER)} value={f.water_classes} onChange={(v) => setF({ ...f, water_classes: v })} label={(w) => WATER[w]} />
      </div>
      <label className="check small">
        <input type="checkbox" checked={f.include_rentals} onChange={(e) => setF({ ...f, include_rentals: e.target.checked })} />
        Incluir alquileres
      </label>
      <p className="muted small" style={{ margin: 0 }}>
        Sin palabras clave ni filtros, el destacado muestra solo los avisos que agregás a mano. Las palabras se buscan en título y descripción, sin importar tildes ni plural.
      </p>
      <div className="spread">
        <button className="btn primary" disabled={save.isPending || !f.name.trim()}>
          Guardar
        </button>
        <button
          type="button"
          className="btn danger"
          onClick={() => window.confirm(`¿Borrar el destacado “${h.name}”? Los avisos no se borran.`) && del.mutate()}
        >
          Borrar destacado
        </button>
      </div>
    </form>
  );
}
