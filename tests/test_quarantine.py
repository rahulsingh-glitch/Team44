from src.silver.quarantine import validate_sale

PRODUCTS = {"P1", "P2"}
STORES = {"S1"}


def test_unknown_product_is_quarantined():
    clean, q = validate_sale({"product_id": "X", "store_id": "S1", "quantity": 1}, PRODUCTS, STORES)
    assert clean is None and q.reason_code == "UNKNOWN_PRODUCT"


def test_negative_qty_quarantined_unless_return():
    _, q = validate_sale({"product_id": "P1", "store_id": "S1", "quantity": -2}, PRODUCTS, STORES)
    assert q.reason_code == "NEGATIVE_QTY"
    clean, q2 = validate_sale(
        {"product_id": "P1", "store_id": "S1", "quantity": -2, "is_return": True}, PRODUCTS, STORES
    )
    assert clean is not None and q2 is None


def test_good_row_passes():
    clean, q = validate_sale({"product_id": "P1", "store_id": "S1", "quantity": 3}, PRODUCTS, STORES)
    assert clean is not None and q is None
