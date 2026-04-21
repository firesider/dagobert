from __future__ import annotations

import numpy as np
import pandas as pd

from trader.indicators import build_indicator_frame, build_latest_snapshot


def _sample_frame(with_volume: bool = True) -> pd.DataFrame:
    periods = 400
    time_index = pd.date_range("2024-01-01", periods=periods, freq="h", tz="UTC")
    base = 1.08 + np.linspace(0, 0.05, periods) + (np.sin(np.arange(periods) / 10) * 0.01)
    close = pd.Series(base)
    open_ = close.shift(1).fillna(close.iloc[0])
    high = np.maximum(open_, close) + 0.002
    low = np.minimum(open_, close) - 0.002

    frame = pd.DataFrame(
        {
            "time": time_index,
            "open": open_.to_numpy(),
            "high": high.to_numpy(),
            "low": low.to_numpy(),
            "close": close.to_numpy(),
            "volume": np.linspace(1000, 5000, periods) if with_volume else np.nan,
            "spread": np.full(periods, 2),
            "symbol": "EURUSD",
            "timeframe": "1h",
            "data_source": "test",
        }
    )
    return frame


def test_build_indicator_frame_adds_expected_columns() -> None:
    features = build_indicator_frame(_sample_frame())

    expected_columns = {
        "ema_20",
        "ema_50",
        "sma_50",
        "sma_200",
        "trend_macd",
        "trend_adx",
        "momentum_rsi",
        "volatility_atr",
        "pivot_point",
        "fib_618_20",
        "realized_vol_20",
        "trend_regime",
    }
    assert expected_columns.issubset(features.columns)
    assert pd.notna(features.iloc[-1]["momentum_rsi"])
    assert features.iloc[-1]["trend_regime"] in {"bullish", "bearish", "neutral"}


def test_build_indicator_frame_uses_proxy_volume_when_needed() -> None:
    features = build_indicator_frame(_sample_frame(with_volume=False))
    assert features["volume_is_proxy"].all()
    assert (features["analysis_volume"] > 0).all()


def test_build_latest_snapshot_returns_one_row_per_symbol() -> None:
    features = build_indicator_frame(_sample_frame())
    snapshot = build_latest_snapshot(features)
    assert len(snapshot) == 1
    assert snapshot.iloc[0]["symbol"] == "EURUSD"
