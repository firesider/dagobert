from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from trader.backtest_report import (
    render_backtest_report,
    summarize_equity,
    summarize_trades_for_report,
)


def _equity_frame() -> pd.DataFrame:
    times = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    rows = []
    for symbol, values in {
        "AAA": [1000.0, 1010.0, 1005.0, 1025.0],
        "PORTFOLIO": [1000.0, 1008.0, 1007.0, 1020.0],
    }.items():
        for time, equity in zip(times, values, strict=True):
            rows.append(
                {
                    "time": time,
                    "symbol": symbol,
                    "strategy_return": 0.01,
                    "equity": equity,
                    "drawdown": (equity / max(values[: values.index(equity) + 1])) - 1,
                    "benchmark_return": 0.005,
                    "benchmark_equity": 1000.0 + ((time.hour + 1) * 5),
                    "benchmark_drawdown": 0.0,
                }
            )
    return pd.DataFrame(rows)


def _trades_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_id": [1, 2, 3],
            "entry_time": ["2024-01-01T00:00:00Z"] * 3,
            "exit_time": ["2024-01-01T01:00:00Z"] * 3,
            "direction": ["long", "long", "short"],
            "entry_price": [100.0, 101.0, 99.0],
            "exit_price": [101.0, 100.0, 98.0],
            "bars_held": [2, 3, 1],
            "gross_return": [0.02, -0.01, 0.01],
            "net_return": [0.018, -0.012, 0.008],
            "symbol": ["AAA", "AAA", "BBB"],
        }
    )


def test_summarize_equity_returns_per_symbol_stats() -> None:
    summary = summarize_equity(_equity_frame()).set_index("symbol")

    assert summary.loc["PORTFOLIO", "bars"] == 4
    assert summary.loc["PORTFOLIO", "ending_equity"] == 1020.0
    assert summary.loc["AAA", "total_return"] == pytest.approx(0.025)


def test_summarize_trades_for_report_returns_per_symbol_stats() -> None:
    summary = summarize_trades_for_report(_trades_frame()).set_index("symbol")

    assert summary.loc["AAA", "trade_count"] == 2
    assert summary.loc["AAA", "win_rate"] == 0.5
    assert summary.loc["BBB", "best_trade"] == 0.008


def test_render_backtest_report_writes_markdown_csv_and_png(tmp_path: Path) -> None:
    equity_path = tmp_path / "backtest_equity.csv"
    trades_path = tmp_path / "backtest_equity_trades.csv"
    metrics_path = tmp_path / "backtest_equity_metrics.json"
    out_dir = tmp_path / "report"

    _equity_frame().to_csv(equity_path, index=False)
    _trades_frame().to_csv(trades_path, index=False)
    metrics_path.write_text(
        json.dumps(
            {
                "ending_capital": 1020.0,
                "total_return": 0.02,
                "sharpe": 1.1,
                "benchmark_total_return": 0.015,
            }
        ),
        encoding="utf-8",
    )

    result = render_backtest_report(equity_path, out_dir)

    assert result == out_dir
    assert (out_dir / "REPORT.md").exists()
    assert (out_dir / "equity_summary.csv").exists()
    assert (out_dir / "trade_summary.csv").exists()
    assert (out_dir / "worst_trades.csv").exists()
    assert (out_dir / "best_trades.csv").exists()
    assert (out_dir / "equity_curve.png").stat().st_size > 0
    assert (out_dir / "drawdown.png").stat().st_size > 0

    report = (out_dir / "REPORT.md").read_text(encoding="utf-8")
    assert "Backtest Report" in report
    assert "benchmark_total_return" in report
