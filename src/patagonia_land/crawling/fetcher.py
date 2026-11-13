"""Fetcher responsable: robots.txt, rate limit por dominio, backoff, protección SSRF, límites de tamaño.

No evade CAPTCHA, login ni paywalls: ante 401/403/429 o señales de bloqueo se detiene y lo reporta.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx
import structlog

from patagonia_land.config import Settings, get_settings
from patagonia_land.crawling.robots import Robots

log = structlog.get_logger()

BLOCK_MARKERS = ("captcha", "cf-challenge", "challenge-platform", "are you a robot", "verify you are human")


class FetchError(Exception):
    pass


class BlockedError(FetchError):
    """El sitio pide login/captcha o devolvió señales de bloqueo: no se intenta evadir."""


class SSRFError(FetchError):
    pass


class RateLimited(BlockedError):
    """El sitio sigue respondiendo 429 tras frenar: se corta la corrida en vez de insistir."""


class RobotsDisallowed(FetchError):
    pass


class OutsideVisitTime(BlockedError):
    """El sitio pide visitas solo en cierta franja horaria (Visit-time): se corta la corrida."""


@dataclass
class FetchResult:
    url: str  # URL final tras redirecciones
    requested_url: str
    status: int
    headers: dict[str, str]
    text: str
    content_type: str
    elapsed: float
    rendered: bool = False

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8", "ignore")).hexdigest()

    @property
    def is_html(self) -> bool:
        return "html" in self.content_type or self.text.lstrip()[:15].lower().startswith(("<!doctype", "<html"))


def _is_forbidden_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return (
        addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
        or addr.is_reserved or addr.is_unspecified
        or ip.startswith("169.254.")  # metadata cloud
        or (addr.version == 6 and addr.ipv4_mapped is not None and _is_forbidden_ip(str(addr.ipv4_mapped)))
    )


def assert_public_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise SSRFError(f"Esquema no permitido: {parts.scheme}")
    host = parts.hostname
    if not host:
        raise SSRFError("URL sin host")
    if host in ("localhost", "metadata.google.internal") or host.endswith((".local", ".internal")):
        raise SSRFError(f"Host prohibido: {host}")
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise FetchError(f"DNS no resuelve {host}: {exc}") from exc
    for info in infos:
        if _is_forbidden_ip(info[4][0]):
            raise SSRFError(f"{host} resuelve a IP privada/prohibida {info[4][0]}")


@dataclass
class Fetcher:
    settings: Settings = field(default_factory=get_settings)
    allow_private: bool = False  # solo tests
    transport: httpx.AsyncBaseTransport | None = None
    _client: httpx.AsyncClient | None = None
    _robots: dict[str, Robots | None] = field(default_factory=dict)
    _last_hit: dict[str, float] = field(default_factory=dict)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    _penalty: dict[str, float] = field(default_factory=dict)  # segundos extra por host tras recibir 429
    requests_made: int = 0

    async def __aenter__(self) -> Fetcher:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self.settings.user_agent, "Accept-Language": "es-AR,es;q=0.9"},
            timeout=self.settings.request_timeout_seconds,
            follow_redirects=False,
            transport=self.transport,
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client:
            await self._client.aclose()

    # --- robots ---------------------------------------------------------------------------------
    async def robots_for(self, url: str) -> Robots | None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        rp: Robots | None
        try:
            res = await self._raw_get(urljoin(origin, "/robots.txt"), check_robots=False)
            if res.status == 200 and "<html" not in res.text[:500].lower():
                rp = Robots(res.text)
            elif res.status in (401, 403):
                rp = Robots(disallow_all=True)
            else:
                rp = None  # sin robots.txt => permitido
        except FetchError:
            rp = None
        self._robots[origin] = rp
        return rp

    async def allowed(self, url: str) -> bool:
        if not self.settings.respect_robots:
            return True
        rp = await self.robots_for(url)
        return True if rp is None else rp.can_fetch(self.settings.user_agent, url)

    async def sitemaps_from_robots(self, url: str) -> list[str]:
        rp = await self.robots_for(url)
        return list(rp.sitemaps) if rp else []

    def crawl_delay(self, url: str) -> float:
        rp = self._robots.get(f"{urlsplit(url).scheme}://{urlsplit(url).netloc}")
        delay = rp.min_interval(self.settings.user_agent) if rp and self.settings.respect_robots else 0.0
        return max(delay, self.settings.request_delay_seconds) + self._penalty.get(urlsplit(url).netloc, 0.0)

    # --- fetch ----------------------------------------------------------------------------------
    async def _throttle(self, url: str) -> None:
        host = urlsplit(url).netloc
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._last_hit.get(host, 0) + self.crawl_delay(url) - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_hit[host] = time.monotonic()

    async def _raw_get(self, url: str, check_robots: bool = True, max_redirects: int = 5) -> FetchResult:
        assert self._client, "usar 'async with Fetcher()'"
        current = url
        for _ in range(max_redirects + 1):
            if not self.allow_private:
                await asyncio.to_thread(assert_public_url, current)
            if check_robots and not await self.allowed(current):
                raise RobotsDisallowed(f"robots.txt no permite {current}")
            if check_robots and self.settings.respect_robots:
                rp = await self.robots_for(current)
                if rp and not rp.visit_allowed_now(self.settings.user_agent):
                    raise OutsideVisitTime(f"robots.txt solo permite visitas en la franja {rp.policy(self.settings.user_agent).get('visit_time_utc')} UTC")
            await self._throttle(current)
            started = time.monotonic()
            self.requests_made += 1
            async with self._client.stream("GET", current) as resp:
                if resp.is_redirect and resp.headers.get("location"):
                    current = urljoin(current, resp.headers["location"])
                    continue
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > self.settings.max_response_bytes:
                        raise FetchError(f"Respuesta demasiado grande: {current}")
                    chunks.append(chunk)
                body = b"".join(chunks)
                encoding = resp.encoding or "utf-8"
                return FetchResult(
                    url=current, requested_url=url, status=resp.status_code,
                    headers=dict(resp.headers), text=body.decode(encoding, errors="replace"),
                    content_type=resp.headers.get("content-type", ""), elapsed=time.monotonic() - started,
                )
        raise FetchError(f"Demasiadas redirecciones: {url}")

    async def get(self, url: str, retries: int = 2) -> FetchResult:
        delay = self.settings.request_delay_seconds or 0.5
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                res = await self._raw_get(url)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                await asyncio.sleep(delay * (2**attempt))
                continue
            if res.status in (401, 407):
                raise BlockedError(f"{url} requiere autenticación ({res.status})")
            if res.status == 403 or (res.status == 200 and _looks_blocked(res.text)):
                raise BlockedError(f"{url} bloqueado o con captcha ({res.status})")
            if res.status == 429:
                # Frenar para todo el host (no solo este pedido): el intervalo crece y se mantiene en la corrida.
                host = urlsplit(url).netloc
                self._penalty[host] = min(60.0, max(2 * self._penalty.get(host, 0.0), 2 * delay, 5.0))
                retry_after = res.headers.get("retry-after", "")
                wait = float(retry_after) if retry_after.isdigit() else self._penalty[host]
                if attempt == retries or wait > 120:
                    raise RateLimited(f"{url}: HTTP 429 persistente; se detiene la corrida para no saturar el sitio")
                await asyncio.sleep(wait)
                last_exc = FetchError(f"HTTP 429 en {url}")
                continue
            if res.status >= 500:
                retry_after = res.headers.get("retry-after", "")
                await asyncio.sleep(float(retry_after) if retry_after.isdigit() else delay * (2 ** (attempt + 1)))
                last_exc = FetchError(f"HTTP {res.status} en {url}")
                continue
            return res
        raise FetchError(str(last_exc) if last_exc else f"Fallo al obtener {url}")

    async def render(self, url: str) -> FetchResult:
        """Renderizado con Playwright (aislado, sin descargas, solo si ENABLE_PLAYWRIGHT)."""
        if not self.settings.enable_playwright:
            raise FetchError("Playwright deshabilitado (ENABLE_PLAYWRIGHT=false)")
        if not self.allow_private:
            await asyncio.to_thread(assert_public_url, url)
        if not await self.allowed(url):
            raise RobotsDisallowed(f"robots.txt no permite {url}")
        await self._throttle(url)
        from playwright.async_api import async_playwright  # import diferido: dependencia opcional

        started = time.monotonic()
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(args=["--disable-dev-shm-usage"])
            ctx = await browser.new_context(user_agent=self.settings.user_agent, accept_downloads=False)
            page = await ctx.new_page()
            await page.route("**/*", lambda r: r.abort() if r.request.resource_type in
                             ("image", "media", "font") else r.continue_())
            resp = await page.goto(url, wait_until="networkidle", timeout=45_000)
            html = await page.content()
            final_url = page.url
            await browser.close()
        if _looks_blocked(html):
            raise BlockedError(f"{url} bloqueado o con captcha")
        return FetchResult(url=final_url, requested_url=url, status=resp.status if resp else 0, headers={},
                           text=html, content_type="text/html", elapsed=time.monotonic() - started,
                           rendered=True)


def _looks_blocked(text: str) -> bool:
    head = text[:5000].lower()
    return any(m in head for m in BLOCK_MARKERS) and len(text) < 30_000
