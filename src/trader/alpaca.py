"""Alpaca historical market data client for US equities and crypto."""

from __future__ import annotations

import importlib
import importlib.util
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any

import pandas as pd

from trader.config import ALPACA_TIMEFRAME_MAP, TIMEFRAME_TO_MINUTES, validate_timeframe


class AlpacaError(RuntimeError):
    """Base Alpaca integration error."""


class AlpacaUnavailableError(AlpacaError):
    """Raised when the alpaca-py package is not importable."""


@dataclass(frozen=True)
class AlpacaConnectionSettings:
    api_key: str | None = None
    api_secret: str | None = None
    paper: bool = True
    data_feed: str = "iex"

    @classmethod
    def from_env(cls) -> "AlpacaConnectionSettings":
        return cls(
            api_key=os.getenv("ALPACA_API_KEY_ID"),
            api_secret=os.getenv("ALPACA_API_SECRET_KEY"),
            paper=_parse_bool(os.getenv("ALPACA_PAPER"), default=True),
            data_feed=(os.getenv("ALPACA_DATA_FEED") or "iex").lower(),
        )


class AlpacaClient:
    def __init__(
        self,
        settings: AlpacaConnectionSettings | None = None,
        stock_client: Any | None = None,
        crypto_client: Any | None = None,
    ) -> None:
        self.settings = settings or AlpacaConnectionSettings.from_env()
        self._stock_client = stock_client
        self._crypto_client = crypto_client

    @classmethod
    def from_env(cls) -> "AlpacaClient":
        return cls(settings=AlpacaConnectionSettings.from_env())

    @staticmethod
    def is_available() -> bool:
        return importlib.util.find_spec("alpaca") is not None

    def copy_rates(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        validated_tf = validate_timeframe(timeframe)
        is_crypto = "/" in symbol
        raw = self._fetch_bars_df(symbol, validated_tf, bars, is_crypto)
        return self._normalize_frame(raw, symbol, validated_tf, bars)

    def _fetch_bars_df(
        self,
        symbol: str,
        timeframe: str,
        bars: int,
        is_crypto: bool,
    ) -> pd.DataFrame:
        client = self._get_crypto_client() if is_crypto else self._get_stock_client()
        request = self._build_request(symbol, timeframe, bars, is_crypto)
        try:
            bar_set = (
                client.get_crypto_bars(request)
                if is_crypto
                else client.get_stock_bars(request)
            )
        except Exception as exc:
            raise AlpacaError(f"Alpaca-Datenabfrage fuer {symbol} fehlgeschlagen: {exc}") from exc

        df = getattr(bar_set, "df", None)
        if df is None:
            raise AlpacaError(f"Alpaca lieferte keine .df-Antwort fuer {symbol}.")
        return df

    @staticmethod
    def _normalize_frame(
        raw: pd.DataFrame,
        symbol: str,
        timeframe: str,
        bars: int,
    ) -> pd.DataFrame:
        if raw is None or raw.empty:
            raise AlpacaError(
                f"Alpaca lieferte keine Bars fuer {symbol}. "
                "Bei --source alpaca brauchst du US-Tickers wie AAPL/SPY oder Crypto wie BTC/USD."
            )

        frame = raw.reset_index() if isinstance(raw.index, pd.MultiIndex) else raw.copy()
        if "timestamp" not in frame.columns and "time" not in frame.columns:
            frame = frame.reset_index()

        time_column = "timestamp" if "timestamp" in frame.columns else "time"
        frame = frame.rename(columns={time_column: "time"})
        frame["time"] = pd.to_datetime(frame["time"], utc=True)

        for column in ("open", "high", "low", "close", "volume"):
            if column not in frame.columns:
                raise AlpacaError(f"Alpaca-Antwort fuer {symbol} fehlt Spalte '{column}'.")

        frame["tick_volume"] = pd.NA
        frame["real_volume"] = pd.NA
        frame["spread"] = pd.NA
        frame["symbol"] = symbol
        frame["timeframe"] = timeframe
        frame["data_source"] = "alpaca"

        expected_columns = [
            "time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "tick_volume",
            "spread",
            "real_volume",
            "symbol",
            "timeframe",
            "data_source",
        ]
        return (
            frame[expected_columns]
            .sort_values("time")
            .tail(bars)
            .reset_index(drop=True)
        )

    def _get_stock_client(self) -> Any:
        if self._stock_client is not None:
            return self._stock_client
        self._require_credentials()
        module = self._import_module("alpaca.data.historical")
        self._stock_client = module.StockHistoricalDataClient(
            api_key=self.settings.api_key,
            secret_key=self.settings.api_secret,
        )
        return self._stock_client

    def _get_crypto_client(self) -> Any:
        if self._crypto_client is not None:
            return self._crypto_client
        self._require_credentials()
        module = self._import_module("alpaca.data.historical")
        self._crypto_client = module.CryptoHistoricalDataClient(
            api_key=self.settings.api_key,
            secret_key=self.settings.api_secret,
        )
        return self._crypto_client

    def _build_request(
        self,
        symbol: str,
        timeframe: str,
        bars: int,
        is_crypto: bool,
    ) -> Any:
        requests_module = self._import_module("alpaca.data.requests")
        timeframe_module = self._import_module("alpaca.data.timeframe")
        amount, unit_name = ALPACA_TIMEFRAME_MAP[timeframe]
        tf = timeframe_module.TimeFrame(amount, getattr(timeframe_module.TimeFrameUnit, unit_name))
        start = _estimate_start(timeframe, bars, is_crypto)

        if is_crypto:
            return requests_module.CryptoBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=start,
            )

        feed_module = self._import_module("alpaca.data.enums")
        feed = getattr(feed_module.DataFeed, self.settings.data_feed.upper(), feed_module.DataFeed.IEX)
        return requests_module.StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf,
            start=start,
            feed=feed,
        )

    def _require_credentials(self) -> None:
        if not self.settings.api_key or not self.settings.api_secret:
            raise AlpacaError(
                "ALPACA_API_KEY_ID und ALPACA_API_SECRET_KEY muessen gesetzt sein."
            )

    @staticmethod
    def _import_module(name: str) -> Any:
        try:
            return importlib.import_module(name)
        except ImportError as exc:
            raise AlpacaUnavailableError(
                "alpaca-py ist nicht installiert. Installiere es mit "
                "'poetry install --with alpaca'."
            ) from exc


def _estimate_start(timeframe: str, bars: int, is_crypto: bool) -> datetime:
    minutes = TIMEFRAME_TO_MINUTES[timeframe]
    # Crypto trades 24/7, so 1.5x calendar buffer suffices.
    # US equities trade ~6.5h × 5/7 days ≈ 19% of wall time, so we need ~5x to
    # ensure short-timeframe requests return enough bars after .tail(bars).
    buffer = 1.5 if is_crypto else 5.0
    raw_days = ceil((bars * minutes) / (24 * 60) * buffer)
    minimum_days = 7 if minutes < 1440 else 365
    days = max(raw_days, minimum_days)
    return datetime.now(timezone.utc) - timedelta(days=days)


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Ungueltiger Boolean-Wert fuer ALPACA_PAPER: {value}")
