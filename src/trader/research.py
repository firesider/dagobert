"""Helpers for ad-hoc research and notebook exploration.

The CLI subcommand ``trader dump-frames`` writes the intermediate frames of
the research pipeline (raw OHLCV, indicators, signals, trades, equity) to
parquet so they can be reloaded cheaply from a notebook or REPL. The helpers
here are the matching reload + visualization side.

Plotting helpers depend on matplotlib, which is in the optional ``docs``
Poetry group; they import lazily so the rest of the module is importable
without it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from trader.backtest import BacktestConfig, run_backtest
from trader.data_sources import FetchRequest, fetch_ohlcv
from trader.indicators import build_indicator_frame
from trader.strategies import StrategyConfig, build_signal_frame

if TYPE_CHECKING:
    from matplotlib.axes import Axes


FRAME_FILES: dict[str, str] = {
    "ohlcv": "ohlcv.parquet",
    "indicators": "indicators.parquet",
    "signals": "signals.parquet",
    "trades": "trades.parquet",
    "equity": "equity.parquet",
}


@dataclass(frozen=True)
class ResearchFrames:
    """Container for the five frames produced by ``dump_frames``."""

    ohlcv: pd.DataFrame
    indicators: pd.DataFrame
    signals: pd.DataFrame
    trades: pd.DataFrame
    equity: pd.DataFrame


def dump_frames(
    out_dir: str | Path,
    symbols: Iterable[str],
    timeframe: str = "1h",
    bars: int = 1500,
    strategy_config: StrategyConfig | None = None,
    backtest_config: BacktestConfig | None = None,
) -> ResearchFrames:
    """Run the full pipeline and persist every intermediate frame to parquet.

    Returns the in-memory ``ResearchFrames`` for callers that want to keep
    working with the results without an extra disk round-trip.
    """
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)

    ohlcv_frames: list[pd.DataFrame] = []
    indicator_frames: list[pd.DataFrame] = []
    failures: list[str] = []

    for symbol in symbols:
        try:
            raw = fetch_ohlcv(FetchRequest(symbol=symbol, timeframe=timeframe, bars=bars))
            ohlcv_frames.append(raw)
            indicator_frames.append(build_indicator_frame(raw))
        except Exception as exc:  # pragma: no cover - keep robust to mixed-symbol failures
            failures.append(f"{symbol}: {exc}")

    if not indicator_frames:
        joined = " | ".join(failures) if failures else "Unbekannter Fehler."
        raise RuntimeError(f"Konnte keine Daten fuer dump-frames aufbauen. {joined}")

    ohlcv = (
        pd.concat(ohlcv_frames, ignore_index=True)
        .sort_values(["symbol", "time"])
        .reset_index(drop=True)
    )
    indicators = (
        pd.concat(indicator_frames, ignore_index=True)
        .sort_values(["symbol", "time"])
        .reset_index(drop=True)
    )

    signals = build_signal_frame(indicators, strategy_config)
    backtest = run_backtest(
        indicators,
        strategy_config=strategy_config,
        backtest_config=backtest_config,
    )

    frames = ResearchFrames(
        ohlcv=ohlcv,
        indicators=indicators,
        signals=signals,
        trades=backtest.trades,
        equity=backtest.equity_curve,
    )

    for name, frame in _frame_iter(frames):
        frame.to_parquet(target / FRAME_FILES[name], index=False)

    if failures:
        print("Teilweise fehlgeschlagen:")
        for failure in failures:
            print(f" - {failure}")

    return frames


def load_frames(out_dir: str | Path) -> ResearchFrames:
    """Reload the five frames previously written by ``dump_frames``."""
    source = Path(out_dir)
    return ResearchFrames(
        ohlcv=pd.read_parquet(source / FRAME_FILES["ohlcv"]),
        indicators=pd.read_parquet(source / FRAME_FILES["indicators"]),
        signals=pd.read_parquet(source / FRAME_FILES["signals"]),
        trades=pd.read_parquet(source / FRAME_FILES["trades"]),
        equity=pd.read_parquet(source / FRAME_FILES["equity"]),
    )


def summarize_trades(trades: pd.DataFrame) -> pd.DataFrame:
    """Per-symbol headline stats from a trades frame.

    Columns: ``symbol, trade_count, win_rate, avg_return, total_return,
    best_trade, worst_trade``. Trades frame must have at least
    ``symbol``, ``net_return``.
    """
    if trades.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "trade_count",
                "win_rate",
                "avg_return",
                "total_return",
                "best_trade",
                "worst_trade",
            ]
        )

    grouped = trades.groupby("symbol", sort=True)["net_return"]
    summary = pd.DataFrame(
        {
            "symbol": grouped.size().index,
            "trade_count": grouped.size().to_numpy(),
            "win_rate": grouped.apply(lambda s: float((s > 0).mean())).to_numpy(),
            "avg_return": grouped.mean().to_numpy(),
            "total_return": grouped.sum().to_numpy(),
            "best_trade": grouped.max().to_numpy(),
            "worst_trade": grouped.min().to_numpy(),
        }
    )
    return summary.reset_index(drop=True)


def plot_equity_curve(
    equity: pd.DataFrame,
    *,
    symbols: Iterable[str] | None = None,
    ax: Axes | None = None,
) -> Axes:
    """Plot equity curves over time. Defaults to the PORTFOLIO row.

    ``equity`` must have ``time``, ``equity``, ``symbol`` columns — the
    canonical schema produced by ``run_backtest``.
    """
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots(figsize=(10, 4))

    chosen = list(symbols) if symbols else ["PORTFOLIO"]
    for symbol in chosen:
        sub = equity[equity["symbol"] == symbol].sort_values("time")
        if sub.empty:
            continue
        ax.plot(sub["time"], sub["equity"], label=symbol)

    ax.set_xlabel("time")
    ax.set_ylabel("equity")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)
    return ax


def _frame_iter(frames: ResearchFrames) -> Iterable[tuple[str, pd.DataFrame]]:
    yield "ohlcv", frames.ohlcv
    yield "indicators", frames.indicators
    yield "signals", frames.signals
    yield "trades", frames.trades
    yield "equity", frames.equity
