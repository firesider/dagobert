"""Project-level defaults and market metadata."""

from __future__ import annotations

DEFAULT_ALPACA_SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "META",
    "TSLA",
    "SPY",
    "QQQ",
]

SUPPORTED_TIMEFRAMES = ("5m", "15m", "1h", "4h", "1d")

TIMEFRAME_TO_MINUTES = {
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

ALPACA_TIMEFRAME_MAP = {
    "5m": (5, "Minute"),
    "15m": (15, "Minute"),
    "1h": (1, "Hour"),
    "4h": (4, "Hour"),
    "1d": (1, "Day"),
}


def normalize_symbol(symbol: str) -> str:
    """Normalize a user-provided symbol string for Alpaca routing.

    Accepts equity tickers (1-5 uppercase letters, e.g. ``AAPL``) and crypto
    pairs (``BASE/QUOTE``, e.g. ``BTC/USD``). Strips whitespace and uppercases
    the input.
    """
    cleaned = symbol.strip().upper().replace(" ", "")
    if "/" in cleaned:
        base, _, quote = cleaned.partition("/")
        if not base or not quote or not base.isalpha() or not quote.isalpha():
            raise ValueError(
                f"Ungueltiges Crypto-Symbol '{symbol}'. Erwartet wird BASE/QUOTE wie BTC/USD."
            )
        return cleaned
    if not cleaned.isalpha() or not 1 <= len(cleaned) <= 5:
        raise ValueError(
            f"Ungueltiges Symbol '{symbol}'. Erwartet wird ein 1-5 Zeichen langer "
            "Ticker (AAPL, MSFT) oder ein Crypto-Paar (BTC/USD)."
        )
    return cleaned


def validate_timeframe(timeframe: str) -> str:
    if timeframe not in SUPPORTED_TIMEFRAMES:
        supported = ", ".join(SUPPORTED_TIMEFRAMES)
        raise ValueError(f"Timeframe '{timeframe}' wird nicht unterstuetzt. Erlaubt: {supported}")
    return timeframe


def timeframe_to_minutes(timeframe: str) -> int:
    return TIMEFRAME_TO_MINUTES[validate_timeframe(timeframe)]
