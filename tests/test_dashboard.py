from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from trader.dashboard import build_dashboard_payload, render_dashboard_html


def test_build_dashboard_payload_discovers_backtest_outputs(tmp_path: Path) -> None:
    equity = pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC"),
            "symbol": ["PORTFOLIO"] * 3,
            "equity": [1000.0, 1010.0, 1025.0],
            "drawdown": [0.0, 0.0, 0.0],
            "benchmark_equity": [1000.0, 1005.0, 1010.0],
        }
    )
    trades = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "net_return": [0.01],
            "entry_time": ["2024-01-01T00:00:00Z"],
            "exit_time": ["2024-01-01T01:00:00Z"],
        }
    )
    equity.to_csv(tmp_path / "backtest_equity.csv", index=False)
    trades.to_csv(tmp_path / "backtest_equity_trades.csv", index=False)
    (tmp_path / "backtest_equity_metrics.json").write_text(
        json.dumps({"ending_capital": 1025.0, "total_return": 0.025, "trade_count": 1}),
        encoding="utf-8",
    )

    payload = build_dashboard_payload(tmp_path)

    assert payload["counts"]["backtests"] == 1
    run = payload["backtests"][0]
    assert run["name"] == "backtest_equity.csv"
    assert run["metrics"]["ending_capital"] == 1025.0
    assert run["summary"][0]["symbol"] == "PORTFOLIO"
    assert len(run["equity"]) == 3


def test_build_dashboard_payload_discovers_sweep_outputs(tmp_path: Path) -> None:
    sweep_dir = tmp_path / "sweep_results"
    sweep_dir.mkdir()
    results = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB"],
            "oos_sharpe": [0.5, 1.2],
        }
    )
    results.to_parquet(sweep_dir / "20260101T000000Z.parquet", index=False)
    (sweep_dir / "20260101T000000Z_winners.json").write_text(
        json.dumps({"winners": [{"cohort": "equity", "robust_score": 1.0}]}),
        encoding="utf-8",
    )

    payload = build_dashboard_payload(tmp_path)

    assert payload["counts"]["sweeps"] == 1
    run = payload["sweeps"][0]
    assert run["metrics"]["cells"] == 2
    assert run["metrics"]["best_oos_sharpe"] == 1.2
    assert run["metrics"]["eligible_winners"] == 1


def test_render_dashboard_html_contains_api_hook() -> None:
    html = render_dashboard_html()

    assert "Trader Dashboard" in html
    assert "/api/summary" in html


def test_dashboard_metrics_use_oos_values_for_walk_forward_runs(tmp_path: Path) -> None:
    """Walk-forward metrics use prefixed keys (in_sample_*, out_of_sample_*).
    The dashboard must surface the OOS half and label the cards `oos_*`,
    otherwise every card except the two with fallbacks renders empty."""
    equity = pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC"),
            "symbol": ["PORTFOLIO"] * 4,
            "equity": [1000.0, 1010.0, 1005.0, 1025.0],
            "drawdown": [0.0, 0.0, -0.005, 0.0],
            "benchmark_equity": [1000.0, 1004.0, 1008.0, 1012.0],
        }
    )
    trades = pd.DataFrame({"symbol": ["AAA"], "net_return": [0.02], "sample": ["out_of_sample"]})
    equity.to_csv(tmp_path / "wf_equity.csv", index=False)
    trades.to_csv(tmp_path / "wf_equity_trades.csv", index=False)
    (tmp_path / "wf_equity_metrics.json").write_text(
        json.dumps(
            {
                "in_sample_total_return": -0.05,
                "in_sample_sharpe": -1.2,
                "in_sample_trade_count": 30,
                "out_of_sample_ending_capital": 1025.0,
                "out_of_sample_total_return": 0.025,
                "out_of_sample_sharpe": 0.65,
                "out_of_sample_max_drawdown": -0.005,
                "out_of_sample_trade_count": 12,
                "out_of_sample_win_rate": 0.55,
                "out_of_sample_profit_factor": 1.4,
                "out_of_sample_benchmark_total_return": 0.012,
                "in_sample_fraction": 0.7,
            }
        ),
        encoding="utf-8",
    )

    payload = build_dashboard_payload(tmp_path)
    metrics = payload["backtests"][0]["metrics"]

    assert metrics["oos_ending_capital"] == 1025.0
    assert metrics["oos_total_return"] == 0.025
    assert metrics["oos_sharpe"] == 0.65
    assert metrics["oos_max_drawdown"] == -0.005
    assert metrics["oos_trades"] == 12
    assert metrics["oos_win_rate"] == 0.55
    assert metrics["oos_profit_factor"] == 1.4
    assert metrics["oos_benchmark_return"] == 0.012
    # Plain (non-walk-forward) keys should NOT appear when prefixed ones exist.
    assert "total_return" not in metrics
    assert "sharpe" not in metrics
