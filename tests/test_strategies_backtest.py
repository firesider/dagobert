from __future__ import annotations

import pandas as pd

from trader.backtest import BacktestConfig, run_backtest
from trader.strategies import StrategyConfig, build_signal_frame, latest_signals


def _feature_frame() -> pd.DataFrame:
    time_index = pd.date_range("2024-01-01", periods=12, freq="h", tz="UTC")
    close = [100.00, 100.10, 100.20, 100.15, 100.30, 100.25, 99.90, 99.80, 99.70, 99.65, 99.55, 99.50]
    ema_20 = [100.00, 100.08, 100.18, 100.12, 100.28, 100.22, 99.92, 99.82, 99.72, 99.66, 99.57, 99.51]
    ema_50 = [99.80, 99.90, 100.00, 100.02, 100.05, 100.10, 100.05, 99.98, 99.90, 99.85, 99.80, 99.75]
    rsi = [55, 57, 60, 58, 61, 59, 44, 42, 40, 38, 37, 35]

    frame = pd.DataFrame(
        {
            "time": time_index,
            "symbol": "EURUSD",
            "timeframe": "1h",
            "data_source": "test",
            "close": close,
            "open": close,
            "high": [value + 0.15 for value in close],
            "low": [value - 0.15 for value in close],
            "ema_20": ema_20,
            "ema_50": ema_50,
            "trend_adx": [25] * len(time_index),
            "momentum_rsi": rsi,
            "rolling_high_20": pd.Series(close).rolling(3, min_periods=1).max().tolist(),
            "rolling_low_20": pd.Series(close).rolling(3, min_periods=1).min().tolist(),
            "atr_pct": [0.005] * len(time_index),
        }
    )
    return frame


def test_build_signal_frame_adds_expected_signal_columns() -> None:
    signal_frame = build_signal_frame(_feature_frame(), StrategyConfig(strategy="ema_rsi_pullback"))

    assert {"signal", "signal_label", "conviction_score", "suggested_stop_loss_pct"}.issubset(
        signal_frame.columns
    )
    assert set(signal_frame["signal"].unique()).issubset({-1, 0, 1})
    assert signal_frame["signal"].abs().sum() > 0


def test_latest_signals_returns_one_row_per_symbol() -> None:
    signal_frame = build_signal_frame(_feature_frame())
    latest = latest_signals(signal_frame)
    assert len(latest) == 1
    assert latest.iloc[0]["symbol"] == "EURUSD"


def test_run_backtest_returns_portfolio_curve_and_trade_log() -> None:
    result = run_backtest(
        _feature_frame(),
        strategy_config=StrategyConfig(strategy="ema_rsi_pullback"),
        backtest_config=BacktestConfig(initial_capital=10_000, risk_per_trade=0.01, stop_loss_pct=0.005),
    )

    assert "PORTFOLIO" in set(result.equity_curve["symbol"])
    assert result.metrics["trade_count"] >= 1
    assert "sharpe" in result.metrics
    assert not result.trades.empty
