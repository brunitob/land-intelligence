"""Resolver el sitio propio de una agencia a partir de su nombre, VERIFICANDO contra datos del directorio.

Genera dominios candidatos a partir del nombre (slug ± palabras genéricas × .com.ar/.com), descarta los que
no resuelven DNS y acepta un sitio SOLO si su home publica un teléfono del directorio (evidencia fuerte) o
el nombre completo de la agencia junto con su ciudad (evidencia media). Nunca se acepta un dominio por
parecido del nombre: un dominio estacionado o de otra empresa no pasa la verificación.

Uso: python -m patagonia_land.source_discovery.resolve agencias.csv > resueltos.csv
"""

from __future__ import annotations

import asyncio
import csv
import re
import socket
import sys
from dataclasses import asdict, dataclass

from patagonia_land.crawling.fetcher import Fetcher, FetchError
from patagonia_land.crawling.page import Page
from patagonia_land.intelligence.normalization import strip_accents

GENERIC = ("negocios inmobiliarios", "bienes raices", "real estate", "gestion inmobiliaria", "inmobiliaria",
           "inmobiliario", "propiedades", "desarrollos", "emprendimientos", "estudio", "conexiones",
           "servicios", "group", "grupo", "patagonia", "patagonica", "bariloche", "sa", "srl", "y", "de", "la",
           "el", "los", "las")
SUFFIXES = ("", "propiedades", "inmobiliaria", "bienesraices", "realestate", "negocios")
PREFIXES = ("", "inmobiliaria")
TLDS = (".com.ar", ".com")
CITY_WORDS = {"bariloche": "bariloche", "villalaangostura": "angostura", "elbolson": "bolson",
              "sanmartindelosandes": "martin de los andes", "junindelosandes": "junin",
              "esquel": "esquel", "trevelin": "trevelin", "villatraful": "traful", "meliquina": "meliquina",
              "alumine": "alumine", "lagopuelo": "puelo", "el-hoyo": "hoyo", "epuyen": "epuyen",
              "cholila": "cholila"}
CITY_SLUG = {"bariloche": "bariloche", "villalaangostura": "vla", "elbolson": "bolson",
             "sanmartindelosandes": "sma", "junindelosandes": "junin", "esquel": "esquel",
             "trevelin": "trevelin", "villatraful": "traful", "meliquina": "meliquina", "alumine": "alumine",
             "lagopuelo": "puelo", "el-hoyo": "elhoyo", "epuyen": "epuyen", "cholila": "cholila"}


def _norm(s: str) -> str:
    s = strip_accents(s.lower()).replace("&", " y ")
    s = re.sub(r"\(.*?\)", " ", s)  # "(alquileres)", "(María Eugenia ...)"
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def candidate_domains(name: str, city: str, limit: int = 24) -> list[str]:
    base = _norm(name.split("/")[0])
    words = base.split()
    core_words = [w for w in words if w not in GENERIC]
    # quitar frases genéricas multi-palabra
    core = base
    for g in sorted(GENERIC, key=len, reverse=True):
        core = re.sub(rf"\b{g}\b", " ", core)
    core_words = core.split() or core_words
    slugs: list[str] = []
    full = "".join(words)
    if full:
        slugs += [full, "-".join(words)]
    if core_words:
        c = "".join(core_words)
        for p in PREFIXES:
            for s in SUFFIXES:
                slugs.append(f"{p}{c}{s}")
        slugs += ["-".join(core_words), f"{c}{CITY_SLUG.get(city, '')}", f"{c}patagonia"]
    out: list[str] = []
    for slug in dict.fromkeys(slugs):
        if 3 <= len(slug) <= 50:
            out += [slug + t for t in TLDS]
    return list(dict.fromkeys(out))[:limit]


def phone_keys(*fields: str | None) -> set[str]:
    """Últimos 7 dígitos de cada teléfono (sin característica ni 15): robusto a formatos."""
    keys = set()
    for f in fields:
        for chunk in re.split(r"\s{2,}|/|,|;| y ", f or ""):
            digits = re.sub(r"\D", "", chunk)
            if len(digits) >= 7:
                keys.add(digits[-7:])
    return keys


async def _resolves(host: str) -> bool:
    loop = asyncio.get_running_loop()
    try:
        await asyncio.wait_for(loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM), timeout=5)
        return True
    except (OSError, TimeoutError):
        return False


@dataclass
class Resolution:
    name: str
    city: str
    website: str = ""
    evidence: str = ""  # phone | name+city
    tried: int = 0
    resolved: int = 0


async def verify(fetcher: Fetcher, domain: str, name: str, city: str, phones: set[str]) -> str | None:
    try:
        res = await fetcher.get(f"https://{domain}/")
    except FetchError:
        try:
            res = await fetcher.get(f"http://{domain}/")
        except FetchError:
            return None
    if not res.is_html:
        return None
    page = Page(res.url, res.text, res.url)
    # dígitos de todo el HTML (tel: links, footer, whatsapp) — incluye ventanas por separadores
    digits = re.sub(r"\D", "", res.text)
    if any(k in digits for k in phones):
        return "phone"
    text = _norm(page.title + " " + page.main_text)
    full = _norm(name.split("/")[0])
    city_word = CITY_WORDS.get(city, city)
    if len(full) >= 8 and full in text and city_word in text:
        return "name+city"
    return None


async def resolve_agency(fetcher: Fetcher, row: dict[str, str]) -> Resolution:
    r = Resolution(row["name"], row["city"])
    cands = candidate_domains(row["name"], row["city"])
    r.tried = len(cands)
    alive = [d for d, ok in zip(cands, await asyncio.gather(*(_resolves(d) for d in cands)), strict=True) if ok]
    r.resolved = len(alive)
    phones = phone_keys(row.get("phones"), row.get("whatsapp"))
    for d in alive:
        ev = await verify(fetcher, d, row["name"], row["city"], phones)
        if ev:
            r.website, r.evidence = d, ev
            if ev == "phone":
                break
    return r


async def resolve_many(rows: list[dict[str, str]], concurrency: int = 8) -> list[Resolution]:
    sem = asyncio.Semaphore(concurrency)
    async with Fetcher() as fetcher:
        async def one(row: dict[str, str]) -> Resolution:
            async with sem:
                return await resolve_agency(fetcher, row)
        return await asyncio.gather(*(one(r) for r in rows))


def main() -> None:
    with open(sys.argv[1], encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    results = asyncio.run(resolve_many(rows))
    w = csv.DictWriter(sys.stdout, fieldnames=list(Resolution.__dataclass_fields__))
    w.writeheader()
    for r in results:
        w.writerow(asdict(r))


if __name__ == "__main__":
    main()
