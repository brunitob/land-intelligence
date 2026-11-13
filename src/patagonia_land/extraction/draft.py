"""Acumulador de campos con proveniencia: la primera fuente (más prioritaria) gana."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from patagonia_land.extraction.schemas import Provenance


@dataclass
class Draft:
    values: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Provenance] = field(default_factory=dict)
    methods: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def has(self, key: str) -> bool:
        v = self.values.get(key)
        return v is not None and v != [] and v != ""

    def offer(self, key: str, value: Any, method: str, evidence: str | None = None,
              confidence: float = 0.8, override: bool = False) -> bool:
        if value is None or value == "" or value == []:
            return False
        if self.has(key) and not override:
            return False
        self.values[key] = value
        self.provenance[key] = Provenance(method=method, evidence=(evidence or str(value))[:300],
                                          confidence=confidence)
        if method not in self.methods:
            self.methods.append(method)
        return True

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)
