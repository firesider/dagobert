"""Signal generation based on engineered indicator frames."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

SUPPORTED_STRATEGIES = ("ema_rsi_pullback", "breakout")

REQUIRED_SIGNAL_COLUMNS = {
    "symbol",
    "time",
    "close",
    "ema_20",
    "ema_50",
    "trend_adx",
    "momentum_rsi",
    "rolling_high_20",
    "rolling_low_20",
    "atr_pct",
}


@dataclass(frozen=True)
class StrategyConfig:
    strategy: str = "ema_rsi_pullback"
    adx_threshold: float = 18.0
    long_rsi_floor: float = 52.0
    short_rsi_ceiling: float = 48.0
    pullback_tolerance: float = 0.0025
    breakout_lookback: int = 20


def build_signal_frame(
    features: pd.DataFrame,
    config: StrategyConfig | None = None,
) -> pd.DataFrame:
    strategy_config = config or StrategyConfig()
    strategy = validate_strategy_name(strategy_config.strategy)

    missing = REQUIRED_SIGNAL_COLUMNS.difference(features.columns)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Features fuer Signale fehlen: {missing_list}")

    frame = features.copy()
    frame = frame.sort_values(["symbol", "time"]).reset_index(drop=True)

    if strategy == "ema_rsi_pullback":
        signal = _ema_rsi_pullback_signal(frame, strategy_config)
    else:
        signal = _breakout_signal(frame, strategy_config)

    conviction = (
        ((frame["trend_adx"].fillna(0).clip(lower=0, upper=50) / 50.0) * 0.6)
        + ((frame["momentum_rsi"].fillna(50).sub(50).abs().clip(upper=25) / 25.0) * 0.4)
    ).clip(upper=1.0)

    suggested_stop = frame["atr_pct"].fillna(0.005).clip(lower=0.003, upper=0.03)
    suggested_take_profit = (suggested_stop * 2.0).clip(lower=0.006, upper=0.08)

    signal_frame = frame.copy()
    signal_frame["strategy_name"] = strategy
    signal_frame["signal"] = signal.astype("int64")
    signal_frame["signal_changed"] = signal_frame["signal"].ne(
        signal_frame.groupby("symbol")["signal"].shift(1).fillna(0)
    )
    signal_frame["signal_label"] = signal_frame["signal"].map(
        {
            -1: "short",
            0: "flat",
            1: "long",
        }
    )
    signal_frame["conviction_score"] = conviction.round(4)
    signal_frame["suggested_stop_loss_pct"] = suggested_stop.round(6)
    signal_frame["suggested_take_profit_pct"] = suggested_take_profit.round(6)
    return signal_frame


def latest_signals(signal_frame: pd.DataFrame) -> pd.DataFrame:
    latest = signal_frame.sort_values("time").groupby("symbol", as_index=False).tail(1)
    columns = [
        "time",
        "symbol",
        "strategy_name",
        "signal",
        "signal_label",
        "close",
        "momentum_rsi",
        "trend_adx",
        "conviction_score",
        "suggested_stop_loss_pct",
        "suggested_take_profit_pct",
        "data_source",
    ]
    available = [column for column in columns if column in latest.columns]
    return latest[available].sort_values("symbol").reset_index(drop=True)


def validate_strategy_name(strategy: str) -> str:
    if strategy not in SUPPORTED_STRATEGIES:
        supported = ", ".join(SUPPORTED_STRATEGIES)
        raise ValueError(f"Unbekannte Strategie '{strategy}'. Erlaubt: {supported}")
    return strategy


def _ema_rsi_pullback_signal(frame: pd.DataFrame, config: StrategyConfig) -> pd.Series:
    bullish_trend = (frame["ema_20"] > frame["ema_50"]) & (frame["trend_adx"] >= config.adx_threshold)
    bearish_trend = (frame["ema_20"] < frame["ema_50"]) & (frame["trend_adx"] >= config.adx_threshold)

    near_ema = ((frame["close"] / frame["ema_20"]) - 1).abs() <= config.pullback_tolerance

    long_signal = bullish_trend & near_ema & frame["momentum_rsi"].between(config.long_rsi_floor, 70)
    short_signal = bearish_trend & near_ema & frame["momentum_rsi"].between(30, config.short_rsi_ceiling)

    return pd.Series(
        np.select([long_signal, short_signal], [1, -1], default=0),
        index=frame.index,
        dtype="int64",
    )


def _breakout_signal(frame: pd.DataFrame, config: StrategyConfig) -> pd.Series:
    if {"high", "low"}.issubset(frame.columns):
        lookback_high = frame.groupby("symbol")["high"].transform(
            lambda series: series.rolling(config.breakout_lookback).max()
        ).shift(1)
        lookback_low = frame.groupby("symbol")["low"].transform(
            lambda series: series.rolling(config.breakout_lookback).min()
        ).shift(1)
    else:
        lookback_high = frame.groupby("symbol")["rolling_high_20"].shift(1)
        lookback_low = frame.groupby("symbol")["rolling_low_20"].shift(1)
    adx_filter = frame["trend_adx"] >= config.adx_threshold

    long_signal = adx_filter & (frame["close"] > lookback_high)
    short_signal = adx_filter & (frame["close"] < lookback_low)

    return pd.Series(
        np.select([long_signal, short_signal], [1, -1], default=0),
        index=frame.index,
        dtype="int64",
    )
