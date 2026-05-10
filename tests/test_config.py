from __future__ import annotations

import pytest

from trader.config import normalize_symbol


@pytest.mark.parametrize(
    "given,expected",
    [
        ("AAPL", "AAPL"),
        ("aapl", "AAPL"),
        ("  msft  ", "MSFT"),
        ("A", "A"),
        ("BRKB", "BRKB"),
        ("GOOGL", "GOOGL"),
    ],
)
def test_normalize_symbol_accepts_equity_tickers(given: str, expected: str) -> None:
    assert normalize_symbol(given) == expected


@pytest.mark.parametrize(
    "given,expected",
    [
        ("BTC/USD", "BTC/USD"),
        ("eth/usd", "ETH/USD"),
        ("BTC / USD", "BTC/USD"),
        ("SOL/USDT", "SOL/USDT"),
    ],
)
def test_normalize_symbol_accepts_crypto_pairs(given: str, expected: str) -> None:
    assert normalize_symbol(given) == expected


@pytest.mark.parametrize(
    "given",
    [
        "",
        "GOOGLE1",  # too long, contains digit
        "AAPL2",  # contains digit
        "TOOLONG",  # 7 chars
        "BTC/",  # missing quote
        "/USD",  # missing base
        "BTC/123",  # quote not letters
        "BTC--USD",  # invalid separator
    ],
)
def test_normalize_symbol_rejects_invalid_inputs(given: str) -> None:
    with pytest.raises(ValueError):
        normalize_symbol(given)
