import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";
import { api, Status } from "./api";
import { ToastProvider } from "./components/ui";
import { FiltersProvider } from "./filters";
import { ago, dateTime } from "./format";
import { HighlightsPage } from "./pages/Highlights";
import { MapPage } from "./pages/Map";
import { MonitorPage } from "./pages/Monitor";
import { PropertiesPage } from "./pages/Properties";
import { SourcesPage } from "./pages/Sources";
import { StatsPage } from "./pages/Stats";
import "./styles.css";

const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: 1 } },
});

function StatusPill() {
  const q = useQuery({ queryKey: ["status"], queryFn: () => api.get<Status>("/status"), refetchInterval: 15_000 });
  const s = q.data;
  if (!s) return null;
  const busy = s.running > 0;
  const what = s.running_jobs[0];
  return (
    <NavLink to="/monitoreo" className="status-pill" title={`Última corrida: ${dateTime(s.last_run_at)}`}>
      <span className={`dot${busy ? " on" : ""}`} />
      <span className="label">
        {busy ? `Actualizando ${what?.source_id ?? ""}` : "En espera"} · última corrida {ago(s.last_run_at)}
        {s.queued > 0 ? ` · ${s.queued} en cola` : ""}
      </span>
    </NavLink>
  );
}

function App() {
  const defaults = useQuery({ queryKey: ["search-defaults"], queryFn: () => api.get<Record<string, any>>("/search/defaults") });
  const maxMinutes = Number(defaults.data?.max_drive_minutes ?? 150);
  const tabs = [
    ["/propiedades", "Propiedades"],
    ["/destacados", "⭐ Destacados"],
    ["/estadisticas", "Estadísticas"],
    ["/mapa", "Mapa"],
    ["/fuentes", "Fuentes"],
    ["/monitoreo", "Monitoreo"],
  ];
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <svg viewBox="0 0 32 32" aria-hidden>
            <path d="M2 26 L12 10 L18 18 L22 13 L30 26 Z" fill="var(--accent)" />
          </svg>
          Patagonia Land
        </div>
        <nav className="nav">
          {tabs.map(([to, label]) => (
            <NavLink key={to} to={to}>
              {label}
            </NavLink>
          ))}
        </nav>
        <StatusPill />
      </header>
      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/propiedades" replace />} />
          <Route path="/propiedades" element={<PropertiesPage maxMinutes={maxMinutes} />} />
          <Route path="/destacados" element={<HighlightsPage />} />
          <Route path="/estadisticas" element={<StatsPage maxMinutes={maxMinutes} />} />
          <Route path="/mapa" element={<MapPage />} />
          <Route path="/fuentes" element={<SourcesPage />} />
          <Route path="/monitoreo" element={<MonitorPage />} />
          <Route path="*" element={<Navigate to="/propiedades" replace />} />
        </Routes>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <BrowserRouter>
          <FiltersProvider>
            <App />
          </FiltersProvider>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
