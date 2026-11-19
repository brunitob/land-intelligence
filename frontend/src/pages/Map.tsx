import { useQuery } from "@tanstack/react-query";
import "leaflet/dist/leaflet.css";
import { useState } from "react";
import { Circle, CircleMarker, MapContainer, Popup, TileLayer, Tooltip } from "react-leaflet";
import { Airport, api } from "../api";
import { AddToHighlight } from "../components/AddToHighlight";
import { ListingDrawer } from "../components/ListingDrawer";
import { Spinner } from "../components/ui";
import { useFilters, useProperties } from "../filters";
import { area, money, num } from "../format";

const EXACT = "#0ca30c";
const APPROX = "#eb6834";

export function MapPage() {
  const { filters } = useFilters();
  const props = useProperties(filters);
  const airports = useQuery({ queryKey: ["airports"], queryFn: () => api.get<Airport[]>("/airports"), staleTime: Infinity });
  const [open, setOpen] = useState<number | null>(null);
  const located = (props.data?.items ?? []).filter((l) => l.latitude != null && l.longitude != null);

  return (
    <div className="stack">
      <div className="spread">
        <h2 className="row">
          {num(located.length)} avisos con ubicación {props.isFetching && <Spinner />}
        </h2>
        <div className="legend" style={{ margin: 0 }}>
          <span>
            <span className="sw" style={{ background: EXACT, borderRadius: "50%" }} />
            Coordenadas publicadas
          </span>
          <span>
            <span className="sw" style={{ background: APPROX, borderRadius: "50%", opacity: 0.6 }} />
            Ubicación aproximada (zona)
          </span>
        </div>
      </div>
      <div className="muted small">Usa los mismos filtros que Propiedades.</div>
      <div className="map-wrap">
        <MapContainer center={[-41.6, -71.3]} zoom={7} preferCanvas style={{ height: "100%", width: "100%" }}>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {located.map((l) =>
            l.geo_precision === "exact" ? (
              <CircleMarker
                key={l.id}
                center={[l.latitude!, l.longitude!]}
                radius={6}
                pathOptions={{ color: "#ffffff", weight: 1.5, fillColor: EXACT, fillOpacity: 0.9 }}
              >
                <ListingPopup l={l} onOpen={setOpen} />
              </CircleMarker>
            ) : (
              <Circle
                key={l.id}
                center={[l.latitude!, l.longitude!]}
                radius={1500}
                pathOptions={{ color: APPROX, weight: 1, fillColor: APPROX, fillOpacity: 0.15 }}
              >
                <ListingPopup l={l} onOpen={setOpen} />
              </Circle>
            ),
          )}
          {(airports.data ?? []).map((a) => (
            <CircleMarker key={a.code} center={[a.latitude, a.longitude]} radius={8} pathOptions={{ color: "#ffffff", weight: 2, fillColor: "#d03b3b", fillOpacity: 1 }}>
              <Tooltip permanent direction="right" offset={[8, 0]}>
                ✈ {a.code}
              </Tooltip>
            </CircleMarker>
          ))}
        </MapContainer>
      </div>
      {open !== null && <ListingDrawer id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function ListingPopup({ l, onOpen }: { l: import("../api").Listing; onOpen: (id: number) => void }) {
  return (
    <Popup>
      <div className="map-popup" style={{ minWidth: 240 }}>
        <strong>{l.title}</strong>
        <div>
          {money(l.price, l.currency)} · {area(l.area_m2)}
        </div>
        <div style={{ color: "#52514e" }}>
          {l.locality ?? "—"} · {l.source_id}
        </div>
        <div style={{ marginTop: 8 }}>
          <AddToHighlight listingId={l.id} compact />
        </div>
        <div style={{ marginTop: 8, display: "flex", gap: 10 }}>
          <a href="#" onClick={(e) => (e.preventDefault(), onOpen(l.id))}>
            Ver detalle
          </a>
          <a href={l.url} target="_blank" rel="noreferrer">
            Aviso original ↗
          </a>
        </div>
      </div>
    </Popup>
  );
}
