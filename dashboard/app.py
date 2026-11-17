"""Dashboard inicial (Streamlit) sobre la API."""

from __future__ import annotations

import os

import altair as alt
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
    return r.json() if r.content else {}


st.title("Patagonia Land Intelligence")
defaults = api("GET", "/search/defaults") or {}
MAX_MIN = int(defaults.get("max_drive_minutes", 150))
st.caption(f"Terrenos, lotes, chacras y campos a ≤{MAX_MIN} min de BRC · CPC · EQS")
ZONES = api("GET", "/zones") or []
tab_props, tab_hl, tab_stats, tab_map, tab_sources, tab_monitor = st.tabs(
    ["Propiedades", "⭐ Destacados", "📊 Estadísticas", "Mapa", "Fuentes", "Monitoreo"])
HIGHLIGHTS = api("GET", "/highlights") or []
PTYPES = ["terreno", "lote", "chacra", "campo", "casa", "cabaña", "departamento", "local", "otro"]
WATER = ["waterfront_confirmed", "waterfront_claimed", "waterfront_possible", "water_nearby", "water_view_only",
         "unknown"]

# ------------------------------------------------------------------------- filtros
with st.sidebar:
    st.header("Filtros")
    ptypes = st.multiselect("Tipo", ["terreno", "lote", "chacra", "campo", "casa", "cabaña", "otro"],
                            default=defaults.get("property_types", ["terreno", "lote", "chacra", "campo"]))
    max_price = st.number_input("Precio máx. (USD)", value=int(defaults.get("max_price_usd", 500000)), step=25000)
    min_area = st.number_input("Superficie mín. (m²)", value=int(defaults.get("min_area_m2", 0)), step=1000)
    airports = st.multiselect(f"Aeropuertos (≤{MAX_MIN} min)", ["BRC", "CPC", "EQS"], default=["BRC", "CPC", "EQS"])
    zones = st.multiselect("Zona", [z["zone"] for z in ZONES],
                           help="Por localidad detectada en el aviso; los avisos sin localidad quedan afuera.")
    water = st.multiselect("Agua", ["waterfront_confirmed", "waterfront_claimed", "waterfront_possible",
                                    "water_nearby", "water_view_only", "unknown"])
    waterfront_only = st.checkbox("Solo costa (declarada o confirmada)", value=defaults.get("waterfront_only", False))
    include_unknown = st.checkbox("Incluir ubicación desconocida", value=defaults.get("include_unknown_location", True))
    include_no_price = st.checkbox("Incluir sin precio publicado", value=True)
    q = st.text_input("Texto")

