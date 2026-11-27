"""Standardisation helpers for the planted-defect categories."""
from __future__ import annotations
import re
from datetime import datetime, timezone


def parse_amount(raw: str | float | int) -> float | None:
    """'₹1,299.50' / '$12.00' / '1299.5' -> float; unparseable -> None (quarantine)."""
    if isinstance(raw, (int, float)):
        return float(raw)
    cleaned = re.sub(r"[^\d.\-]", "", str(raw))
    try:
        return float(cleaned)
    except ValueError:
        return None


def to_utc(dt: datetime) -> datetime:
    """Normalise mixed-tz timestamps to a single zone (UTC) at silver."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
