"""Market data adapters for MetaTrader 5 and yfinance."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from trader.config import (
    MT5_TIMEFRAME_ATTR_MAP,
    RESAMPLE_RULE_MAP,
    YFINANCE_INTERVAL_MAP,
    estimate_yfinance_start,
    normalize_symbol,
    validate_timeframe,
    yfinance_symbol,
)
from trader.mt5 import MetaTrader5Client, Mt5Error


class DataSourceError(RuntimeError):
    """Raised when a market data source cannot return valid data."""


@dataclass(frozen=True)
class FetchRequest:
    symbol: str
    timeframe: str
    bars: int


class YFinanceDataSource:
    source_name = "yfinance"

    def fetch(self, request: FetchRequest) -> pd.DataFrame:
        symbol = normalize_symbol(request.symbol)
        timeframe = validate_timeframe(request.timeframe)
        start = estimate_yfinance_start(timeframe=timeframe, bars=request.bars)
        end = datetime.now(timezone.utc)
        interval = YFINANCE_INTERVAL_MAP[timeframe]

        frame = yf.download(
            tickers=yfinance_symbol(symbol),
            start=start,
            end=end,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
        )

        if frame.empty:
            raise DataSourceError(
                f"yfinance lieferte keine Daten fuer {symbol} im Timeframe {timeframe}."
            )

        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)

        frame = frame.reset_index()
        time_column = "Datetime" if "Datetime" in frame.columns else "Date"
        frame = frame.rename(
            columns={
                time_column: "time",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Adj Close": "adj_close",
                "Volume": "volume",
            }
        )

        frame["time"] = pd.to_datetime(frame["time"], utc=True)
        frame = frame[["time", "open", "high", "low", "close", "volume"]]

        if timeframe in RESAMPLE_RULE_MAP:
            frame = self._resample(frame, RESAMPLE_RULE_MAP[timeframe])

        frame["tick_volume"] = pd.NA
        frame["real_volume"] = pd.NA
        frame["spread"] = pd.NA
        frame["symbol"] = symbol
        frame["timeframe"] = timeframe
        frame["data_source"] = self.source_name

        return frame.sort_values("time").tail(request.bars).reset_index(drop=True)

    @staticmethod
    def _resample(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
        resampled = (
            frame.set_index("time")
            .resample(rule, label="right", closed="right")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna(subset=["open", "high", "low", "close"])
            .reset_index()
        )
        return resampled


class MetaTrader5DataSource:
    source_name = "metatrader5"

    @staticmethod
    def _import_module():
        try:
            return importlib.import_module("MetaTrader5")
        except ImportError:
            return None

    def is_available(self) -> bool:
        return self._import_module() is not None

    def fetch(self, request: FetchRequest) -> pd.DataFrame:
        try:
            with MetaTrader5Client.from_env() as client:
                return client.copy_rates(request.symbol, request.timeframe, request.bars)
        except Mt5Error as exc:
            raise DataSourceError(str(exc)) from exc


def fetch_ohlcv(request: FetchRequest, source: str = "auto") -> pd.DataFrame:
    """Resolve the preferred market data source with automatic fallback."""
    if source not in {"auto", "mt5", "yfinance"}:
        raise ValueError("source muss 'auto', 'mt5' oder 'yfinance' sein.")

    if source == "yfinance":
        return YFinanceDataSource().fetch(request)

    if source == "mt5":
        return MetaTrader5DataSource().fetch(request)

    mt5_source = MetaTrader5DataSource()
    errors: list[str] = []

    if mt5_source.is_available():
        try:
            return mt5_source.fetch(request)
        except DataSourceError as exc:
            errors.append(str(exc))

    try:
        return YFinanceDataSource().fetch(request)
    except DataSourceError as exc:
        errors.append(str(exc))

    joined_errors = " | ".join(errors) if errors else "Keine Datenquelle verfuegbar."
    raise DataSourceError(joined_errors)
