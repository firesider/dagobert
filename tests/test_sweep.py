from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from trader.sweep import (
    SweepConfig,
    SweepGrid,
    persist_results,
    pick_winners,
    run_sweep,
)


def _synthetic_ohlcv(symbol: str, periods: int = 600, base: float = 100.0) -> pd.DataFrame:
    time_index = pd.date_range("2024-01-01", periods=periods, freq="h", tz="UTC")
    rng = np.random.default_rng(seed=hash(symbol) & 0xFFFF)
    drift = np.linspace(0, 5, periods)
    noise = rng.normal(0, 0.6, periods)
    close = base + drift + noise.cumsum() * 0.05
    series = pd.Series(close)
    open_ = series.shift(1).fillna(series.iloc[0])
    high = np.maximum(open_, series) + 0.4
    low = np.minimum(open_, series) - 0.4
    return pd.DataFrame(
        {
            "time": time_index,
            "open": open_.to_numpy(),
            "high": high.to_numpy(),
            "low": low.to_numpy(),
            "close": series.to_numpy(),
            "volume": np.linspace(1_000_000, 1_500_000, periods),
            "tick_volume": pd.NA,
            "spread": pd.NA,
            "real_volume": pd.NA,
            "symbol": symbol,
            "timeframe": "1h",
            "data_source": "test",
        }
    )


def _patch_fetch(monkeypatch) -> None:
    def fake_fetch(request):
        return _synthetic_ohlcv(request.symbol, periods=600)

    monkeypatch.setattr("trader.sweep.fetch_ohlcv", fake_fetch)


def test_sweep_grid_quick_yields_eight_cells() -> None:
    grid = SweepGrid.quick()
    cells = grid.cells()
    assert len(cells) == 8
    keys = {"pullback_tolerance", "long_rsi_floor", "atr_pct_floor", "atr_pct_ceiling"}
    assert all(set(cell.keys()) == keys for cell in cells)


def test_sweep_grid_rejects_floor_above_ceiling() -> None:
    grid = SweepGrid(
        pullback_tolerance=(0.005,),
        long_rsi_floor=(52.0,),
        atr_pct_floor=(0.005, 0.05),
        atr_pct_ceiling=(0.03, 0.10),
    )
    cells = grid.cells()
    # 0.05 floor with 0.03 ceiling must be rejected; the others survive.
    pairs = {(cell["atr_pct_floor"], cell["atr_pct_ceiling"]) for cell in cells}
    assert (0.05, 0.03) not in pairs
    assert (0.005, 0.03) in pairs
    assert (0.05, 0.10) in pairs


def test_sweep_config_rejects_invalid_in_sample_fraction() -> None:
    with pytest.raises(ValueError, match="in_sample_fraction"):
        SweepConfig(in_sample_fraction=1.0)


def test_run_sweep_smoke(monkeypatch) -> None:
    _patch_fetch(monkeypatch)
    config = SweepConfig(
        grid=SweepGrid.quick(),
        timeframes=("1h",),
        equity_symbols=("AAA",),
        crypto_symbols=("BBB/USD",),
        years_by_timeframe={"1h": 0.07},  # ~600 bars
        min_trades=1,
    )
    results = run_sweep(config)

    expected_rows = len(SweepGrid.quick().cells()) * 1 * 2  # cells × timeframes × symbols
    assert len(results) == expected_rows
    expected_cols = {
        "cohort",
        "symbol",
        "timeframe",
        "pullback_tolerance",
        "long_rsi_floor",
        "atr_pct_floor",
        "atr_pct_ceiling",
        "in_sample_sharpe",
        "in_sample_trade_count",
        "in_sample_total_return",
        "in_sample_max_drawdown",
        "in_sample_benchmark_total_return",
        "oos_sharpe",
        "oos_trade_count",
        "oos_total_return",
        "oos_max_drawdown",
        "oos_benchmark_total_return",
        "oos_excess_return",
        "strategy",
        "risk_per_trade",
        "stop_loss_pct",
    }
    assert expected_cols.issubset(set(results.columns))
    assert set(results["cohort"]) == {"equity", "crypto"}


