import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, Highlight } from "../api";
import { Spinner, useToast } from "./ui";

const NEW = "__new__";

// Agregar un aviso a un destacado (uno existente o uno nuevo). Muestra en cuáles ya está.
export function AddToHighlight({ listingId, compact = false }: { listingId: number; compact?: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const hls = useQuery({ queryKey: ["highlights"], queryFn: () => api.get<Highlight[]>("/highlights") });
  const inHl = useQuery({
    queryKey: ["listing-hl", listingId],
    queryFn: () => api.get<{ id: number; name: string; origin: string }[]>(`/listings/${listingId}/highlights`),
  });
  const [target, setTarget] = useState("");
  const [name, setName] = useState("");
  const options = (hls.data ?? []).filter((h) => !(inHl.data ?? []).some((x) => x.id === h.id));
  const chosen = target || (options[0] ? String(options[0].id) : NEW);

  const add = useMutation({
    mutationFn: async () => {
      const h = chosen === NEW ? await api.post<Highlight>("/highlights", { name: name.trim() }) : options.find((x) => String(x.id) === chosen)!;
      await api.put(`/highlights/${h.id}/listings/${listingId}`, { mode: "pinned" });
      return h;
    },
    onSuccess: (h) => {
      toast(`Agregado a “${h.name}”`);
      setTarget("");
      setName("");
      qc.invalidateQueries({ queryKey: ["listing-hl", listingId] });
      qc.invalidateQueries({ queryKey: ["highlights"] });
      qc.invalidateQueries({ queryKey: ["hl-listings"] });
    },
    onError: (e) => toast(`No se pudo agregar: ${e instanceof Error ? e.message : e}`, true),
  });

  if (inHl.isLoading || hls.isLoading) return <Spinner />;
  return (
    <div className="stack" style={{ gap: 6 }}>
      {(inHl.data ?? []).length > 0 && (
        <div className="row" style={{ gap: 4 }}>
          {inHl.data!.map((h) => (
            <span key={h.id} className="badge accent">
              ⭐ {h.name}
              {!compact && ` · ${h.origin}`}
            </span>
          ))}
        </div>
      )}
      <form
        className="row"
        style={{ gap: 6, flexWrap: compact ? "wrap" : undefined }}
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate();
        }}
      >
        <select className="select grow" value={chosen} onChange={(e) => setTarget(e.target.value)} aria-label="Destacado">
          {options.map((h) => (
            <option key={h.id} value={h.id}>
              ⭐ {h.name}
            </option>
          ))}
          <option value={NEW}>➕ Nuevo destacado…</option>
        </select>
        {chosen === NEW && (
          <input className="input grow" placeholder="Nombre del destacado" value={name} onChange={(e) => setName(e.target.value)} />
        )}
        <button className="btn primary" disabled={add.isPending || (chosen === NEW && !name.trim())}>
          {add.isPending && <Spinner />} Agregar
        </button>
      </form>
    </div>
  );
}
