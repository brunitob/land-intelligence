import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { RUN_STATUS } from "../format";

// ------------------------------------------------------------------ toasts
type Toast = { msg: string; error?: boolean; id: number };
const ToastCtx = createContext<(msg: string, error?: boolean) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null);
  const show = useCallback((msg: string, error = false) => setToast({ msg, error, id: Date.now() }), []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), toast.error ? 6000 : 3000);
    return () => clearTimeout(t);
  }, [toast]);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {toast && (
        <div className={`toast${toast.error ? " error" : ""}`} role="status" key={toast.id}>
          {toast.msg}
        </div>
      )}
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

// ------------------------------------------------------------------ piezas chicas
export function Spinner() {
  return <span className="spinner" aria-label="Cargando" />;
}

export function Loading({ label = "Cargando…" }: { label?: string }) {
  return (
    <div className="empty row" style={{ justifyContent: "center" }}>
      <Spinner /> {label}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  return <div className="alert error">No se pudo cargar: {error instanceof Error ? error.message : String(error)}</div>;
}

export function Chips<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: T[];
  value: T[];
  onChange: (v: T[]) => void;
  label?: (o: T) => string;
}) {
  return (
    <div className="chips">
      {options.map((o) => {
        const on = value.includes(o);
        return (
          <button
            type="button"
            key={o}
            className={`chip${on ? " on" : ""}`}
            aria-pressed={on}
            onClick={() => onChange(on ? value.filter((x) => x !== o) : [...value, o])}
          >
            {label ? label(o) : o}
          </button>
        );
      })}
    </div>
  );
}

export function RunBadge({ status, broken }: { status: string | null | undefined; broken?: boolean }) {
  if (broken) return <span className="badge warn">⚠ Posible rotura</span>;
  if (!status) return <span className="badge">Sin corridas</span>;
  const cls = status === "success" ? "good" : status === "partial" ? "warn" : status === "running" ? "accent" : "bad";
  const icon = status === "success" ? "✓" : status === "partial" ? "◐" : status === "running" ? "…" : "✕";
  return (
    <span className={`badge ${cls}`}>
      {icon} {RUN_STATUS[status] ?? status}
    </span>
  );
}

export function Meter({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  return (
    <span className="row nowrap" style={{ gap: 6, flexWrap: "nowrap" }} title={`${Math.round(value * 100)} %`}>
      <span className="meter">
        <span style={{ width: `${Math.round(value * 100)}%` }} />
      </span>
      <span className="small ink2">{Math.round(value * 100)}%</span>
    </span>
  );
}

export function Drawer({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <>
      <div className="backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true">
        {children}
      </aside>
    </>
  );
}

// ------------------------------------------------------------------ orden de tablas
export type Sort = { key: string; dir: 1 | -1 };

export function sortRows<T>(rows: T[], sort: Sort | null): T[] {
  if (!sort) return rows;
  return [...rows].sort((a: any, b: any) => {
    const x = a[sort.key];
    const y = b[sort.key];
    if (x === y) return 0;
    if (x === null || x === undefined) return 1; // vacíos siempre al final
    if (y === null || y === undefined) return -1;
    return (x < y ? -1 : 1) * sort.dir;
  });
}

export function Th({
  k,
  sort,
  setSort,
  children,
  num,
}: {
  k: string;
  sort: Sort | null;
  setSort: (s: Sort | null) => void;
  children: ReactNode;
  num?: boolean;
}) {
  const active = sort?.key === k;
  return (
    <th
      className={`sortable${num ? " num" : ""}`}
      aria-sort={active ? (sort!.dir === 1 ? "ascending" : "descending") : "none"}
      onClick={() => setSort(!active ? { key: k, dir: num ? -1 : 1 } : sort!.dir === (num ? -1 : 1) ? { key: k, dir: num ? 1 : -1 } : null)}
    >
      {children} {active ? (sort!.dir === 1 ? "▲" : "▼") : ""}
    </th>
  );
}
