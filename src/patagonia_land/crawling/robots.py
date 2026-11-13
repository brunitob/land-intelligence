"""Parser de robots.txt según RFC 9309 + extensiones comunes.

`urllib.robotparser` NO soporta comodines (`*`, `$`): una regla `Disallow: /*?` se tomaba literal y el
crawler pedía URLs prohibidas. Este parser implementa:
- grupos por user-agent (el más específico que coincide con nuestro token; si no, `*`),
- `*` y `$` en reglas, regla más larga gana, Allow gana en empate,
- `Crawl-delay`, `Request-rate` (n/período, opcionalmente con franja horaria) y `Visit-time` (UTC).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import unquote, urlsplit


@dataclass
class Rule:
    allow: bool
    path: str
    regex: re.Pattern[str]


@dataclass
class RequestRate:
    requests: int
    seconds: int
    window: tuple[int, int] | None = None  # (HHMM, HHMM) UTC

    @property
    def min_interval(self) -> float:
        return self.seconds / max(self.requests, 1)


@dataclass
class Group:
    agents: list[str] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    crawl_delay: float | None = None
    request_rates: list[RequestRate] = field(default_factory=list)
    visit_time: tuple[int, int] | None = None


def _compile(path: str) -> re.Pattern[str]:
    anchored = path.endswith("$")
    body = path[:-1] if anchored else path
    pattern = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile("^" + pattern + ("$" if anchored else ""))


def _window(s: str) -> tuple[int, int] | None:
    m = re.match(r"^\s*(\d{4})\s*-\s*(\d{4})", s)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _in_window(window: tuple[int, int], now: datetime) -> bool:
    hhmm = now.hour * 100 + now.minute
    start, end = window
    return start <= hhmm < end if start <= end else hhmm >= start or hhmm < end


UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class Robots:
    def __init__(self, text: str = "", disallow_all: bool = False):
        self.groups: list[Group] = []
        self.sitemaps: list[str] = []
        self.disallow_all = disallow_all
        self._parse(text)

    def _parse(self, text: str) -> None:
        current: Group | None = None
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (x.strip() for x in line.split(":", 1))
            key = key.lower()
            if key == "sitemap":
                self.sitemaps.append(value)
                continue
            if key == "user-agent":
                if current is None or not last_was_agent:
                    current = Group()
                    self.groups.append(current)
                current.agents.append(value.lower())
                last_was_agent = True
                continue
            last_was_agent = False
            if current is None:
                continue
            if key in ("allow", "disallow"):
                if value == "" and key == "disallow":
                    continue  # "Disallow:" vacío = permitir todo
                path = unquote(value)
                current.rules.append(Rule(allow=key == "allow", path=path, regex=_compile(path)))
            elif key == "crawl-delay":
                try:
                    current.crawl_delay = float(value.split()[0])
                except (ValueError, IndexError):
                    pass
            elif key == "request-rate":
                m = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*([smhd]?)\s*(.*)$", value, re.I)
                if m:
                    secs = int(m.group(2)) * UNITS.get((m.group(3) or "s").lower(), 1)
                    current.request_rates.append(RequestRate(int(m.group(1)), secs, _window(m.group(4))))
            elif key == "visit-time":
                current.visit_time = _window(value)

    def group_for(self, user_agent: str) -> Group | None:
        token = user_agent.split("/")[0].strip().lower()
        best: Group | None = None
        best_len = -1
        star: Group | None = None
        for g in self.groups:
            for a in g.agents:
                if a == "*":
                    star = star or g
                elif a and a in token and len(a) > best_len:
                    best, best_len = g, len(a)
        return best or star

    def can_fetch(self, user_agent: str, url: str) -> bool:
        if self.disallow_all:
            return False
        g = self.group_for(user_agent)
        if not g:
            return True
        parts = urlsplit(url)
        target = unquote(parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        best: Rule | None = None
        for r in g.rules:
            if r.regex.match(target):
                if best is None or len(r.path) > len(best.path) or (len(r.path) == len(best.path) and r.allow):
                    best = r
        return True if best is None else best.allow

    def min_interval(self, user_agent: str, now: datetime | None = None) -> float:
        """Intervalo mínimo entre pedidos: max(Crawl-delay, Request-rate aplicable ahora)."""
        g = self.group_for(user_agent)
        if not g:
            return 0.0
        now = now or datetime.now(UTC)
        interval = g.crawl_delay or 0.0
        for rr in g.request_rates:
            if rr.window is None or _in_window(rr.window, now):
                interval = max(interval, rr.min_interval)
        # Si hay varias reglas sin franja, ya tomamos la más restrictiva.
        return interval

    def visit_allowed_now(self, user_agent: str, now: datetime | None = None) -> bool:
        g = self.group_for(user_agent)
        if not g or not g.visit_time:
            return True
        return _in_window(g.visit_time, now or datetime.now(UTC))

    def policy(self, user_agent: str) -> dict[str, object]:
        g = self.group_for(user_agent)
        if not g:
            return {}
        return {
            "group": g.agents,
            "crawl_delay": g.crawl_delay,
            "request_rates": [f"{r.requests}/{r.seconds}s" + (f" {r.window}" if r.window else "")
                              for r in g.request_rates],
            "visit_time_utc": g.visit_time,
            "min_interval_seconds_now": self.min_interval(user_agent),
            "disallows_query_urls": not self.can_fetch(user_agent, "https://x/a?b=1"),
        }
