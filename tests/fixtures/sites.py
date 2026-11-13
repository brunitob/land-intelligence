"""Tres sitios sintéticos con estructuras distintas, servidos con httpx.MockTransport.

- site_a (inmoa.test): WordPress-like, JSON-LD, paginación ?page=N, sitemap.xml.
- site_b (inmob.test): HTML plano, tablas etiqueta/valor, paginación /terrenos/page/N, iframe de Google Maps.
- site_c (inmoc.test): listas <li>, <dl>, paginación rel=next, precios "Consultar" y ARS, robots con Disallow.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

PAGE = """<!doctype html><html><head><title>{title}</title>{head}</head>
<body><header><nav><a href="/">Inicio</a> <a href="{list_url}">Propiedades</a> <a href="/contacto">Contacto</a>
<a href="/nosotros">Nosotros</a></nav></header><main>{body}</main>
<footer><a href="/politica-de-privacidad">Privacidad</a> <a href="https://wa.me/549">WhatsApp</a></footer></body></html>"""


@dataclass
class Item:
    id: int
    title: str
    price: str
    area: str
    locality: str
    description: str
    lat: float | None = None
    lon: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------------------- site A
A_ITEMS = [
    Item(101, "Lote en Dina Huapi con vista al lago", "USD 85.000", "1.200 m²", "Dina Huapi",
         "Excelente lote con vista al lago Nahuel Huapi, servicios de luz y gas natural en la puerta.",
         -41.0702, -71.1561),
    Item(102, "Chacra en Colonia Suiza", "U$S 420.000", "4,5 ha", "Colonia Suiza",
         "Chacra con costa de arroyo propia, vertiente y bosque nativo. Acceso por ruta asfaltada.", -41.09, -71.50),
    Item(103, "Terreno en Villa Los Coihues", "USD 120.000", "2.500 m2", "Villa Los Coihues",
         "Terreno a 300 metros del lago Gutiérrez, en barrio tranquilo, con agua de red.", None, None),
    Item(104, "Campo de 120 hectáreas en Pilcaniyeu", "USD 380.000", "120 ha", "Pilcaniyeu",
         "Campo atravesado por un arroyo, apto ganadería. Mallín y aguadas.", None, None),
    Item(105, "Lote en Llao Llao frente al lago", "USD 650.000", "3.000 m²", "Llao Llao",
         "Lote con costa propia sobre el lago Moreno, 40 metros de costa. Vistas panorámicas.", -41.06, -71.52),
]


def a_detail(it: Item) -> str:
    ld = {"@context": "https://schema.org", "@type": "RealEstateListing", "name": it.title,
          "description": it.description, "sku": f"A-{it.id}",
          "offers": {"@type": "Offer", "price": it.price.split()[-1].replace(".", ""), "priceCurrency": "USD"},
          "address": {"@type": "PostalAddress", "addressLocality": it.locality, "addressRegion": "Río Negro"},
          "image": [f"https://inmoa.test/wp-content/uploads/prop-{it.id}-{i}.jpg" for i in range(3)]}
    if it.lat:
        ld["geo"] = {"@type": "GeoCoordinates", "latitude": it.lat, "longitude": it.lon}
    head = f'<script type="application/ld+json">{json.dumps(ld)}</script>' \
           f'<link rel="canonical" href="https://inmoa.test/propiedad/{it.id}-{it.locality.lower().replace(" ", "-")}/">'
    body = f"""<article><h1>{it.title}</h1><div class="price">{it.price}</div>
