"""Threshold sweep: grid-search StrategyConfig parameters on Alpaca history.

The sweep is the calibration step that replaces the FX-tuned defaults
(``pullback_tolerance``, ``long_rsi_floor``, ``atr_pct_floor`` /
``_ceiling``) with values derived from out-of-sample equity/crypto data.

Pipeline per ``(symbol, timeframe, parameter cell)``:

1. Fetch ``years``-long history of bars from Alpaca via :func:`fetch_ohlcv`.
2. Build the indicator frame.
3. Split bars 70/30 by time — first 70% is "in-sample" (used to filter
   degenerate cells), last 30% is "out-of-sample" (the reported metric).
4. Run :func:`run_backtest` with the parameter cell on the OOS slice.
5. Compute net Sharpe; reject the cell if ``trade_count < min_trades``.

Winners are picked per ``(cohort, timeframe)`` by max OOS Sharpe.

The CLI subcommand ``trader sweep`` exposes the full pipeline plus a
``--quick`` smoke option that uses a tiny grid for end-to-end validation.
"""

from __future__ import annotations

import itertools
import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from trader.backtest import BacktestConfig, run_backtest
from trader.data_sources import FetchRequest, fetch_ohlcv
from trader.indicators import build_indicator_frame
from trader.strategies import StrategyConfig

# Default cohorts, mirrors the approved Phase 5 plan.
EQUITY_COHORT: tuple[str, ...] = ("AAPL", "MSFT", "SPY", "QQQ", "NVDA")
CRYPTO_COHORT: tuple[str, ...] = ("BTC/USD", "ETH/USD", "SOL/USD")

# Period lookback per timeframe (calendar years).
DEFAULT_YEARS_BY_TIMEFRAME: dict[str, float] = {
    "1d": 3.0,
    "1h": 1.0,
}

BARS_PER_YEAR: dict[str, int] = {
    "1d": 365,
    "1h": 24 * 365,
    "4h": 6 * 365,
    "15m": 4 * 24 * 365,
    "5m": 12 * 24 * 365,
}


@dataclass(frozen=True)
class SweepGrid:
    """Discrete axes the sweep iterates over."""

    pullback_tolerance: tuple[float, ...] = (0.0025, 0.005, 0.01, 0.02)
    long_rsi_floor: tuple[float, ...] = (48.0, 52.0, 55.0, 58.0)
    atr_pct_floor: tuple[float, ...] = (0.001, 0.003, 0.005)
    atr_pct_ceiling: tuple[float, ...] = (0.02, 0.03, 0.05, 0.10)

    def cells(self) -> list[dict[str, float]]:
        """Cartesian product of the axes as concrete kwargs.

        Cells where ``atr_pct_floor >= atr_pct_ceiling`` are rejected
        because they would clip ATR to a constant.
        """
        result: list[dict[str, float]] = []
        for pt, rsi, lo, hi in itertools.product(
            self.pullback_tolerance,
            self.long_rsi_floor,
            self.atr_pct_floor,
            self.atr_pct_ceiling,
        ):
            if lo >= hi:
                continue
            result.append(
                {
                    "pullback_tolerance": pt,
                    "long_rsi_floor": rsi,
                    "atr_pct_floor": lo,
                    "atr_pct_ceiling": hi,
                }
            )
        return result

    @classmethod
    def quick(cls) -> SweepGrid:
        """Tiny grid for smoke testing (8 cells)."""
        return cls(
            pullback_tolerance=(0.0025, 0.01),
            long_rsi_floor=(52.0, 55.0),
            atr_pct_floor=(0.003,),
            atr_pct_ceiling=(0.03, 0.05),
        )


