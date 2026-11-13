"""Detección de cambios entre snapshots de un anuncio."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ChangeType(StrEnum):
    NEW_LISTING = "new_listing"
    PRICE_DECREASED = "price_decreased"
    PRICE_INCREASED = "price_increased"
    AREA_CHANGED = "area_changed"
    DESCRIPTION_CHANGED = "description_changed"
    STATUS_CHANGED = "status_changed"
    REMOVED = "removed"
    RELISTED = "relisted"


@dataclass
class DetectedChange:
    change_type: ChangeType
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None
    pct_change: float | None = None


def content_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def _norm_text(s: str | None) -> str:
    return " ".join((s or "").lower().split())


def diff_snapshots(old: dict[str, Any], new: dict[str, Any]) -> list[DetectedChange]:
    changes: list[DetectedChange] = []
    op, np_ = old.get("price"), new.get("price")
    same_currency = old.get("currency") == new.get("currency")
    if op and np_ and same_currency and float(op) != float(np_):
        pct = round((float(np_) - float(op)) / float(op) * 100, 2)
        changes.append(DetectedChange(
            ChangeType.PRICE_DECREASED if np_ < op else ChangeType.PRICE_INCREASED,
            {"price": op, "currency": old.get("currency")}, {"price": np_, "currency": new.get("currency")}, pct))
    elif op and np_ and not same_currency:
        changes.append(DetectedChange(ChangeType.PRICE_INCREASED if np_ > op else ChangeType.PRICE_DECREASED,
                                      {"price": op, "currency": old.get("currency")},
                                      {"price": np_, "currency": new.get("currency")}, None))
    oa, na = old.get("area_m2"), new.get("area_m2")
    if oa and na and abs(float(oa) - float(na)) / float(oa) > 0.005:
        changes.append(DetectedChange(ChangeType.AREA_CHANGED, {"area_m2": oa}, {"area_m2": na},
                                      round((float(na) - float(oa)) / float(oa) * 100, 2)))
    if _norm_text(old.get("description")) != _norm_text(new.get("description")) and old.get("description") \
            and new.get("description"):
        changes.append(DetectedChange(ChangeType.DESCRIPTION_CHANGED,
                                      {"description": (old.get("description") or "")[:500]},
                                      {"description": (new.get("description") or "")[:500]}))
    if (old.get("status_text") or None) != (new.get("status_text") or None):
        changes.append(DetectedChange(ChangeType.STATUS_CHANGED, {"status_text": old.get("status_text")},
                                      {"status_text": new.get("status_text")}))
    return changes
