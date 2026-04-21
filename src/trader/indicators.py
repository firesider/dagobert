"""Indicator engineering for Forex OHLCV data."""

from __future__ import annotations

import numpy as np
import pandas as pd
from ta import add_all_ta_features

REQUIRED_COLUMNS = {"time", "open", "high", "low", "close"}

KEY_SNAPSHOT_COLUMNS = [
    "time",
    "symbol",
    "timeframe",
    "data_source",
    "close",
    "spread",
    "ema_20",
    "ema_50",
    "sma_50",
    "sma_200",
    "trend_macd",
    "trend_macd_signal",
    "trend_adx",
    "momentum_rsi",
    "momentum_stoch_rsi",
    "momentum_wr",
    "volatility_atr",
    "atr_pct",
    "volatility_bbw",
    "volatility_dcp",
    "volume_adi",
    "volume_obv",
    "pivot_point",
    "pivot_support_1",
    "pivot_resistance_1",
    "fib_618_20",
    "realized_vol_20",
    "close_zscore_20",
    "trend_regime",
    "trend_strength_regime",
    "volume_is_proxy",
]


def build_indicator_frame(raw_frame: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS.difference(raw_frame.columns)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Input-DataFrame enthaelt nicht alle Pflichtspalten: {missing_list}")

    frame = raw_frame.copy()
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    frame = frame.sort_values("time").drop_duplicates(subset=["time"]).reset_index(drop=True)

    numeric_columns = ["open", "high", "low", "close", "volume", "tick_volume", "spread", "real_volume"]
    for column in numeric_columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    if "volume" not in frame.columns:
        frame["volume"] = np.nan

    frame = _attach_volume_proxy(frame)

    enriched = add_all_ta_features(
        frame,
        open="open",
        high="high",
        low="low",
        close="close",
        volume="analysis_volume",
        fillna=False,
    )
    enriched = enriched.copy()

    enriched = _add_price_action_features(enriched)
    enriched = _add_support_resistance_features(enriched)
    enriched = _add_trend_regimes(enriched)

    return enriched


def build_latest_snapshot(features: pd.DataFrame) -> pd.DataFrame:
    latest = features.sort_values("time").groupby("symbol", as_index=False).tail(1)
    available_columns = [column for column in KEY_SNAPSHOT_COLUMNS if column in latest.columns]
    return latest[available_columns].sort_values("symbol").reset_index(drop=True)


def _attach_volume_proxy(frame: pd.DataFrame) -> pd.DataFrame:
    preferred_volume = pd.Series(np.nan, index=frame.index, dtype="float64")

    if "tick_volume" in frame.columns and frame["tick_volume"].notna().any():
        preferred_volume = frame["tick_volume"].astype("float64")
    elif "volume" in frame.columns and frame["volume"].notna().any():
        preferred_volume = frame["volume"].astype("float64")

    has_real_volume = preferred_volume.fillna(0).sum() > 0

    if has_real_volume:
        floor = preferred_volume[preferred_volume > 0].min()
        floor = float(floor) if pd.notna(floor) else 1.0
        frame["analysis_volume"] = preferred_volume.fillna(floor).clip(lower=floor)
        frame["volume_is_proxy"] = False
        return frame

    close_safe = frame["close"].replace(0, np.nan)
    range_component = ((frame["high"] - frame["low"]).abs() / close_safe).fillna(0)
    return_component = frame["close"].pct_change().abs().fillna(0)
    proxy = ((range_component + return_component) * 1_000_000).clip(lower=1.0)

    frame["analysis_volume"] = proxy
    frame["volume_is_proxy"] = True
    return frame


def _add_price_action_features(frame: pd.DataFrame) -> pd.DataFrame:
    close_safe = frame["close"].replace(0, np.nan)
    body = frame["close"] - frame["open"]
    high_low_range = frame["high"] - frame["low"]
    rolling_mean_20 = frame["close"].rolling(20).mean()
    rolling_std_20 = frame["close"].rolling(20).std()
    rolling_high_20 = frame["high"].rolling(20).max()
    rolling_low_20 = frame["low"].rolling(20).min()

    feature_block = pd.DataFrame(
        {
            "return_1": frame["close"].pct_change(),
            "log_return_1": np.log(frame["close"] / frame["close"].shift(1)),
            "range_pct": high_low_range / close_safe,
            "body_pct": body.abs() / close_safe,
            "upper_wick_pct": (frame["high"] - frame[["open", "close"]].max(axis=1)) / close_safe,
            "lower_wick_pct": (frame[["open", "close"]].min(axis=1) - frame["low"]) / close_safe,
            "ema_20": frame["close"].ewm(span=20, adjust=False).mean(),
            "ema_50": frame["close"].ewm(span=50, adjust=False).mean(),
            "sma_50": frame["close"].rolling(50).mean(),
            "sma_200": frame["close"].rolling(200).mean(),
            "atr_pct": frame["volatility_atr"] / close_safe,
            "close_zscore_20": (frame["close"] - rolling_mean_20) / rolling_std_20.replace(0, np.nan),
            "rolling_high_20": rolling_high_20,
            "rolling_low_20": rolling_low_20,
        },
        index=frame.index,
    )
    feature_block["ema_20_over_50"] = (feature_block["ema_20"] / feature_block["ema_50"]) - 1
    feature_block["realized_vol_20"] = feature_block["log_return_1"].rolling(20).std() * np.sqrt(20)
    feature_block["realized_vol_60"] = feature_block["log_return_1"].rolling(60).std() * np.sqrt(60)
    feature_block["distance_to_20_high_pct"] = (frame["close"] / rolling_high_20) - 1
    feature_block["distance_to_20_low_pct"] = (frame["close"] / rolling_low_20) - 1

    return pd.concat([frame, feature_block], axis=1)


def _add_support_resistance_features(frame: pd.DataFrame) -> pd.DataFrame:
    prior_high = frame["high"].shift(1)
    prior_low = frame["low"].shift(1)
    prior_close = frame["close"].shift(1)
    prior_range = prior_high - prior_low

    pivot = (prior_high + prior_low + prior_close) / 3
    rolling_range = (frame["rolling_high_20"] - frame["rolling_low_20"]).replace(0, np.nan)

    feature_block = pd.DataFrame(
        {
            "pivot_point": pivot,
            "pivot_support_1": (2 * pivot) - prior_high,
            "pivot_resistance_1": (2 * pivot) - prior_low,
            "pivot_support_2": pivot - prior_range,
            "pivot_resistance_2": pivot + prior_range,
            "fib_236_20": frame["rolling_high_20"] - (rolling_range * 0.236),
            "fib_382_20": frame["rolling_high_20"] - (rolling_range * 0.382),
            "fib_500_20": frame["rolling_high_20"] - (rolling_range * 0.500),
            "fib_618_20": frame["rolling_high_20"] - (rolling_range * 0.618),
        },
        index=frame.index,
    )

    return pd.concat([frame, feature_block], axis=1)


def _add_trend_regimes(frame: pd.DataFrame) -> pd.DataFrame:
    feature_block = pd.DataFrame(
        {
            "trend_regime": np.select(
                [
                    frame["ema_20"] > frame["ema_50"],
                    frame["ema_20"] < frame["ema_50"],
                ],
                ["bullish", "bearish"],
                default="neutral",
            ),
            "trend_strength_regime": np.where(frame["trend_adx"] >= 25, "trending", "ranging"),
        },
        index=frame.index,
    )
    return pd.concat([frame, feature_block], axis=1)
