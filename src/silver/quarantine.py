"""Silver-layer validation: good rows pass, bad rows go to quarantine with a reason."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class QuarantinedRow:
    row: dict
    reason_code: str


def validate_sale(row: dict, known_products: set[str], known_stores: set[str]):
    """Return (clean_row, None) or (None, QuarantinedRow). Mirrors the DQ rules."""
    if row.get("product_id") not in known_products:
        return None, QuarantinedRow(row, "UNKNOWN_PRODUCT")
    if row.get("store_id") not in known_stores:
        return None, QuarantinedRow(row, "UNKNOWN_STORE")
    qty = row.get("quantity")
    if qty is None or (qty < 0 and not row.get("is_return", False)):
        return None, QuarantinedRow(row, "NEGATIVE_QTY")
    return row, None
