"""Project-level defaults and market metadata."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil

DEFAULT_FOREX_SYMBOLS = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "AUDUSD",
    "USDCAD",
    "NZDUSD",
    "EURGBP",
    "EURJPY",
    "GBPJPY",
]

SUPPORTED_TIMEFRAMES = ("5m", "15m", "1h", "4h", "1d")

TIMEFRAME_TO_MINUTES = {
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

YFINANCE_INTERVAL_MAP = {
    "5m": "5m",
    "15m": "15m",
    "1h": "60m",
    "4h": "60m",
    "1d": "1d",
}

YFINANCE_LOOKBACK_CAP_DAYS = {
    "5m": 59,
    "15m": 59,
    "1h": 729,
    "4h": 729,
    "1d": 3650,
}

RESAMPLE_RULE_MAP = {
    "4h": "4h",
}

MT5_TIMEFRAME_ATTR_MAP = {
    "5m": "TIMEFRAME_M5",
    "15m": "TIMEFRAME_M15",
    "1h": "TIMEFRAME_H1",
    "4h": "TIMEFRAME_H4",
    "1d": "TIMEFRAME_D1",
}


def normalize_symbol(symbol: str) -> str:
    """Convert symbol input such as EUR/USD into EURUSD."""
    cleaned = symbol.replace("/", "").replace(" ", "").upper()
    if len(cleaned) != 6:
        raise ValueError(
            f"Ungueltiges Forex-Symbol '{symbol}'. Erwartet wird z. B. EURUSD oder EUR/USD."
        )
    return cleaned


def validate_timeframe(timeframe: str) -> str:
    if timeframe not in SUPPORTED_TIMEFRAMES:
        supported = ", ".join(SUPPORTED_TIMEFRAMES)
        raise ValueError(f"Timeframe '{timeframe}' wird nicht unterstuetzt. Erlaubt: {supported}")
    return timeframe


def timeframe_to_minutes(timeframe: str) -> int:
    return TIMEFRAME_TO_MINUTES[validate_timeframe(timeframe)]


def yfinance_symbol(symbol: str) -> str:
    return f"{normalize_symbol(symbol)}=X"


def estimate_yfinance_start(timeframe: str, bars: int) -> datetime:
    """Estimate a conservative lookback window for Yahoo Finance downloads."""
    tf = validate_timeframe(timeframe)
    minutes = timeframe_to_minutes(tf)
    raw_days = ceil((bars * minutes) / (24 * 60) * 1.4)
    minimum_days = {
        "5m": 7,
        "15m": 14,
        "1h": 60,
        "4h": 180,
        "1d": 365,
    }[tf]
    days = min(max(raw_days, minimum_days), YFINANCE_LOOKBACK_CAP_DAYS[tf])
    return datetime.now(timezone.utc) - timedelta(days=days)