params = {"property_types": ptypes, "max_price_usd": max_price or None, "min_area_m2": min_area or None,
          "airports": airports, "zones": zones, "water_classes": water, "waterfront_only": waterfront_only,
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
        st.caption("Tildá ⭐ en los avisos que quieras y agregalos a un destacado (uno tuyo o uno nuevo).")
        pdf = df[[c for c in cols if c in df.columns]].copy()
        pdf.insert(0, "elegir", False)
        bulk_box = st.container()  # controles arriba de la tabla; se completan después de leer la selección
        picked = st.data_editor(
            pdf, use_container_width=True, hide_index=True, key="props_table",
            disabled=[c for c in pdf.columns if c != "elegir"],
            column_config={"elegir": st.column_config.CheckboxColumn("⭐"),
                           "url": st.column_config.LinkColumn("URL"),
                           "confidence": st.column_config.ProgressColumn("Conf.", min_value=0, max_value=1)})
        chosen = picked.loc[picked["elegir"], "id"].tolist()
        NEW = "➕ Nuevo destacado…"
        a1, a2, a3 = bulk_box.columns([3, 3, 2], vertical_alignment="bottom")
        dest = a1.selectbox("Agregar a", [NEW] + [h["name"] for h in HIGHLIGHTS], key="bulk_dest",
                            index=1 if HIGHLIGHTS else 0)
        new_name = a2.text_input("Nombre del nuevo destacado", placeholder="Casa para envejecer",
                                 disabled=dest != NEW, key="bulk_new_name")
        if a3.button(f"⭐ Agregar {len(chosen)}", disabled=not chosen or (dest == NEW and not new_name.strip()),
                     type="primary"):
            if dest == NEW:
                # Destacado manual: sin filtros, solo muestra los avisos que se agregan a mano.
                target = api("POST", "/highlights", json={"name": new_name.strip()})
            else:
                target = next(h for h in HIGHLIGHTS if h["name"] == dest)
            if target:
                for lid in chosen:
                    api("PUT", f"/highlights/{target['id']}/listings/{int(lid)}", json={"mode": "pinned"})
                st.session_state.pop("props_table", None)  # destildar
                st.rerun()
        sel = st.selectbox("Ver detalle", df["id"].tolist(),
                           format_func=lambda i: f"#{i} {df.set_index('id').loc[i, 'title']}")
        if sel:
            d = api("GET", f"/listings/{sel}")
            if d:
                c1, c2 = st.columns([2, 1])
                with c1:
                    st.markdown(f"### [{d['title']}]({d['url']})")
                    in_hl = api("GET", f"/listings/{sel}/highlights") or []
                    if in_hl:
                        st.caption("⭐ En destacados: " + " · ".join(
                            f"{h['name']} ({h['origin']})" for h in in_hl))
                    if HIGHLIGHTS:
                        hc1, hc2 = st.columns([3, 1])
                        target = hc1.selectbox("Fijar en destacado", HIGHLIGHTS, format_func=lambda h: h["name"],
                                               key=f"pin_sel_{sel}", label_visibility="collapsed")
                        if hc2.button("⭐ Fijar", key=f"pin_{sel}"):
                            api("PUT", f"/highlights/{target['id']}/listings/{sel}", json={"mode": "pinned"})
                            st.rerun()
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

with tab_hl:
    with st.expander("➕ Nuevo destacado"):
        with st.form("new_hl", clear_on_submit=True):
            n_name = st.text_input("Nombre", placeholder="Casa para envejecer, Lago, Hectárea…")
            n_kw = st.text_input("Palabras clave (opcional, separadas por coma)", placeholder="lago, costa, playa",
                                 help="Vacío = destacado manual: solo muestra los avisos que agregues a mano "
                                      "(tildándolos en Propiedades).")
            if st.form_submit_button("Crear") and n_name:
                if api("POST", "/highlights", json={"name": n_name, "keywords": [
                        k.strip() for k in n_kw.split(",") if k.strip()]}):
                    st.rerun()
    if not HIGHLIGHTS:
        st.info("Todavía no hay destacados. Creá uno arriba.")
    else:
        h = st.radio("Destacado", HIGHLIGHTS, horizontal=True, label_visibility="collapsed",
                     format_func=lambda x: f"⭐ {x['name']} ({x['total']})")
        zone_names = [z["zone"] for z in ZONES]
        with st.expander("Filtros de este destacado", expanded=False):
            with st.form(f"edit_hl_{h['id']}"):
                c1, c2 = st.columns(2)
                e_name = c1.text_input("Nombre", h["name"])
                e_kw = c2.text_input("Palabras clave (coma)", ", ".join(h["keywords"]),
                                     help="Título o descripción, sin importar tildes ni plural. Vacío = sin filtro "
                                          "de texto.")
                e_mode = c1.radio("Palabras", ["any", "all"], index=0 if h["match_mode"] == "any" else 1,
                                  horizontal=True, format_func=lambda m: "alguna" if m == "any" else "todas")
                e_zones = c2.multiselect("Zonas", zone_names, [z for z in h["zones"] if z in zone_names])
                e_types = c1.multiselect("Tipo", PTYPES, [t for t in h["property_types"] if t in PTYPES])
                e_water = c2.multiselect("Agua", WATER, [w for w in h["water_classes"] if w in WATER])
                e_price = c1.number_input("Precio máx. USD (0 = sin límite)", value=int(h["max_price_usd"] or 0),
                                          step=10000)
                e_area = c2.number_input("Superficie mín. m² (0 = sin límite)", value=int(h["min_area_m2"] or 0),
                                         step=1000)
                e_rent = st.checkbox("Incluir alquileres", h["include_rentals"])
                b1, b2 = st.columns([1, 5])
                if b1.form_submit_button("Guardar", type="primary"):
                    api("PATCH", f"/highlights/{h['id']}", json={
                        "name": e_name, "keywords": [k.strip() for k in e_kw.split(",") if k.strip()],
                        "match_mode": e_mode, "zones": e_zones, "property_types": e_types, "water_classes": e_water,
                        "max_price_usd": e_price or None, "min_area_m2": e_area or None, "include_rentals": e_rent})
                    st.rerun()
                if b2.form_submit_button("Borrar destacado"):
                    api("DELETE", f"/highlights/{h['id']}")
                    st.rerun()
        res = api("GET", f"/highlights/{h['id']}/listings") or {}
        hdf = pd.DataFrame(res.get("items", []))
        st.subheader(f"{res.get('total', 0)} anuncios"
                     + (f" · {h['fijados']} fijados a mano" if h.get("fijados") else "")
                     + (f" · {h['excluidos']} sacados a mano" if h.get("excluidos") else ""))
        if hdf.empty:
            st.caption("Todavía vacío. Tildá ⭐ avisos en Propiedades y agregalos a este destacado.")
        else:
            hdf["ha"] = (hdf["area_m2"] / 10_000).round(2)
            hdf.insert(0, "quitar", False)
            cols = ["quitar", "origin", "id", "title", "property_type", "price", "currency", "ha", "price_per_ha_usd",
                    "locality", "water_class", "source_id", "url"]
            edited = st.data_editor(
                hdf[[c for c in cols if c in hdf.columns]], hide_index=True, use_container_width=True,
                disabled=[c for c in cols if c != "quitar"], key=f"hl_table_{h['id']}",
                column_config={"url": st.column_config.LinkColumn("URL"),
                               "origin": st.column_config.TextColumn("Origen"),
                               "quitar": st.column_config.CheckboxColumn("Quitar")})
            to_remove = edited[edited["quitar"]]
            if not to_remove.empty and st.button(f"Quitar {len(to_remove)} del destacado"):
                for _, r in to_remove.iterrows():  # fijado o por filtro: queda excluido a mano
                    api("PUT", f"/highlights/{h['id']}/listings/{r['id']}", json={"mode": "excluded"})
                st.rerun()
        if res.get("excluded"):
            with st.expander(f"Sacados a mano ({len(res['excluded'])})"):
                for x in res["excluded"]:
                    c1, c2 = st.columns([5, 1])
                    c1.markdown(f"[{x['title']}]({x['url']})")
                    if c2.button("Restaurar", key=f"rest_{h['id']}_{x['id']}"):
                        api("DELETE", f"/highlights/{h['id']}/listings/{x['id']}")
                        st.rerun()

# Paleta (tema oscuro de Streamlit): una serie = azul; estados = verde OK / rojo error, siempre con leyenda.
SERIES, GOOD, CRITICAL = "#3987e5", "#0ca30c", "#d03b3b"

CHANGE_LABELS = {"new_listing": "Nuevos", "price_decreased": "Bajó el precio", "price_increased": "Subió el precio",
                 "removed": "Dados de baja", "area_changed": "Cambió superficie", "status_changed": "Cambió estado",
                 "description_changed": "Cambió descripción", "relisted": "Republicado"}


def fmt_ar(n: float | None) -> str:
    """1234567 -> '1.234.567' (formato argentino)."""
    return "—" if n is None or pd.isna(n) else f"{n:,.0f}".replace(",", ".")


def hbar(data: pd.DataFrame, cat: str, val: str, cat_title: str, val_title: str) -> alt.Chart:
    """Barras horizontales de una serie: valor en el extremo (formato argentino), tooltip por barra."""
    data = data.assign(_lbl=data[val].map(fmt_ar))
    h = max(120, 28 * len(data))
    base = alt.Chart(data).encode(y=alt.Y(f"{cat}:N", sort="-x", title=None,
                                          axis=alt.Axis(labelLimit=220, labelOverlap=False)))
    bars = base.mark_bar(color=SERIES, cornerRadiusEnd=4, height=16).encode(
        x=alt.X(f"{val}:Q", title=val_title, axis=alt.Axis(grid=False, labels=False, ticks=False, domain=False)),
        tooltip=[alt.Tooltip(f"{cat}:N", title=cat_title), alt.Tooltip("_lbl:N", title=val_title)])
    labels = base.mark_text(align="left", dx=4, color="#c3c2b7").encode(x=f"{val}:Q", text="_lbl:N")
    return (bars + labels).properties(height=h)


with tab_stats:
    st_days = st.segmented_control("Período", [7, 14, 30], default=14, format_func=lambda d: f"{d} días",
                                   key="stats_days") or 14
    S = api("GET", "/stats", params={"days": st_days}) or {}
    k = S.get("kpis", {})
    if k:
        st.subheader("Operación")
        last = pd.to_datetime(k["last_run_at"]).tz_convert("America/Argentina/Buenos_Aires") \
            if k.get("last_run_at") else None
        geo_pct = k["props_with_drive_time"] / k["props_located"] if k["props_located"] else 0
        fmt = lambda n: f"{n:,}".replace(",", ".")
        tiles = [
            ("Avisos activos", fmt(k["listings_active"]), None, None),
            ("Tierra activa", fmt(k["land_active"]), None, "Terrenos, lotes, chacras y campos en venta."),
            ("Fuentes activas", f"{k['sources_enabled']}/{k['sources_total']}", None, None),
            ("Corridas 24 h", k["runs_24h"],
             f"{k['runs_failed_24h']} con error" if k["runs_failed_24h"] else None, None),
            ("Tiempo de manejo", f"{geo_pct:.0%}", None,
             "Propiedades con coordenadas que ya tienen tiempo de manejo (ORS) a los aeropuertos."),
            ("Última corrida", last.strftime("%d/%m %H:%M") if last is not None else "—", None, None),
            ("Nuevos 7 d", k["new_7d"], None, "Sin contar la carga inicial de cada fuente."),
            ("Bajas de precio 7 d", k["price_drops_7d"], None, None),
            ("Dados de baja 7 d", k["removed_7d"], None, None),
            ("Duplicados a revisar", fmt(k["dedup_pending"]), None,
             "Pares de avisos de distintas inmobiliarias que podrían ser la misma propiedad (tab Monitoreo)."),
        ]
        for i in range(0, len(tiles), 3):
            cols = st.columns(3)
            for col, (label, value, delta, hlp) in zip(cols, tiles[i:i + 3], strict=False):
                col.metric(label, value, delta=delta, delta_color="inverse" if delta else "off", help=hlp)
        if k["runs_broken_24h"]:
            st.warning(f"⚠️ {k['runs_broken_24h']} fuente(s) con posible rotura en las últimas 24 h "
                       "(ver tabla de fuentes).")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Corridas por día**")
            r = pd.DataFrame(S["runs_by_day"])
            if not r.empty:
                r = r.melt(id_vars=["day", "avg_minutes"], value_vars=["ok", "failed"], var_name="estado",
                           value_name="corridas")
                r["estado"] = r["estado"].map({"ok": "OK", "failed": "Con error"})
                r["dia"] = pd.to_datetime(r["day"]).dt.strftime("%d/%m")
                st.altair_chart(alt.Chart(r).mark_bar(cornerRadiusEnd=4, stroke="#1a1a19", strokeWidth=2).encode(
                    x=alt.X("dia:O", title=None, sort=None, axis=alt.Axis(labelAngle=0, grid=False)),
                    y=alt.Y("corridas:Q", title=None, stack=True),
                    color=alt.Color("estado:N", scale=alt.Scale(domain=["OK", "Con error"], range=[GOOD, CRITICAL]),
                                    legend=alt.Legend(orient="top", title=None)),
                    order=alt.Order("estado:N", sort="descending"),
                    tooltip=[alt.Tooltip("dia:O", title="Día"), "estado:N", "corridas:Q",
                             alt.Tooltip("avg_minutes:Q", title="Duración media (min)")]),
                    use_container_width=True)
        with col2:
            st.markdown("**Avisos nuevos por día** (sin la carga inicial)")
            ch = pd.DataFrame(S["changes_by_day"])
            nd = ch[ch["change_type"] == "new_listing"].copy() if not ch.empty else ch
            if not nd.empty:
                nd["dia"] = pd.to_datetime(nd["day"]).dt.strftime("%d/%m")
            if nd.empty:
                st.caption("Sin avisos nuevos en el período.")
            else:
                st.altair_chart(alt.Chart(nd).mark_bar(color=SERIES, cornerRadiusEnd=4).encode(
                    x=alt.X("dia:O", title=None, sort=None, axis=alt.Axis(labelAngle=0, grid=False)),
                    y=alt.Y("n:Q", title=None),
                    tooltip=[alt.Tooltip("dia:O", title="Día"), alt.Tooltip("n:Q", title="Nuevos")]), use_container_width=True)

        st.subheader("Mercado de tierra por zona")
        z = pd.DataFrame(S["zones"])
        if not z.empty:
            col1, col2 = st.columns([1, 1])
            with col1:
                st.markdown("**Avisos activos por zona**")
                st.altair_chart(hbar(z, "zone", "listings", "Zona", "Avisos"), use_container_width=True)
            with col2:
                st.markdown("**Precio mediano por zona (USD)**")
                zp = z[z["with_price"] >= 3].dropna(subset=["median_price_usd"])
                st.altair_chart(hbar(zp, "zone", "median_price_usd", "Zona", "Mediana USD"),
                                use_container_width=True)
            st.caption("El gráfico de precio solo muestra zonas con 3 o más avisos con precio; la tabla, todas.")
            st.dataframe(z, hide_index=True, use_container_width=True, column_config={
                "zone": "Zona", "listings": "Avisos", "with_price": "Con precio",
                "median_price_usd": st.column_config.NumberColumn("Mediana USD", format="localized"),
                "median_usd_per_ha": st.column_config.NumberColumn("Mediana USD/ha", format="localized",
                                                                   help="Solo avisos con precio y ≥ 500 m²")})

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Cambios detectados (7 días)**")
            c7 = pd.DataFrame(S["changes_7d"])
            if not c7.empty:
                c7["tipo"] = c7["change_type"].map(lambda t: CHANGE_LABELS.get(t, t))
                st.altair_chart(hbar(c7, "tipo", "n", "Cambio", "Cantidad"), use_container_width=True)
        with col2:
            st.markdown("**Avisos activos por tipo** (sin alquileres)")
            ty = pd.DataFrame(S["types"])
            if not ty.empty:
                st.altair_chart(hbar(ty, "property_type", "n", "Tipo", "Avisos"), use_container_width=True)

        st.markdown("**Movimientos de precio**")
        pm = pd.DataFrame(S["price_moves"])
        if pm.empty:
            st.caption("Sin cambios de precio en el período.")
        else:
            pm["cambio"] = pm["change_type"].map(lambda t: "▼ Bajó" if t == "price_decreased" else "▲ Subió")
            pm["detected_at"] = pd.to_datetime(pm["detected_at"]).dt.tz_convert(
                "America/Argentina/Buenos_Aires").dt.strftime("%d/%m %H:%M")
            st.dataframe(pm[["detected_at", "cambio", "pct_change", "title", "price", "currency", "locality",
                             "source_id", "url"]], hide_index=True, use_container_width=True, column_config={
                "detected_at": "Detectado", "cambio": "Cambio",
                "pct_change": st.column_config.NumberColumn("%", format="%.1f%%"), "title": "Aviso",
                "price": st.column_config.NumberColumn("Precio actual", format="localized"), "currency": "Moneda",
                "locality": "Localidad", "source_id": "Fuente", "url": st.column_config.LinkColumn("URL")})

        st.subheader("Fuentes")
        src = pd.DataFrame(S["sources"])
        if not src.empty:
            only_on = st.toggle("Solo fuentes activas", value=True, key="stats_only_enabled")
            if only_on:
                src = src[src["enabled"]]
            src["estado"] = src.apply(
                lambda r: "⚠️ posible rotura" if r["possibly_broken"] else
                ("✅ OK" if r["last_status"] == "success" else
                 "🟡 parcial" if r["last_status"] == "partial" else
                 "❌ error" if r["last_status"] else "— sin corridas"), axis=1)
            src["last_run_at"] = pd.to_datetime(src["last_run_at"], utc=True).dt.tz_convert(
                "America/Argentina/Buenos_Aires").dt.strftime("%d/%m %H:%M")
            pct = {"min_value": 0, "max_value": 1, "format": "percent"}
            st.dataframe(
                src[["name", "estado", "region", "active", "land", "pct_price", "pct_area", "pct_locality",
                     "pct_coords", "new_7d", "price_changes_7d", "removed_7d", "last_run_at", "last_minutes",
                     "last_errors", "base_url"]],
                hide_index=True, use_container_width=True, height=min(900, 38 + 35 * len(src)),
                column_config={
                    "name": "Fuente", "estado": "Último crawl", "region": "Región", "active": "Activos",
                    "land": "Tierra", "pct_price": st.column_config.ProgressColumn("Precio", **pct),
                    "pct_area": st.column_config.ProgressColumn("Superficie", **pct),
                    "pct_locality": st.column_config.ProgressColumn("Localidad", **pct),
                    "pct_coords": st.column_config.ProgressColumn("Coordenadas", **pct),
                    "new_7d": "Nuevos 7d", "price_changes_7d": "Cambios precio 7d", "removed_7d": "Bajas 7d",
                    "last_run_at": "Última corrida", "last_minutes": st.column_config.NumberColumn("Min", format="%.1f"),
                    "last_errors": "Errores", "base_url": st.column_config.LinkColumn("Sitio")})
            st.caption("Cobertura = % de avisos activos de la fuente que tienen ese dato. Coordenadas = punto "
                       "publicado (exacto o zona aproximada), no solo la localidad.")

        st.markdown("**Propiedades dentro de 150 min por aeropuerto**")
        dr = pd.DataFrame(S["drive"])
        if not dr.empty:
            st.dataframe(dr, hide_index=True, column_config={
                "airport_code": "Aeropuerto", "within": "Dentro", "outside": "Fuera", "unknown": "Sin ruta"})

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
