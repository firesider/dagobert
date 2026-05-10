"""Market data adapter for Alpaca."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trader.alpaca import AlpacaClient, AlpacaError


class DataSourceError(RuntimeError):
    """Raised when a market data source cannot return valid data."""


@dataclass(frozen=True)
class FetchRequest:
    symbol: str
    timeframe: str
    bars: int


class AlpacaDataSource:
    source_name = "alpaca"

    def fetch(self, request: FetchRequest) -> pd.DataFrame:
        try:
            client = AlpacaClient.from_env()
            return client.copy_rates(request.symbol, request.timeframe, request.bars)
        except AlpacaError as exc:
            raise DataSourceError(str(exc)) from exc


def fetch_ohlcv(request: FetchRequest) -> pd.DataFrame:
    """Fetch OHLCV bars from Alpaca for the given request."""
    return AlpacaDataSource().fetch(request)
