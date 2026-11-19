import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";
import { api, ApiError, Status } from "./api";
import { Login } from "./components/Login";
import { Loading, ToastProvider } from "./components/ui";
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

type Me = { username: string | null; auth_required: boolean };

// Sin sesión válida muestra el login; si una sesión vence mientras se usa la app, vuelve al login.
function AuthGate() {
  const qc = useQueryClient();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<Me>("/auth/me"),
    retry: false,
    staleTime: Infinity,
  });
  useEffect(() => {
    const onExpired = () => qc.setQueryData(["me"], null);
    window.addEventListener("auth:required", onExpired);
    return () => window.removeEventListener("auth:required", onExpired);
  }, [qc]);
  const unauth = (me.error instanceof ApiError && me.error.status === 401) || (me.isSuccess && me.data === null);
  if (me.isLoading) return <Loading />;
  if (unauth) {
    return (
      <Login
        onLogin={() => {
          qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
          me.refetch();
        }}
      />
    );
  }
  return (
    <FiltersProvider>
      <App me={me.data ?? null} />
    </FiltersProvider>
  );
}

function UserMenu({ me }: { me: Me | null }) {
  const qc = useQueryClient();
  if (!me?.auth_required) return null;
  const logout = async () => {
    await api.post("/auth/logout").catch(() => undefined);
    qc.setQueryData(["me"], null);
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
  };
  return (
    <div className="user-menu">
      <span>{me.username}</span>
      <button className="btn ghost sm" onClick={logout}>
        Salir
      </button>
    </div>
  );
}

function App({ me }: { me: Me | null }) {
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
        <UserMenu me={me} />
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
          <AuthGate />
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
