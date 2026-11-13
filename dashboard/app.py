"""Dashboard inicial (Streamlit) sobre la API."""

from __future__ import annotations

import os

import httpx
import pandas as pd
import pydeck as pdk
import streamlit as st

API = os.environ.get("API_URL", "http://localhost:8000")
TOKEN = os.environ.get("API_TOKEN", "")
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN and TOKEN != "change-me" else {}

st.set_page_config(page_title="Patagonia Land Intelligence", layout="wide")


def api(method: str, path: str, **kw):
    r = httpx.request(method, f"{API}{path}", headers=HEADERS, timeout=30, **kw)
    if r.status_code >= 400:
        st.error(f"{method} {path} → {r.status_code}: {r.text[:300]}")
        return None
    return r.json()


st.title("Patagonia Land Intelligence")
st.caption("Terrenos, lotes, chacras y campos a ≤60 min de BRC · CPC · EQS")
tab_props, tab_map, tab_sources, tab_monitor = st.tabs(["Propiedades", "Mapa", "Fuentes", "Monitoreo"])

defaults = api("GET", "/search/defaults") or {}

# ------------------------------------------------------------------------- filtros
with st.sidebar:
    st.header("Filtros")
    ptypes = st.multiselect("Tipo", ["terreno", "lote", "chacra", "campo", "casa", "cabaña", "otro"],
                            default=defaults.get("property_types", ["terreno", "lote", "chacra", "campo"]))
    max_price = st.number_input("Precio máx. (USD)", value=int(defaults.get("max_price_usd", 500000)), step=25000)
    min_area = st.number_input("Superficie mín. (m²)", value=int(defaults.get("min_area_m2", 0)), step=1000)
    airports = st.multiselect("Aeropuertos (≤60 min)", ["BRC", "CPC", "EQS"], default=["BRC", "CPC", "EQS"])
    water = st.multiselect("Agua", ["waterfront_confirmed", "waterfront_claimed", "waterfront_possible",
                                    "water_nearby", "water_view_only", "unknown"])
    waterfront_only = st.checkbox("Solo costa (declarada o confirmada)", value=defaults.get("waterfront_only", False))
    include_unknown = st.checkbox("Incluir ubicación desconocida", value=defaults.get("include_unknown_location", True))
    include_no_price = st.checkbox("Incluir sin precio publicado", value=True)
    q = st.text_input("Texto")

params = {"property_types": ptypes, "max_price_usd": max_price or None, "min_area_m2": min_area or None,
          "airports": airports, "water_classes": water, "waterfront_only": waterfront_only,
          "include_unknown_location": include_unknown, "include_no_price": include_no_price, "q": q or None,
          "limit": 1000}
data = api("GET", "/properties", params={k: v for k, v in params.items() if v not in (None, [], "")}) or {}
items = data.get("items", [])
df = pd.DataFrame(items)

with tab_props:
    st.subheader(f"{data.get('total', 0)} anuncios")
    if data.get("airport_filter_mode") == "region":
        st.info("Isócronas aún no calculadas: el filtro por aeropuerto usa la región de la inmobiliaria.")
    if not df.empty:
        df["ha"] = (df["area_m2"] / 10_000).round(2)
        cols = ["id", "title", "property_type", "price", "currency", "ha", "price_per_ha_usd", "locality",
                "geo_precision", "water_class", "confidence", "status", "source_id", "url"]
        st.dataframe(df[[c for c in cols if c in df.columns]], use_container_width=True, hide_index=True,
                     column_config={"url": st.column_config.LinkColumn("URL"),
                                    "confidence": st.column_config.ProgressColumn("Conf.", min_value=0, max_value=1)})
        sel = st.selectbox("Ver detalle", df["id"].tolist(),
                           format_func=lambda i: f"#{i} {df.set_index('id').loc[i, 'title']}")
        if sel:
            d = api("GET", f"/listings/{sel}")
            if d:
                c1, c2 = st.columns([2, 1])
                with c1:
                    st.markdown(f"### [{d['title']}]({d['url']})")
                    st.write(d.get("description") or "_sin descripción_")
                    photos = d.get("photos") or []
                    if photos:
                        st.image(photos[:6], width=220)
                with c2:
                    st.markdown("**Evidencia y confianza por campo**")
                    st.json(d.get("provenance") or {}, expanded=False)
                    w = (d.get("data") or {}).get("water", {})
                    st.markdown(f"**Agua:** `{w.get('water_class')}` — {w.get('evidence') or ''}")
                    if (d.get("data") or {}).get("warnings"):
                        st.warning("\n".join(d["data"]["warnings"]))
                    hist = pd.DataFrame([{"fecha": s["captured_at"], "precio": s["data"].get("price")}
                                         for s in d.get("snapshots", [])])
                    if len(hist) > 1:
                        st.line_chart(hist.set_index("fecha"))
                    st.markdown("**Cambios**")
                    for ch in d.get("changes", []):
                        st.write(f"{ch['detected_at'][:16]} · {ch['change_type']} {ch.get('pct_change') or ''}")