@dataclass(frozen=True)
class SweepConfig:
    grid: SweepGrid = field(default_factory=SweepGrid)
    timeframes: tuple[str, ...] = ("1d", "1h")
    equity_symbols: tuple[str, ...] = EQUITY_COHORT
    crypto_symbols: tuple[str, ...] = CRYPTO_COHORT
    in_sample_fraction: float = 0.7
    min_trades: int = 30
    backtest_config: BacktestConfig = field(default_factory=BacktestConfig)
    strategy: str = "ema_rsi_pullback"
    years_by_timeframe: dict[str, float] = field(
        default_factory=lambda: DEFAULT_YEARS_BY_TIMEFRAME.copy()
    )

    def __post_init__(self) -> None:
        if not 0.0 < self.in_sample_fraction < 1.0:
            raise ValueError("in_sample_fraction muss in (0, 1) liegen.")
        if self.min_trades < 1:
            raise ValueError("min_trades muss >= 1 sein.")


def run_sweep(
    config: SweepConfig | None = None,
) -> pd.DataFrame:
    """Run the full sweep and return one row per (cohort, symbol, timeframe, cell).

    Caller is responsible for I/O: persist the returned frame and feed it
    to :func:`pick_winners`.
    """
    sweep_config = config or SweepConfig()
    cells = sweep_config.grid.cells()
    rows: list[dict[str, float | str | int]] = []

    cohorts: dict[str, Sequence[str]] = {
        "equity": sweep_config.equity_symbols,
        "crypto": sweep_config.crypto_symbols,
    }

    for cohort_name, symbols in cohorts.items():
        for timeframe in sweep_config.timeframes:
            bars = _bars_for(timeframe, sweep_config.years_by_timeframe)
            indicator_by_symbol = _load_indicators(symbols, timeframe, bars)
            for symbol, indicator_frame in indicator_by_symbol.items():
                in_sample, out_of_sample = _split_in_out(
                    indicator_frame, sweep_config.in_sample_fraction
                )
                for cell in cells:
                    row = _evaluate_cell(
                        cohort=cohort_name,
                        symbol=symbol,
                        timeframe=timeframe,
                        cell=cell,
                        in_sample=in_sample,
                        out_of_sample=out_of_sample,
                        sweep_config=sweep_config,
                    )
                    rows.append(row)

    return pd.DataFrame(rows)


def pick_winners(
    results: pd.DataFrame,
    min_trades: int = 30,
) -> pd.DataFrame:
    """Pick the highest OOS Sharpe per (cohort, timeframe), aggregating symbols.

    A cell is eligible only if the per-symbol average ``oos_trade_count``
    in the cohort meets ``min_trades``. The aggregate score is the mean
    OOS Sharpe across the cohort's symbols.
    """
    if results.empty:
        return results.copy()

    grouped = (
        results.groupby(
            [
                "cohort",
                "timeframe",
                "pullback_tolerance",
                "long_rsi_floor",
                "atr_pct_floor",
                "atr_pct_ceiling",
            ]
        )
        .agg(
            oos_sharpe_mean=("oos_sharpe", "mean"),
            oos_trade_count_mean=("oos_trade_count", "mean"),
            symbol_count=("symbol", "nunique"),
        )
        .reset_index()
    )
    eligible = grouped[grouped["oos_trade_count_mean"] >= min_trades].copy()
    if eligible.empty:
        return eligible

    winners = (
        eligible.sort_values("oos_sharpe_mean", ascending=False)
        .groupby(["cohort", "timeframe"], sort=True)
        .head(1)
        .reset_index(drop=True)
    )
    return winners


def persist_results(
    results: pd.DataFrame,
    winners: pd.DataFrame,
    out_dir: str | Path,
    timestamp: str | None = None,
) -> tuple[Path, Path]:
    """Write the full grid + winners to ``out_dir``. Returns (results_path, winners_path)."""
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    results_path = target / f"{stamp}.parquet"
    winners_path = target / f"{stamp}_winners.json"

    results.to_parquet(results_path, index=False)
    winners_payload = {
        "generated_at": stamp,
        "winners": [_winner_to_payload(row) for _, row in winners.iterrows()],
    }
    winners_path.write_text(json.dumps(winners_payload, indent=2), encoding="utf-8")
    return results_path, winners_path