<ul class="specs"><li>Superficie: {it.area}</li><li>Ubicación: {it.locality}</li></ul>
<div class="property-description"><p>{it.description}</p></div>
<div class="gallery">{''.join(f'<img src="/wp-content/uploads/prop-{it.id}-{i}.jpg" width="800">' for i in range(3))}</div>
</article>"""
    return PAGE.format(title=it.title, head=head, body=body, list_url="/propiedades")


def a_list(page: int) -> str:
    per = 2
    chunk = A_ITEMS[(page - 1) * per: page * per]
    cards = "".join(
        f'<div class="property-card"><a class="property-link" href="/propiedad/{i.id}-{i.locality.lower().replace(" ", "-")}/">'
        f'<h3>{i.title}</h3></a><span class="price">{i.price}</span><span>{i.area}</span></div>' for i in chunk)
    pages = (len(A_ITEMS) + per - 1) // per
    pag = "".join(f'<a href="/propiedades?page={n}">{n}</a> ' for n in range(1, pages + 1))
    return PAGE.format(title="Propiedades", head="", body=f'<section class="grid">{cards}</section>'
                       f'<nav class="pagination">{pag}</nav>', list_url="/propiedades")


def site_a(request: httpx.Request, state: dict[str, Any]) -> httpx.Response:
    p = request.url.path.rstrip("/") or "/"
    if p == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nDisallow: /wp-admin\nSitemap: https://inmoa.test/sitemap.xml")
    if p == "/sitemap.xml":
        urls = "".join(f"<url><loc>https://inmoa.test/propiedad/{i.id}-{i.locality.lower().replace(' ', '-')}/</loc></url>"
                       for i in A_ITEMS if i.id not in state.get("hidden", set()))
        return httpx.Response(200, text=f'<?xml version="1.0"?><urlset>{urls}<url><loc>https://inmoa.test/contacto</loc></url></urlset>',
                              headers={"content-type": "application/xml"})
    if p == "/":
        return _html(PAGE.format(title="Inmo A", head="", body="<h1>Inmobiliaria A</h1><p>Bienvenidos</p>",
                                 list_url="/propiedades"))
    if p == "/propiedades":
        return _html(a_list(int(request.url.params.get("page", "1"))))
    if p.startswith("/propiedad/"):
        pid = int(p.split("/")[2].split("-")[0])
        if pid in state.get("hidden", set()):
            return httpx.Response(404, text="no encontrado")
        it = next((i for i in A_ITEMS if i.id == pid), None)
        if it:
            it2 = Item(**{**it.__dict__, "price": state.get("prices", {}).get(pid, it.price)})
            return _html(a_detail(it2))
    if p in ("/contacto", "/nosotros", "/politica-de-privacidad"):
        return _html(PAGE.format(title="Contacto", head="", body="<h1>Contacto</h1><p>Escribinos</p>",
                                 list_url="/propiedades"))
    return httpx.Response(404, text="404")


# ------------------------------------------------------------------------------- site B
B_ITEMS = [
    Item(1, "Terreno en Trevelin - 2 hectáreas", "U$S 95.000", "2 has", "Trevelin",
         "Terreno de 2 hectáreas sobre camino vecinal, con vista al cordón montañoso. A 500 metros del río Percy.",
         -43.0901, -71.4702),
    Item(2, "Campo con costa de río en Esquel", "USD 1.200.000", "850 hectáreas", "Esquel",
         "Campo con costa de río y vertientes, casa principal y galpón.", None, None),
    Item(3, "Lote urbano Esquel", "U$S 38.000", "450 m2", "Esquel",
         "Lote urbano en barrio residencial, todos los servicios.", None, None),
    Item(4, "Chacra en Aldea Escolar", "USD 210.000", "5 ha", "Aldea Escolar",
         "Chacra con arroyo que atraviesa el terreno, frutales y casa de madera.", -43.12, -71.55),
]


def b_detail(it: Item) -> str:
    rows = f"<tr><th>Precio</th><td>{it.price}</td></tr><tr><th>Superficie total</th><td>{it.area}</td></tr>" \
           f"<tr><th>Localidad</th><td>{it.locality}, Chubut</td></tr><tr><th>Código</th><td>B{it.id:04d}</td></tr>"
    mapa = (f'<iframe src="https://maps.google.com/maps?q={it.lat},{it.lon}&z=15&output=embed"></iframe>'
            if it.lat else "")
    body = f"""<div class="ficha"><h1>{it.title}</h1><table class="datos">{rows}</table>
