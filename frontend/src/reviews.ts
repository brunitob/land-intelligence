import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { useToast } from "./components/ui";

// Marcar avisos como revisados (salen de "Nuevos sin revisar") o devolverlos a nuevos.
export function useMarkReviewed() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: ({ ids, reviewed }: { ids: number[]; reviewed: boolean }) => api.post("/listings/review", { ids, reviewed }),
    onSuccess: (_r, { ids, reviewed }) => {
      const n = ids.length;
      toast(reviewed ? `${n === 1 ? "Aviso marcado" : `${n} avisos marcados`} como revisado${n === 1 ? "" : "s"}` : "Vuelve a estar entre los nuevos");
      qc.invalidateQueries({ queryKey: ["properties"] });
      qc.invalidateQueries({ queryKey: ["listing"] });
      qc.invalidateQueries({ queryKey: ["hl-listings"] });
    },
    onError: (e) => toast(`No se pudo marcar: ${e instanceof Error ? e.message : e}`, true),
  });
}
