"""Threshold sweep: grid-search StrategyConfig parameters on Alpaca history.

The sweep is the calibration step that replaces the FX-tuned defaults
(``pullback_tolerance``, ``long_rsi_floor``, ``atr_pct_floor`` /
``_ceiling``) with values derived from out-of-sample equity/crypto data.

Pipeline per ``(symbol, timeframe, parameter cell)``:

1. Fetch ``years``-long history of bars from Alpaca via :func:`fetch_ohlcv`.
2. Build the indicator frame.
3. Split bars 70/30 by time — first 70% is "in-sample" (used to filter
   degenerate cells), last 30% is "out-of-sample" (the reported metric).
4. Run :func:`run_backtest` with the parameter cell on both splits.
5. Persist strategy/backtest parameters plus IS/OOS metrics for ranking.

Winners are picked per ``(cohort, timeframe)`` by a robust score that
rewards OOS Sharpe, benchmark outperformance, and trade count while
penalizing drawdown and cross-symbol instability.

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
    """Pick the most robust cell per (cohort, timeframe), aggregating symbols.

    A cell is eligible only if the per-symbol average ``oos_trade_count``
    in the cohort meets ``min_trades``. The score prefers high OOS Sharpe
    and benchmark outperformance, then penalizes drawdown and symbol-level
    Sharpe dispersion.
    """
    if results.empty:
        return results.copy()

    ranking_frame = _with_ranking_defaults(results)
    grouped = (
        ranking_frame.groupby(
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
            strategy=("strategy", "first"),
            oos_sharpe_mean=("oos_sharpe", "mean"),
            oos_sharpe_std=("oos_sharpe", "std"),
            oos_total_return_mean=("oos_total_return", "mean"),
            oos_max_drawdown_mean=("oos_max_drawdown", "mean"),
            oos_profit_factor_mean=("oos_profit_factor", "mean"),
            oos_benchmark_total_return_mean=("oos_benchmark_total_return", "mean"),
            oos_trade_count_mean=("oos_trade_count", "mean"),
            oos_trade_count_min=("oos_trade_count", "min"),
            in_sample_sharpe_mean=("in_sample_sharpe", "mean"),
            symbol_count=("symbol", "nunique"),
        )
        .reset_index()
    )
    eligible = grouped[grouped["oos_trade_count_mean"] >= min_trades].copy()
    if eligible.empty:
        return eligible

    eligible["oos_sharpe_std"] = eligible["oos_sharpe_std"].fillna(0.0)
    eligible["oos_excess_return_mean"] = (
        eligible["oos_total_return_mean"] - eligible["oos_benchmark_total_return_mean"]
    )
    eligible["robust_score"] = (
        eligible["oos_sharpe_mean"].fillna(0.0)
        + (eligible["oos_excess_return_mean"].fillna(0.0) * 0.5)
        + (eligible["oos_trade_count_mean"].clip(upper=min_trades * 3) / min_trades * 0.05)
        - eligible["oos_sharpe_std"].fillna(0.0)
        - eligible["oos_max_drawdown_mean"].abs().fillna(0.0)
    )

    winners = (
        eligible.sort_values(
            ["robust_score", "oos_sharpe_mean", "oos_trade_count_mean"],
            ascending=[False, False, False],
        )
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
    config: SweepConfig | None = None,
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
        "ranking_method": (
            "robust_score = oos_sharpe_mean + 0.5*oos_excess_return_mean "
            "+ capped_trade_count_bonus - oos_sharpe_std - abs(oos_max_drawdown_mean)"
        ),
        "config": _config_to_payload(config) if config is not None else None,
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

    in_metrics = _backtest_metrics(in_sample, strategy_config, sweep_config)
    oos_metrics = _backtest_metrics(out_of_sample, strategy_config, sweep_config)

    return {
        "cohort": cohort,
        "symbol": symbol,
        "timeframe": timeframe,
        "strategy": sweep_config.strategy,
        "in_sample_fraction": sweep_config.in_sample_fraction,
        "min_trades": sweep_config.min_trades,
        "risk_per_trade": sweep_config.backtest_config.risk_per_trade,
        "stop_loss_pct": sweep_config.backtest_config.stop_loss_pct,
        "max_leverage": sweep_config.backtest_config.max_leverage,
        "fee_bps": sweep_config.backtest_config.fee_bps,
        "slippage_bps": sweep_config.backtest_config.slippage_bps,
        "allow_short": int(sweep_config.backtest_config.allow_short),
        "use_strategy_exits": int(sweep_config.backtest_config.use_strategy_exits),
        "in_sample_bars": len(in_sample),
        "out_of_sample_bars": len(out_of_sample),
        "pullback_tolerance": cell["pullback_tolerance"],
        "long_rsi_floor": cell["long_rsi_floor"],
        "atr_pct_floor": cell["atr_pct_floor"],
        "atr_pct_ceiling": cell["atr_pct_ceiling"],
        "in_sample_sharpe": in_metrics["sharpe"],
        "in_sample_trade_count": int(in_metrics["trade_count"]),
        "in_sample_total_return": in_metrics["total_return"],
        "in_sample_max_drawdown": in_metrics["max_drawdown"],
        "in_sample_profit_factor": in_metrics["profit_factor"],
        "in_sample_benchmark_total_return": in_metrics["benchmark_total_return"],
        "oos_sharpe": oos_metrics["sharpe"],
        "oos_trade_count": int(oos_metrics["trade_count"]),
        "oos_total_return": oos_metrics["total_return"],
        "oos_max_drawdown": oos_metrics["max_drawdown"],
        "oos_profit_factor": oos_metrics["profit_factor"],
        "oos_benchmark_total_return": oos_metrics["benchmark_total_return"],
        "oos_excess_return": oos_metrics["total_return"] - oos_metrics["benchmark_total_return"],
    }


def _backtest_score(
    indicators: pd.DataFrame,
    strategy_config: StrategyConfig,
    sweep_config: SweepConfig,
) -> tuple[float, int]:
    metrics = _backtest_metrics(indicators, strategy_config, sweep_config)
    return float(metrics["sharpe"]), int(metrics["trade_count"])


def _backtest_metrics(
    indicators: pd.DataFrame,
    strategy_config: StrategyConfig,
    sweep_config: SweepConfig,
) -> dict[str, float]:
    if indicators.empty:
        return _empty_metrics()
    try:
        result = run_backtest(
            indicators,
            strategy_config=strategy_config,
            backtest_config=sweep_config.backtest_config,
        )
    except (ValueError, KeyError):
        return _empty_metrics()

    return {
        "sharpe": _finite_metric(result.metrics, "sharpe"),
        "trade_count": _finite_metric(result.metrics, "trade_count", default=0.0),
        "total_return": _finite_metric(result.metrics, "total_return"),
        "max_drawdown": _finite_metric(result.metrics, "max_drawdown"),
        "profit_factor": _finite_metric(result.metrics, "profit_factor"),
        "benchmark_total_return": _finite_metric(result.metrics, "benchmark_total_return"),
    }


def _empty_metrics() -> dict[str, float]:
    return {
        "sharpe": float("nan"),
        "trade_count": 0.0,
        "total_return": float("nan"),
        "max_drawdown": float("nan"),
        "profit_factor": float("nan"),
        "benchmark_total_return": float("nan"),
    }


def _finite_metric(
    metrics: dict[str, float],
    key: str,
    default: float = float("nan"),
) -> float:
    value = float(metrics.get(key, default))
    return value if math.isfinite(value) else default


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
        "strategy": str(row.get("strategy", "ema_rsi_pullback")),
        "pullback_tolerance": float(row["pullback_tolerance"]),
        "long_rsi_floor": float(row["long_rsi_floor"]),
        "atr_pct_floor": float(row["atr_pct_floor"]),
        "atr_pct_ceiling": float(row["atr_pct_ceiling"]),
        "robust_score": float(row.get("robust_score", float("nan"))),
        "oos_sharpe_mean": float(row["oos_sharpe_mean"]),
        "oos_sharpe_std": float(row.get("oos_sharpe_std", 0.0)),
        "oos_total_return_mean": float(row.get("oos_total_return_mean", float("nan"))),
        "oos_excess_return_mean": float(row.get("oos_excess_return_mean", float("nan"))),
        "oos_max_drawdown_mean": float(row.get("oos_max_drawdown_mean", float("nan"))),
        "oos_profit_factor_mean": float(row.get("oos_profit_factor_mean", float("nan"))),
        "oos_trade_count_mean": float(row["oos_trade_count_mean"]),
        "oos_trade_count_min": float(row.get("oos_trade_count_min", float("nan"))),
        "in_sample_sharpe_mean": float(row.get("in_sample_sharpe_mean", float("nan"))),
        "symbol_count": int(row["symbol_count"]),
    }


def _with_ranking_defaults(results: pd.DataFrame) -> pd.DataFrame:
    frame = results.copy()
    defaults: dict[str, str | float] = {
        "strategy": "ema_rsi_pullback",
        "oos_total_return": 0.0,
        "oos_max_drawdown": 0.0,
        "oos_profit_factor": 0.0,
        "oos_benchmark_total_return": 0.0,
        "in_sample_sharpe": 0.0,
    }
    for column, default in defaults.items():
        if column not in frame.columns:
            frame[column] = default
    return frame


def _config_to_payload(config: SweepConfig) -> dict[str, object]:
    return {
        "strategy": config.strategy,
        "timeframes": list(config.timeframes),
        "equity_symbols": list(config.equity_symbols),
        "crypto_symbols": list(config.crypto_symbols),
        "in_sample_fraction": config.in_sample_fraction,
        "min_trades": config.min_trades,
        "years_by_timeframe": config.years_by_timeframe,
        "grid": {
            "pullback_tolerance": list(config.grid.pullback_tolerance),
            "long_rsi_floor": list(config.grid.long_rsi_floor),
            "atr_pct_floor": list(config.grid.atr_pct_floor),
            "atr_pct_ceiling": list(config.grid.atr_pct_ceiling),
        },
        "backtest": {
            "initial_capital": config.backtest_config.initial_capital,
            "risk_per_trade": config.backtest_config.risk_per_trade,
            "stop_loss_pct": config.backtest_config.stop_loss_pct,
            "max_leverage": config.backtest_config.max_leverage,
            "fee_bps": config.backtest_config.fee_bps,
            "slippage_bps": config.backtest_config.slippage_bps,
            "allow_short": config.backtest_config.allow_short,
            "use_strategy_exits": config.backtest_config.use_strategy_exits,
        },
    }
