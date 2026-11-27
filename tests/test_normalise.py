from src.common.normalise import parse_amount


def test_currency_symbols_are_parsed():
    assert parse_amount("1,299.50") == 1299.50
    assert parse_amount("$12.00") == 12.0


def test_unparseable_amount_returns_none():
    assert parse_amount("N/A") is None
