"""Markdown/PNG report generation for saved backtest outputs."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd


def render_backtest_report(
    equity_path: str | Path,
    out_dir: str | Path,
    *,
    trades_path: str | Path | None = None,
    metrics_path: str | Path | None = None,
) -> Path:
    """Render a reproducible report from saved backtest files.

    ``equity_path`` is required. ``trades_path`` and ``metrics_path`` default
    to the filenames emitted by ``trader backtest``:
    ``<equity_stem>_trades.csv`` and ``<equity_stem>_metrics.json``.
    """
    equity_file = Path(equity_path)
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)

    equity = _read_frame(equity_file)
    trades_file = (
        Path(trades_path)
        if trades_path
        else equity_file.with_name(f"{equity_file.stem}_trades.csv")
    )
    metrics_file = (
        Path(metrics_path)
        if metrics_path
        else equity_file.with_name(f"{equity_file.stem}_metrics.json")
    )

    trades = _read_frame(trades_file) if trades_file.exists() else _empty_trades()
    metrics = _read_metrics(metrics_file) if metrics_file.exists() else {}

    summary = summarize_equity(equity)
    trade_summary = summarize_trades_for_report(trades)
    worst_trades = _worst_trades(trades)
    best_trades = _best_trades(trades)

    summary.to_csv(target / "equity_summary.csv", index=False)
    trade_summary.to_csv(target / "trade_summary.csv", index=False)
    worst_trades.to_csv(target / "worst_trades.csv", index=False)
    best_trades.to_csv(target / "best_trades.csv", index=False)

    _plot_equity(equity, target / "equity_curve.png")
    _plot_drawdown(equity, target / "drawdown.png")

    _write_report_index(
        out_dir=target,
        equity_path=equity_file,
        trades_path=trades_file if trades_file.exists() else None,
        metrics_path=metrics_file if metrics_file.exists() else None,
        metrics=metrics,
        summary=summary,
        trade_summary=trade_summary,
        worst_trades=worst_trades,
        best_trades=best_trades,
    )
    return target


def summarize_equity(equity: pd.DataFrame) -> pd.DataFrame:
    """Headline stats per symbol from a backtest equity curve."""
    required = {"symbol", "equity", "drawdown", "strategy_return"}
    missing = required.difference(equity.columns)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Equity-Frame fehlt Pflichtspalten: {missing_list}")

    rows: list[dict[str, float | str | int]] = []
    for symbol, frame in equity.groupby("symbol", sort=True):
        sorted_frame = frame.sort_values("time") if "time" in frame.columns else frame
        start_equity = float(sorted_frame["equity"].iloc[0])
        end_equity = float(sorted_frame["equity"].iloc[-1])
        benchmark_end = (
            float(sorted_frame["benchmark_equity"].iloc[-1])
            if "benchmark_equity" in sorted_frame.columns
            else float("nan")
        )
        rows.append(
            {
                "symbol": str(symbol),
                "bars": int(len(sorted_frame)),
                "ending_equity": end_equity,
                "total_return": (end_equity / start_equity) - 1 if start_equity > 0 else 0.0,
                "max_drawdown": float(sorted_frame["drawdown"].min()),
                "avg_strategy_return": float(sorted_frame["strategy_return"].mean()),
                "benchmark_ending_equity": benchmark_end,
                "benchmark_total_return": (
                    (benchmark_end / start_equity) - 1
                    if start_equity > 0 and pd.notna(benchmark_end)
                    else float("nan")
                ),
            }
        )
    return pd.DataFrame(rows)


def summarize_trades_for_report(trades: pd.DataFrame) -> pd.DataFrame:
    """Per-symbol trade stats used by the report."""
    if trades.empty or "net_return" not in trades.columns:
        return pd.DataFrame(
            columns=[
                "symbol",
                "trade_count",
                "win_rate",
                "avg_net_return",
                "total_net_return",
                "best_trade",
                "worst_trade",
                "avg_bars_held",
            ]
        )

    grouped = trades.groupby("symbol", sort=True)
    return grouped.apply(_trade_group_summary, include_groups=False).reset_index()


def _trade_group_summary(frame: pd.DataFrame) -> pd.Series:
    return pd.Series(
        {
            "trade_count": int(len(frame)),
            "win_rate": float((frame["net_return"] > 0).mean()),
            "avg_net_return": float(frame["net_return"].mean()),
            "total_net_return": float(frame["net_return"].sum()),
            "best_trade": float(frame["net_return"].max()),
            "worst_trade": float(frame["net_return"].min()),
            "avg_bars_held": float(frame["bars_held"].mean()) if "bars_held" in frame else 0.0,
        }
    )


def _write_report_index(
    *,
    out_dir: Path,
    equity_path: Path,
    trades_path: Path | None,
    metrics_path: Path | None,
    metrics: dict[str, Any],
    summary: pd.DataFrame,
    trade_summary: pd.DataFrame,
    worst_trades: pd.DataFrame,
    best_trades: pd.DataFrame,
) -> None:
    lines = [
        f"# Backtest Report - {equity_path.name}",
        "",
        f"Equity source: `{equity_path}`",
        f"Trades source: `{trades_path}`" if trades_path else "Trades source: not found",
        f"Metrics source: `{metrics_path}`" if metrics_path else "Metrics source: not found",
        "",
        "## Metrics",
        "",
        _metrics_block(metrics),
        "",
        "## Equity Summary",
        "",
        "```",
        summary.to_string(index=False, float_format=lambda v: f"{v:.4f}"),
        "```",
        "",
        "## Trade Summary",
        "",
        _frame_block(trade_summary, empty_text="No trades found."),
        "",
        "## Worst Trades",
        "",
        _frame_block(worst_trades, empty_text="No trades found."),
        "",
        "## Best Trades",
        "",
        _frame_block(best_trades, empty_text="No trades found."),
        "",
        "## Plots",
        "",
        "- ![Equity curve](equity_curve.png)",
        "- ![Drawdown](drawdown.png)",
        "",
        "## Files",
        "",
        "- `equity_summary.csv`",
        "- `trade_summary.csv`",
        "- `worst_trades.csv`",
        "- `best_trades.csv`",
    ]
    (out_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def _metrics_block(metrics: dict[str, Any]) -> str:
    if not metrics:
        return "_No metrics JSON found._"
    keys = [
        "initial_capital",
        "ending_capital",
        "total_return",
        "annualized_return",
        "annualized_volatility",
        "sharpe",
        "max_drawdown",
        "trade_count",
        "win_rate",
        "profit_factor",
        "benchmark_total_return",
        "benchmark_sharpe",
        "out_of_sample_total_return",
        "out_of_sample_sharpe",
        "out_of_sample_benchmark_total_return",
        "out_of_sample_benchmark_sharpe",
    ]
    rows = [(key, metrics[key]) for key in keys if key in metrics]
    if not rows:
        rows = sorted(metrics.items())
    text = pd.DataFrame(rows, columns=["metric", "value"]).to_string(index=False)
    return f"```\n{text}\n```"


def _frame_block(frame: pd.DataFrame, *, empty_text: str) -> str:
    if frame.empty:
        return f"_{empty_text}_"
    return f"```\n{frame.to_string(index=False, float_format=lambda v: f'{v:.4f}')}\n```"


def _plot_equity(equity: pd.DataFrame, path: Path) -> None:
    plt = _import_pyplot()
    fig, ax = plt.subplots(figsize=(10, 4))
    for symbol, frame in _plot_symbols(equity).groupby("symbol", sort=True):
        sorted_frame = frame.sort_values("time")
        ax.plot(sorted_frame["time"], sorted_frame["equity"], label=str(symbol))
        if symbol == "PORTFOLIO" and "benchmark_equity" in sorted_frame.columns:
            ax.plot(
                sorted_frame["time"],
                sorted_frame["benchmark_equity"],
                label="PORTFOLIO benchmark",
                linestyle="--",
            )
    ax.set_xlabel("time")
    ax.set_ylabel("equity")
    ax.set_title("Equity curve")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _plot_drawdown(equity: pd.DataFrame, path: Path) -> None:
    plt = _import_pyplot()
    fig, ax = plt.subplots(figsize=(10, 4))
    for symbol, frame in _plot_symbols(equity).groupby("symbol", sort=True):
        sorted_frame = frame.sort_values("time")
        ax.plot(sorted_frame["time"], sorted_frame["drawdown"], label=str(symbol))
    ax.set_xlabel("time")
    ax.set_ylabel("drawdown")
    ax.set_title("Drawdown")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _plot_symbols(equity: pd.DataFrame) -> pd.DataFrame:
    if "PORTFOLIO" in set(equity["symbol"]):
        return equity[equity["symbol"] == "PORTFOLIO"]
    return equity


def _import_pyplot():
    os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="trader-mpl-"))
    import matplotlib.pyplot as plt

    return plt


def _best_trades(trades: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    if trades.empty or "net_return" not in trades.columns:
        return _empty_trades()
    return trades.sort_values("net_return", ascending=False).head(limit).reset_index(drop=True)


def _worst_trades(trades: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    if trades.empty or "net_return" not in trades.columns:
        return _empty_trades()
    return trades.sort_values("net_return", ascending=True).head(limit).reset_index(drop=True)


def _read_frame(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix == ".csv":
        return pd.read_csv(path)
    if path.suffix == ".json":
        return pd.read_json(path)
    raise ValueError("Input-Datei muss .parquet, .csv oder .json enden.")


def _read_metrics(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _empty_trades() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "trade_id",
            "entry_time",
            "exit_time",
            "direction",
            "entry_price",
            "exit_price",
            "bars_held",
            "gross_return",
            "net_return",
            "symbol",
        ]
    )