def test_pick_winners_rejects_low_trade_count_and_picks_best() -> None:
    rows = [
        # cohort A, two cells, both meet min_trades, second is better
        {
            "cohort": "equity",
            "timeframe": "1d",
            "pullback_tolerance": 0.005,
            "long_rsi_floor": 52.0,
            "atr_pct_floor": 0.003,
            "atr_pct_ceiling": 0.03,
            "symbol": "AAA",
            "oos_sharpe": 0.5,
            "oos_trade_count": 40,
        },
        {
            "cohort": "equity",
            "timeframe": "1d",
            "pullback_tolerance": 0.01,
            "long_rsi_floor": 55.0,
            "atr_pct_floor": 0.003,
            "atr_pct_ceiling": 0.05,
            "symbol": "AAA",
            "oos_sharpe": 1.2,
            "oos_trade_count": 50,
        },
        # third cell: high Sharpe but only 5 trades — must be filtered out
        {
            "cohort": "equity",
            "timeframe": "1d",
            "pullback_tolerance": 0.02,
            "long_rsi_floor": 58.0,
            "atr_pct_floor": 0.003,
            "atr_pct_ceiling": 0.10,
            "symbol": "AAA",
            "oos_sharpe": 5.0,
            "oos_trade_count": 5,
        },
    ]
    results = pd.DataFrame(rows)
    winners = pick_winners(results, min_trades=30)

    assert len(winners) == 1
    winner = winners.iloc[0]
    assert winner["cohort"] == "equity"
    assert winner["pullback_tolerance"] == pytest.approx(0.01)
    assert winner["long_rsi_floor"] == pytest.approx(55.0)
    # The 5-trade cell with Sharpe=5.0 must NOT be the winner.
    assert winner["oos_sharpe_mean"] == pytest.approx(1.2)
    assert "robust_score" in winner


def test_pick_winners_returns_empty_when_no_cell_eligible() -> None:
    results = pd.DataFrame(
        [
            {
                "cohort": "equity",
                "timeframe": "1d",
                "pullback_tolerance": 0.005,
                "long_rsi_floor": 52.0,
                "atr_pct_floor": 0.003,
                "atr_pct_ceiling": 0.03,
                "symbol": "AAA",
                "oos_sharpe": 1.5,
                "oos_trade_count": 10,
            },
        ]
    )
    winners = pick_winners(results, min_trades=30)
    assert winners.empty


def test_persist_results_writes_parquet_and_winners_json(tmp_path: Path) -> None:
    results = pd.DataFrame(
        [
            {
                "cohort": "equity",
                "symbol": "AAA",
                "timeframe": "1d",
                "pullback_tolerance": 0.005,
                "long_rsi_floor": 52.0,
                "atr_pct_floor": 0.003,
                "atr_pct_ceiling": 0.03,
                "in_sample_sharpe": 0.7,
                "in_sample_trade_count": 60,
                "oos_sharpe": 1.1,
                "oos_trade_count": 40,
            }
        ]
    )
    winners = pick_winners(results, min_trades=30)
    results_path, winners_path = persist_results(
        results, winners, tmp_path, timestamp="20260101T000000Z"
    )

    assert results_path.name == "20260101T000000Z.parquet"
    assert winners_path.name == "20260101T000000Z_winners.json"
    assert results_path.exists()
    assert winners_path.exists()

    payload = json.loads(winners_path.read_text())
    assert payload["generated_at"] == "20260101T000000Z"
    assert "robust_score" in payload["ranking_method"]
    assert payload["config"] is None
    assert len(payload["winners"]) == 1
    winner = payload["winners"][0]
    assert winner["cohort"] == "equity"
    assert winner["pullback_tolerance"] == pytest.approx(0.005)
    assert "robust_score" in winner


def test_persist_results_includes_config_metadata(tmp_path: Path) -> None:
    results = pd.DataFrame(
        [
            {
                "cohort": "equity",
                "symbol": "AAA",
                "timeframe": "1d",
                "strategy": "ema_rsi_pullback",
                "pullback_tolerance": 0.005,
                "long_rsi_floor": 52.0,
                "atr_pct_floor": 0.003,
                "atr_pct_ceiling": 0.03,
                "in_sample_sharpe": 0.7,
                "in_sample_trade_count": 60,
                "oos_sharpe": 1.1,
                "oos_total_return": 0.12,
                "oos_max_drawdown": -0.04,
                "oos_profit_factor": 1.8,
                "oos_benchmark_total_return": 0.05,
                "oos_trade_count": 40,
            }
        ]
    )
    config = SweepConfig(
        grid=SweepGrid.quick(),
        timeframes=("1d",),
        equity_symbols=("AAA",),
        crypto_symbols=(),
        min_trades=1,
    )
    winners = pick_winners(results, min_trades=1)
    _, winners_path = persist_results(
        results, winners, tmp_path, timestamp="20260101T000000Z", config=config
    )

    payload = json.loads(winners_path.read_text())
    assert payload["config"]["strategy"] == "ema_rsi_pullback"
    assert payload["config"]["timeframes"] == ["1d"]
    assert payload["config"]["equity_symbols"] == ["AAA"]
    assert payload["config"]["grid"]["pullback_tolerance"] == [0.0025, 0.01]
