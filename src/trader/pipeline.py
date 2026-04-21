"""High-level workflow for fetching, enriching, and exporting Forex datasets."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from trader.config import DEFAULT_FOREX_SYMBOLS
from trader.data_sources import FetchRequest, fetch_ohlcv
from trader.indicators import build_indicator_frame, build_latest_snapshot


def build_forex_dataset(
    symbols: Iterable[str] | None = None,
    timeframe: str = "1h",
    bars: int = 1500,
    source: str = "auto",
) -> pd.DataFrame:
    requested_symbols = list(symbols or DEFAULT_FOREX_SYMBOLS)
    frames: list[pd.DataFrame] = []
    failures: list[str] = []

    for symbol in requested_symbols:
        try:
            raw = fetch_ohlcv(FetchRequest(symbol=symbol, timeframe=timeframe, bars=bars), source=source)
            features = build_indicator_frame(raw)
            frames.append(features)
        except Exception as exc:  # pragma: no cover - keeps CLI robust across mixed data sources
            failures.append(f"{symbol}: {exc}")

    if not frames:
        joined = " | ".join(failures) if failures else "Unbekannter Fehler."
        raise RuntimeError(f"Es konnten keine Forex-Daten aufgebaut werden. {joined}")

    dataset = pd.concat(frames, ignore_index=True)
    dataset = dataset.sort_values(["symbol", "time"]).reset_index(drop=True)
    dataset.attrs["failures"] = failures
    return dataset


def save_frame(frame: pd.DataFrame, output_path: str | Path) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.suffix == ".parquet":
        frame.to_parquet(target, index=False)
    elif target.suffix == ".csv":
        frame.to_csv(target, index=False)
    elif target.suffix == ".json":
        frame.to_json(target, orient="records", date_format="iso")
    else:
        raise ValueError("Output-Datei muss .parquet, .csv oder .json enden.")

    return target


def save_latest_snapshot(features: pd.DataFrame, output_path: str | Path) -> Path:
    target = Path(output_path)
    snapshot = build_latest_snapshot(features)
    return save_frame(snapshot, target)
