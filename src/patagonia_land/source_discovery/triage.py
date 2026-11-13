"""Triage rápido de un sitio candidato (2–3 pedidos): ¿se puede rastrear? ¿publica fichas? ¿qué plataforma?

No reemplaza al Site Inspector: decide si vale la pena registrarlo e inspeccionarlo.

Uso: python -m patagonia_land.source_discovery.triage candidatos.csv > triage.csv
     (CSV con columnas name, city, website)
"""

from __future__ import annotations

import asyncio
import csv
import re
import sys
from dataclasses import asdict, dataclass, field
from urllib.parse import urlsplit

from patagonia_land.crawling.fetcher import (
    BlockedError,
    Fetcher,
    FetchError,
    OutsideVisitTime,
    RobotsDisallowed,
)
from patagonia_land.crawling.page import Page, path_has_id, url_token_score
from patagonia_land.crawling.urls import same_site

# Huellas de plataformas comunes en inmobiliarias argentinas.
PLATFORMS = {
    "tokko": re.compile(r"tokkobroker|tokko", re.IGNORECASE),
    "xintel": re.compile(r"xintel", re.IGNORECASE),
    "kiteprop": re.compile(r"kiteprop", re.IGNORECASE),
    "mapaprop": re.compile(r"mapaprop", re.IGNORECASE),
    "inmoup": re.compile(r"inmoup", re.IGNORECASE),
    "remax": re.compile(r"remax\.com", re.IGNORECASE),
    "wix": re.compile(r"wixstatic|wix\.com", re.IGNORECASE),
    "wordpress": re.compile(r"wp-content|wp-json", re.IGNORECASE),
    "houzez": re.compile(r"houzez", re.IGNORECASE),
    "wpresidence": re.compile(r"wpresidence", re.IGNORECASE),
    "real-homes": re.compile(r"realhomes|real-homes", re.IGNORECASE),
    "estatik": re.compile(r"estatik", re.IGNORECASE),
    "squarespace": re.compile(r"squarespace", re.IGNORECASE),
    "nextjs": re.compile(r"__NEXT_DATA__|/_next/", re.IGNORECASE),
    "nuxt": re.compile(r"__NUXT__|/_nuxt/", re.IGNORECASE),
}
LAND_WORDS = re.compile(r"\b(terrenos?|lotes?|chacras?|campos?|fracci[oó]n|hect[aá]reas?)\b", re.IGNORECASE)
LISTING_TOKENS = ("propiedad", "propiedades", "inmueble", "ficha", "terreno", "lote", "venta", "property",
                  "listing", "chacra", "campo", "casa", "departamento")
SECTION_HINT = re.compile(r"terreno|lote|chacra|campo|propiedades|venta|inmuebles", re.IGNORECASE)


@dataclass
class Triage:
    name: str
    city: str
    website: str
    final_url: str | None = None
    status: str = "pending"  # ok | robots_blocks | robots_slow | blocked | error | no_site
    robots: str | None = None  # absent | present
    robots_notes: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    script_heavy: bool | None = None
    detail_like_links: int = 0
    land_word_hits: int = 0
    section_links: list[str] = field(default_factory=list)
    verdict: str = ""  # viable | revisar | descartar
    reason: str = ""


async def triage_site(fetcher: Fetcher, name: str, city: str, website: str) -> Triage:
    t = Triage(name, city, website)
    if not website:
        t.status, t.verdict, t.reason = "no_site", "descartar", "sin sitio propio"
        return t
    url = website if website.startswith("http") else f"https://{website}"
    try:
        rp = await fetcher.robots_for(url)
        t.robots = "present" if rp is not None else "absent"
        if rp is not None:
            pol = rp.policy(fetcher.settings.user_agent)
            if pol.get("min_interval_seconds_now", 0) >= 60:
                t.robots_notes.append(f"intervalo≥{pol['min_interval_seconds_now']:.0f}s")
            if pol.get("visit_time_utc"):
                t.robots_notes.append(f"visit-time {pol['visit_time_utc']}")
            if pol.get("disallows_query_urls"):
                t.robots_notes.append("prohíbe '?'")
        res = await fetcher.get(url)
    except RobotsDisallowed:
        t.status, t.verdict, t.reason = "robots_blocks", "descartar", "robots.txt prohíbe la home"
        return t
    except OutsideVisitTime as exc:
        t.status, t.verdict, t.reason = "robots_slow", "revisar", f"robots exige crawl lento: {exc}"[:200]
        return t
    except BlockedError as exc:
        t.status, t.verdict, t.reason = "blocked", "descartar", f"bloqueo/captcha: {exc}"[:200]
        return t
    except FetchError as exc:
        t.status, t.verdict, t.reason = "error", "revisar", str(exc)[:200]
        return t
    t.final_url, t.status = res.url, "ok"
    page = Page(res.url, res.text, res.url)
    t.platforms = [k for k, rx in PLATFORMS.items() if rx.search(res.text)]
    t.script_heavy = page.script_heavy
    links = [u for u in page.links if same_site(u, res.url)]
    t.detail_like_links = sum(1 for u in set(links)
                              if path_has_id(u) and url_token_score(u, LISTING_TOKENS) > 0)
    t.land_word_hits = len(LAND_WORDS.findall(page.main_text))
    sections = []
    for a in page.soup.find_all("a", href=True):
        txt = a.get_text(" ", strip=True)
        if txt and len(txt) < 40 and SECTION_HINT.search(txt):
            href = a["href"]
            if not href.startswith(("mailto:", "tel:", "javascript:", "#")):
                sections.append(f"{txt}→{urlsplit(href).path or href}")
    t.section_links = list(dict.fromkeys(sections))[:6]

    blocking = [n for n in t.robots_notes if n.startswith(("intervalo", "visit-time"))]
    if blocking:
        t.verdict, t.reason = "revisar", "robots exige crawl lento: " + ", ".join(blocking)
    elif t.detail_like_links >= 3:
        t.verdict, t.reason = "viable", f"{t.detail_like_links} links tipo ficha en la home"
    elif t.section_links or t.land_word_hits >= 3:
        t.verdict, t.reason = "viable", "secciones de propiedades/terrenos detectadas"
    elif t.script_heavy:
        t.verdict, t.reason = "revisar", "sitio JS: puede requerir render o API pública"
    else:
        t.verdict, t.reason = "descartar", "sin indicios de fichas publicadas"
    return t


async def triage_many(rows: list[dict[str, str]], concurrency: int = 6) -> list[Triage]:
    sem = asyncio.Semaphore(concurrency)  # dominios distintos: el rate limit es por dominio en el Fetcher
    async with Fetcher() as fetcher:
        async def one(r: dict[str, str]) -> Triage:
            async with sem:
                return await triage_site(fetcher, r["name"], r["city"], (r.get("website") or "").strip())
        return await asyncio.gather(*(one(r) for r in rows))


def main() -> None:
    with open(sys.argv[1], encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    results = asyncio.run(triage_many(rows))
    w = csv.DictWriter(sys.stdout, fieldnames=list(Triage.__dataclass_fields__))
    w.writeheader()
    for t in results:
        d = asdict(t)
        for k in ("robots_notes", "platforms", "section_links"):
            d[k] = " | ".join(d[k])
        w.writerow(d)


if __name__ == "__main__":
    main()
