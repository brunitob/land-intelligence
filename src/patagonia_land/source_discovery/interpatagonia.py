"""Directorio de inmobiliarias de InterPatagonia (/{ciudad}/inmobiliario.html).

El directorio NO publica sitios web (los links salientes pasan por /r?, prohibido por su robots.txt):
solo nombre, dirección y teléfonos. Sirve como lista de agencias a las que buscarles el sitio.

Uso: python -m patagonia_land.source_discovery.interpatagonia > agencias.csv
"""

from __future__ import annotations

import asyncio
import csv
import re
import sys
from dataclasses import asdict, dataclass

from bs4 import BeautifulSoup

from patagonia_land.crawling.fetcher import Fetcher

BASE = "https://www.interpatagonia.com"
# ciudad en InterPatagonia → región/aeropuerto del proyecto
CITIES = {
    "bariloche": "bariloche",
    "villalaangostura": "bariloche",
    "elbolson": "bariloche",
    "villatraful": "bariloche",
    "meliquina": "chapelco",
    "alumine": "chapelco",
    "lagopuelo": "esquel",
    "el-hoyo": "esquel",
    "epuyen": "esquel",
    "cholila": "esquel",
    "sanmartindelosandes": "chapelco",
    "junindelosandes": "chapelco",
    "esquel": "esquel",
    "trevelin": "esquel",
}
REAL_ESTATE_RUBRO = re.compile(r"inmobiliari|bienes ra[ií]ces|propiedades|loteos|desarroll", re.IGNORECASE)


@dataclass
class Agency:
    name: str
    city: str
    region: str
    rubro: str | None
    address: str | None
    phones: str | None
    whatsapp: str | None


def parse_directory(html: str, city: str) -> list[Agency]:
    soup = BeautifulSoup(html, "lxml")
    out: list[Agency] = []
    for art in soup.select("article.tarj"):
        h3 = art.find("h3")
        if not h3:
            continue
        rubro_el = art.select_one(".tarj-rubro-txt")
        rubro = rubro_el.get_text(strip=True) if rubro_el else None
        if rubro and not REAL_ESTATE_RUBRO.search(rubro):
            continue  # p.ej. "Alquileres temporarios", "Escribanías"
        dir_el, tel_el = art.select_one("p.dir"), art.select_one("p.tels")
        wa = art.select_one('a[href^="https://wa.me/"]')
        wa_num = re.search(r"wa\.me/(\d+)", wa["href"]).group(1) if wa else None
        out.append(Agency(
            name=h3.get_text(" ", strip=True), city=city, region=CITIES[city], rubro=rubro,
            address=dir_el.get_text(" ", strip=True) if dir_el else None,
            phones=tel_el.get_text(" ", strip=True) if tel_el else None, whatsapp=wa_num,
        ))
    return out


async def fetch_all(cities: list[str] | None = None) -> list[Agency]:
    agencies: list[Agency] = []
    async with Fetcher() as f:
        for city in cities or list(CITIES):
            res = await f.get(f"{BASE}/{city}/inmobiliario.html")
            agencies.extend(parse_directory(res.text, city))
    seen, uniq = set(), []
    for a in agencies:
        key = (a.name.lower(), a.city)
        if key not in seen:
            seen.add(key)
            uniq.append(a)
    return uniq


def main() -> None:
    agencies = asyncio.run(fetch_all())
    w = csv.DictWriter(sys.stdout, fieldnames=list(Agency.__dataclass_fields__))
    w.writeheader()
    for a in agencies:
        w.writerow(asdict(a))


if __name__ == "__main__":
    main()
