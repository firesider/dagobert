from __future__ import annotations

import pandas as pd
import pytest

from trader.alpaca import AlpacaClient, AlpacaConnectionSettings, AlpacaError


def _stock_bars_frame() -> pd.DataFrame:
    timestamps = pd.date_range("2024-06-01", periods=5, freq="h", tz="UTC")
    index = pd.MultiIndex.from_product([["AAPL"], timestamps], names=["symbol", "timestamp"])
    return pd.DataFrame(
        {
            "open": [180.0, 180.5, 181.0, 181.4, 181.8],
            "high": [181.0, 181.2, 181.6, 181.9, 182.2],
            "low": [179.5, 180.1, 180.6, 181.0, 181.3],
            "close": [180.5, 181.0, 181.4, 181.8, 182.0],
            "volume": [1_000_000, 950_000, 1_100_000, 1_050_000, 980_000],
            "trade_count": [12_345, 11_990, 12_500, 12_200, 11_800],
            "vwap": [180.4, 181.0, 181.3, 181.7, 181.9],
        },
        index=index,
    )


def test_normalize_frame_emits_canonical_schema() -> None:
    raw = _stock_bars_frame()
    out = AlpacaClient._normalize_frame(raw, symbol="AAPL", timeframe="1h", bars=10)

    assert list(out.columns) == [
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
    assert out["data_source"].eq("alpaca").all()
    assert out["symbol"].eq("AAPL").all()
    assert out["timeframe"].eq("1h").all()
    assert out["tick_volume"].isna().all()
    assert out["spread"].isna().all()
    assert out["real_volume"].isna().all()
    assert str(out["time"].dt.tz) == "UTC"
    assert out["time"].is_monotonic_increasing
    assert len(out) == 5


def test_normalize_frame_truncates_to_bars() -> None:
    raw = _stock_bars_frame()
    out = AlpacaClient._normalize_frame(raw, symbol="AAPL", timeframe="1h", bars=3)
    assert len(out) == 3
    assert out["time"].is_monotonic_increasing


def test_normalize_frame_empty_raises_with_helpful_message() -> None:
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    with pytest.raises(AlpacaError, match="US-Tickers"):
        AlpacaClient._normalize_frame(empty, symbol="EURUSD", timeframe="1h", bars=10)


def test_copy_rates_routes_crypto_symbol_to_crypto_client() -> None:
    crypto_frame = _stock_bars_frame().rename(index={"AAPL": "BTC/USD"})
    crypto_frame.index = crypto_frame.index.set_levels(["BTC/USD"], level="symbol")

    captured: dict[str, object] = {}

    class FakeBarSet:
        def __init__(self, df: pd.DataFrame) -> None:
            self.df = df

    class FakeCryptoClient:
        def get_crypto_bars(self, request):
            captured["used"] = "crypto"
            captured["request"] = request
            return FakeBarSet(crypto_frame)

    class FakeStockClient:
        def get_stock_bars(self, request):
            captured["used"] = "stock"
            return FakeBarSet(_stock_bars_frame())

    client = AlpacaClient(
        settings=AlpacaConnectionSettings(api_key="k", api_secret="s"),
        stock_client=FakeStockClient(),
        crypto_client=FakeCryptoClient(),
    )
    client._build_request = lambda symbol, timeframe, bars, is_crypto: ("REQ", symbol, is_crypto)

    out = client.copy_rates("BTC/USD", "1h", 10)

    assert captured["used"] == "crypto"
    assert captured["request"] == ("REQ", "BTC/USD", True)
    assert out["symbol"].eq("BTC/USD").all()


def test_copy_rates_routes_stock_symbol_to_stock_client() -> None:
    captured: dict[str, object] = {}

    class FakeBarSet:
        df = _stock_bars_frame()

    class FakeStockClient:
        def get_stock_bars(self, request):
            captured["used"] = "stock"
            return FakeBarSet()

    client = AlpacaClient(
        settings=AlpacaConnectionSettings(api_key="k", api_secret="s"),
        stock_client=FakeStockClient(),
    )
    client._build_request = lambda symbol, timeframe, bars, is_crypto: None

    out = client.copy_rates("AAPL", "1h", 10)
    assert captured["used"] == "stock"
    assert out["data_source"].eq("alpaca").all()


def test_missing_credentials_raises_clear_error() -> None:
    client = AlpacaClient(settings=AlpacaConnectionSettings(api_key=None, api_secret=None))
    with pytest.raises(AlpacaError, match="ALPACA_API_KEY_ID"):
        client._get_stock_client()


def test_is_available_reflects_find_spec(monkeypatch) -> None:
    import importlib.util as util

    monkeypatch.setattr(util, "find_spec", lambda name: None)
    assert AlpacaClient.is_available() is False

    monkeypatch.setattr(util, "find_spec", lambda name: object())
    assert AlpacaClient.is_available() is True
