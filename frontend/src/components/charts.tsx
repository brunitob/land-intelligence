import { ReactNode, useState } from "react";

// Gráficos simples en HTML: una serie = azul (--series-1); estados = verde OK / rojo error, siempre con leyenda.
// Hover con tooltip en cada barra; valores en formato argentino.

type Tip = { x: number; y: number; content: ReactNode } | null;

function useTip() {
  const [tip, setTip] = useState<Tip>(null);
  const bind = (content: ReactNode) => ({
    onMouseMove: (e: React.MouseEvent) => setTip({ x: e.clientX + 12, y: e.clientY + 12, content }),
    onMouseLeave: () => setTip(null),
  });
  const node = tip && (
    <div className="tip" style={{ left: Math.min(tip.x, window.innerWidth - 220), top: tip.y }}>
      {tip.content}
    </div>
  );
  return { bind, node };
}

export function HBar<T>({
  rows,
  label,
  value,
  format,
  tooltip,
}: {
  rows: T[];
  label: (r: T) => string;
  value: (r: T) => number;
  format: (n: number) => string;
  tooltip?: (r: T) => ReactNode;
}) {
  const { bind, node } = useTip();
  const max = Math.max(1, ...rows.map(value));
  if (!rows.length) return <div className="muted small">Sin datos.</div>;
  return (
    <div className="hbar">
      {rows.map((r, i) => (
        <div className="rowhit" key={i} {...bind(tooltip ? tooltip(r) : `${label(r)}: ${format(value(r))}`)}>
          <span className="lbl" title={label(r)}>
            {label(r)}
          </span>
          <span className="track">
            <span className="bar" style={{ width: `${(value(r) / max) * 85}%` }} />
            <span className="val">{format(value(r))}</span>
          </span>
        </div>
      ))}
      {node}
    </div>
  );
}

export function StackedColumns({
  days,
  series,
  format,
}: {
  days: { label: string; values: number[]; extra?: ReactNode }[];
  series: { name: string; color: string }[];
  format: (n: number) => string;
}) {
  const { bind, node } = useTip();
  const max = Math.max(1, ...days.map((d) => d.values.reduce((a, b) => a + b, 0)));
  if (!days.length) return <div className="muted small">Sin datos en el período.</div>;
  return (
    <div>
      {series.length > 1 && (
        <div className="legend">
          {series.map((s) => (
            <span key={s.name}>
              <span className="sw" style={{ background: s.color }} />
              {s.name}
            </span>
          ))}
        </div>
      )}
      <div className="vbars">
        {days.map((d, i) => (
          <div
            className="col"
            key={i}
            {...bind(
              <div>
                <div style={{ fontWeight: 600 }}>{d.label}</div>
                {series.map((s, j) => (
                  <div key={s.name}>
                    {s.name}: {format(d.values[j])}
                  </div>
                ))}
                {d.extra}
              </div>,
            )}
          >
            {d.values.map((v, j) =>
              v > 0 ? (
                <div
                  className="seg"
                  key={j}
                  style={{ height: `calc(${(v / max) * 100}% - 2px)`, background: series[j].color }}
                />
              ) : null,
            )}
          </div>
        ))}
      </div>
      <div className="vlabels">
        {days.map((d, i) => (
          <span key={i}>{days.length > 16 && i % 2 ? "" : d.label}</span>
        ))}
      </div>
      {node}
    </div>
  );
}