with tab_map:
    apts = api("GET", "/airports") or []
    layers = []
    for iso in api("GET", "/airports/isochrones", params={"minutes": 60}) or []:
        layers.append(pdk.Layer("GeoJsonLayer", {"type": "Feature", "geometry": iso["geometry"]},
                                opacity=0.12, get_fill_color=[30, 120, 200], get_line_color=[30, 120, 200]))
    if not df.empty and "latitude" in df:
        m = df.dropna(subset=["latitude", "longitude"]).copy()
        m["color"] = m["geo_precision"].map(lambda p: [20, 160, 60, 220] if p == "exact" else [240, 160, 20, 140])
        m["radius"] = m["geo_precision"].map(lambda p: 120 if p == "exact" else 1500)
        layers.append(pdk.Layer("ScatterplotLayer", m, get_position="[longitude, latitude]", get_fill_color="color",
                                get_radius="radius", pickable=True))
    if apts:
        layers.append(pdk.Layer("TextLayer", pd.DataFrame(apts), get_position="[longitude, latitude]",
                                get_text="code", get_size=18, get_color=[200, 30, 30]))
    st.caption("Verde: coordenadas publicadas · Naranja (círculo grande): solo localidad, ubicación aproximada")
    st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=pdk.ViewState(latitude=-41.5, longitude=-71.3, zoom=6.3),
                             tooltip={"text": "{title}\n{locality} · {geo_precision}"}))

with tab_sources:
    with st.form("add_source"):
        st.subheader("Agregar inmobiliaria por URL")
        url = st.text_input("URL del sitio", placeholder="https://www.inmobiliaria.com.ar")
        start = st.text_input("URL de listado (opcional)", placeholder="https://.../propiedades?tipo=terreno")
        region = st.selectbox("Región", ["bariloche", "chapelco", "esquel"])
        if st.form_submit_button("Registrar e inspeccionar") and url:
            res = api("POST", "/sources", json={"base_url": url, "region": region,
                                                "start_urls": [start] if start else []})
            if res:
                st.success(f"Fuente {res['id']} registrada; job de inspección #{res.get('job', {}).get('id')}")
    for src in api("GET", "/sources") or []:
        run = src.get("last_run") or {}
        with st.expander(f"{'🟢' if src['enabled'] else '⚪'} {src['name']} — {src['active_listings']} activos · "
                         f"último: {run.get('status', '—')}{' ⚠️ posible rotura' if run.get('possibly_broken') else ''}"):
            c1, c2, c3 = st.columns(3)
            if c1.button("Inspeccionar", key=f"i{src['id']}"):
                st.write(api("POST", f"/sources/{src['id']}/inspect"))
            if c2.button("Crawlear ahora", key=f"c{src['id']}"):
                st.write(api("POST", f"/sources/{src['id']}/crawl"))
            c3.write(f"Perfil: {src.get('profile')}")
            runs = api("GET", f"/sources/{src['id']}/runs") or []
            if runs:
                st.dataframe(pd.DataFrame(runs)[["id", "started_at", "status", "pages_visited", "details_discovered",
                                                 "details_processed", "valid_properties", "pct_with_price",
                                                 "pct_with_area", "errors_count", "possibly_broken",
                                                 "duration_seconds"]], hide_index=True)
                if runs[0].get("errors"):
                    st.json(runs[0]["errors"][:20], expanded=False)

with tab_monitor:
    jobs = api("GET", "/jobs") or []
    if jobs:
        st.subheader("Jobs")
        st.dataframe(pd.DataFrame(jobs)[["id", "kind", "source_id", "status", "progress", "error", "created_at"]],
                     hide_index=True)
    st.subheader("Cambios recientes")
    ch = api("GET", "/changes") or []
    if ch:
        st.dataframe(pd.DataFrame(ch)[["detected_at", "change_type", "pct_change", "title", "locality", "source_id",
                                       "url"]], hide_index=True,
                     column_config={"url": st.column_config.LinkColumn("URL")})
    st.subheader("Posibles duplicados a revisar")
    for c in api("GET", "/dedup/pending") or []:
        a, b = c["a"], c["b"]
        col1, col2, col3 = st.columns([3, 3, 2])
        col1.markdown(f"[{a['title']}]({a['url']}) · {a['source_id']}")
        col2.markdown(f"[{b['title']}]({b['url']}) · {b['source_id']}")
        with col3:
            st.caption(f"score {c['score']:.2f}")
            if st.button("Unir", key=f"m{c['id']}"):
                api("POST", f"/dedup/{c['id']}", json={"decision": "merge"})
            if st.button("Distintos", key=f"r{c['id']}"):
                api("POST", f"/dedup/{c['id']}", json={"decision": "reject"})