<div class="descripcion"><p>{it.description}</p><p>Consulte por financiación. Escritura al día.</p></div>
{mapa}<div class="fotos"><a href="/fotos/b{it.id}_1.jpg"><img src="/fotos/b{it.id}_1_th.jpg"></a>
<a href="/fotos/b{it.id}_2.jpg"><img src="/fotos/b{it.id}_2_th.jpg"></a></div></div>"""
    return PAGE.format(title=f"{it.title} | Inmo B", head="", body=body, list_url="/terrenos")


def b_list(page: int) -> str:
    per = 3
    chunk = B_ITEMS[(page - 1) * per: page * per]
    cards = "".join(f'<article class="item-propiedad"><a href="/ficha.php?id={i.id}"><img src="/fotos/b{i.id}_1_th.jpg">'
                    f'<h2>{i.title}</h2></a><p class="valor">{i.price}</p><p>{i.area}</p></article>' for i in chunk)
    nxt = f'<a class="next" href="/terrenos/page/{page + 1}">Siguiente</a>' if page * per < len(B_ITEMS) else ""
    return PAGE.format(title="Terrenos", head="", body=f"<h1>Terrenos en venta</h1>{cards}<div class='pag'>{nxt}</div>",
                       list_url="/terrenos")


def site_b(request: httpx.Request, state: dict[str, Any]) -> httpx.Response:
    p = request.url.path.rstrip("/") or "/"
    if p == "/robots.txt":
        return httpx.Response(404)
    if p == "/":
        return _html(PAGE.format(title="Inmo B", head="", body="<h1>Inmo B Esquel</h1><a href='/terrenos'>Ver terrenos</a>",
                                 list_url="/terrenos"))
    if p == "/terrenos":
        return _html(b_list(1))
    if p.startswith("/terrenos/page/"):
        return _html(b_list(int(p.rsplit("/", 1)[1])))
    if p == "/ficha.php":
        it = next((i for i in B_ITEMS if str(i.id) == request.url.params.get("id")), None)
        if it:
            return _html(b_detail(it))
    if p in ("/contacto", "/nosotros", "/politica-de-privacidad"):
        return _html(PAGE.format(title="Contacto", head="", body="<p>Tel</p>", list_url="/terrenos"))
    return httpx.Response(404)


# ------------------------------------------------------------------------------- site C
C_ITEMS = [
    Item(11, "Lote en San Martín de los Andes, barrio Chapelco Golf", "Consultar", "1.850 m2",
         "San Martín de los Andes", "Lote en barrio privado con acceso al lago Lácar por bajada común. Luz y gas."),
    Item(12, "Terreno en Junín de los Andes", "$ 45.000.000", "800 m2", "Junín de los Andes",
         "Terreno plano a 2 cuadras del río Chimehuín."),
    Item(13, "Fracción de 12 ha en Lago Lolog", "USD 540.000", "12 hectáreas", "Lago Lolog",
         "Fracción con 120 metros de costa sobre el lago Lolog. Bosque de coihues."),
    Item(14, "Casa en San Martín de los Andes", "USD 290.000", "600 m2", "San Martín de los Andes",
         "Casa de 3 dormitorios, sin costa, a 10 cuadras del lago."),
]


def c_detail(it: Item) -> str:
    body = f"""<h1>{it.title}</h1><dl class="caracteristicas"><dt>Valor</dt><dd>{it.price}</dd>
<dt>Superficie</dt><dd>{it.area}</dd><dt>Zona</dt><dd>{it.locality}</dd><dt>Ref</dt><dd>SMA-{it.id}</dd></dl>
<section id="descripcion"><p>{it.description} Excelente oportunidad en la zona, consulte sin compromiso por más información.</p></section>
<img src="/img/c{it.id}a.webp" width="900"><img src="/img/c{it.id}b.webp" width="900"><img src="/img/logo.png">"""
    return PAGE.format(title=it.title, head="", body=body, list_url="/venta")


def c_list(page: int) -> str:
    per = 2
    chunk = C_ITEMS[(page - 1) * per: page * per]
    lis = "".join(f'<li class="resultado"><a href="/inmueble/{i.id}/{i.title.lower().replace(" ", "-")[:30]}">'
                  f'{i.title}</a> <b>{i.price}</b> · {i.area}</li>' for i in chunk)
    head = f'<link rel="next" href="/venta?pagina={page + 1}">' if page * per < len(C_ITEMS) else ""
    nxt = f'<a rel="next" href="/venta?pagina={page + 1}">»</a>' if head else ""
    return PAGE.format(title="Venta", head=head, body=f"<ul class='resultados'>{lis}</ul>{nxt}", list_url="/venta")


def site_c(request: httpx.Request, state: dict[str, Any]) -> httpx.Response:
    p = request.url.path.rstrip("/") or "/"
    if p == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nDisallow: /admin\n")
    if p == "/":
        return _html(PAGE.format(title="Inmo C", head="", body="<h1>Inmo C</h1>", list_url="/venta"))
    if p == "/venta":
        return _html(c_list(int(request.url.params.get("pagina", "1"))))
    if p.startswith("/inmueble/"):
        it = next((i for i in C_ITEMS if str(i.id) == p.split("/")[2]), None)
        if it:
            return _html(c_detail(it))
    if p.startswith("/admin"):
        raise AssertionError("robots.txt prohíbe /admin y el crawler lo pidió igual")
    return httpx.Response(404)


def _html(text: str) -> httpx.Response:
    return httpx.Response(200, text=text, headers={"content-type": "text/html; charset=utf-8"})


SITES = {"inmoa.test": site_a, "inmob.test": site_b, "inmoc.test": site_c}


def make_transport(state: dict[str, Any] | None = None) -> httpx.MockTransport:
    state = state if state is not None else {}

    def handler(request: httpx.Request) -> httpx.Response:
        fn = SITES.get(request.url.host)
        if not fn:
            return httpx.Response(404)
        state.setdefault("requests", []).append(str(request.url))
        return fn(request, state)

    return httpx.MockTransport(handler)