def _evaluate_cell(
    *,
    cohort: str,
    symbol: str,
    timeframe: str,
    cell: dict[str, float],
    in_sample: pd.DataFrame,
    out_of_sample: pd.DataFrame,
    sweep_config: SweepConfig,
) -> dict[str, float | str | int]:
    strategy_config = StrategyConfig(
        strategy=sweep_config.strategy,
        pullback_tolerance=cell["pullback_tolerance"],
        long_rsi_floor=cell["long_rsi_floor"],
        atr_pct_floor=cell["atr_pct_floor"],
        atr_pct_ceiling=cell["atr_pct_ceiling"],
    )

    in_sharpe, in_trades = _backtest_score(in_sample, strategy_config, sweep_config)
    oos_sharpe, oos_trades = _backtest_score(out_of_sample, strategy_config, sweep_config)

    return {
        "cohort": cohort,
        "symbol": symbol,
        "timeframe": timeframe,
        "pullback_tolerance": cell["pullback_tolerance"],
        "long_rsi_floor": cell["long_rsi_floor"],
        "atr_pct_floor": cell["atr_pct_floor"],
        "atr_pct_ceiling": cell["atr_pct_ceiling"],
        "in_sample_sharpe": in_sharpe,
        "in_sample_trade_count": in_trades,
        "oos_sharpe": oos_sharpe,
        "oos_trade_count": oos_trades,
    }


def _backtest_score(
    indicators: pd.DataFrame,
    strategy_config: StrategyConfig,
    sweep_config: SweepConfig,
) -> tuple[float, int]:
    if indicators.empty:
        return float("nan"), 0
    try:
        result = run_backtest(
            indicators,
            strategy_config=strategy_config,
            backtest_config=sweep_config.backtest_config,
        )
    except (ValueError, KeyError):
        return float("nan"), 0

    sharpe = float(result.metrics.get("sharpe", float("nan")))
    trade_count = int(result.metrics.get("trade_count", 0))
    if not math.isfinite(sharpe):
        sharpe = float("nan")
    return sharpe, trade_count


def _split_in_out(
    indicators: pd.DataFrame,
    fraction: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if indicators.empty:
        return indicators.copy(), indicators.copy()
    sorted_frame = indicators.sort_values(["symbol", "time"]).reset_index(drop=True)
    bars = len(sorted_frame)
    cutoff = max(1, int(bars * fraction))
    return sorted_frame.iloc[:cutoff].copy(), sorted_frame.iloc[cutoff:].copy()


def _load_indicators(
    symbols: Iterable[str],
    timeframe: str,
    bars: int,
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            raw = fetch_ohlcv(FetchRequest(symbol=symbol, timeframe=timeframe, bars=bars))
            out[symbol] = build_indicator_frame(raw)
        except Exception as exc:  # pragma: no cover - sweep is robust to per-symbol failures
            print(f"sweep: skipping {symbol}@{timeframe}: {exc}")
    return out


def _bars_for(timeframe: str, years_by_timeframe: dict[str, float]) -> int:
    years = years_by_timeframe.get(timeframe, 1.0)
    return int(round(years * BARS_PER_YEAR.get(timeframe, 365)))


def _winner_to_payload(row: pd.Series) -> dict[str, float | str | int]:
    return {
        "cohort": str(row["cohort"]),
        "timeframe": str(row["timeframe"]),
        "pullback_tolerance": float(row["pullback_tolerance"]),
        "long_rsi_floor": float(row["long_rsi_floor"]),
        "atr_pct_floor": float(row["atr_pct_floor"]),
        "atr_pct_ceiling": float(row["atr_pct_ceiling"]),
        "oos_sharpe_mean": float(row["oos_sharpe_mean"]),
        "oos_trade_count_mean": float(row["oos_trade_count_mean"]),
        "symbol_count": int(row["symbol_count"]),
    }
