from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from trader.research import (
    FRAME_FILES,
    ResearchFrames,
    dump_frames,
    load_frames,
    summarize_trades,
)


def _fake_ohlcv(symbol: str, periods: int = 400, base: float = 100.0) -> pd.DataFrame:
    time_index = pd.date_range("2024-01-01", periods=periods, freq="h", tz="UTC")
    close = base + np.linspace(0, 5, periods) + np.sin(np.arange(periods) / 8) * 1.5
    series = pd.Series(close)
    open_ = series.shift(1).fillna(series.iloc[0])
    high = np.maximum(open_, series) + 0.3
    low = np.minimum(open_, series) - 0.3
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


def test_dump_frames_writes_all_five_parquets(tmp_path: Path, monkeypatch) -> None:
    def fake_fetch(request):
        return _fake_ohlcv(request.symbol, periods=400, base=100.0 + len(request.symbol))

    monkeypatch.setattr("trader.research.fetch_ohlcv", fake_fetch)

    frames = dump_frames(out_dir=tmp_path, symbols=["AAPL", "MSFT"], timeframe="1h", bars=400)

    for name, filename in FRAME_FILES.items():
        path = tmp_path / filename
        assert path.exists(), f"{name} parquet missing"
        assert path.stat().st_size > 0
    assert isinstance(frames, ResearchFrames)
    assert set(frames.ohlcv["symbol"]) == {"AAPL", "MSFT"}
    assert "PORTFOLIO" in set(frames.equity["symbol"])


def test_load_frames_round_trip(tmp_path: Path, monkeypatch) -> None:
    def fake_fetch(request):
        return _fake_ohlcv(request.symbol, periods=300)

    monkeypatch.setattr("trader.research.fetch_ohlcv", fake_fetch)

    written = dump_frames(out_dir=tmp_path, symbols=["AAPL"], bars=300)
    reloaded = load_frames(tmp_path)

    pd.testing.assert_frame_equal(
        reloaded.ohlcv.reset_index(drop=True),
        written.ohlcv.reset_index(drop=True),
        check_dtype=False,
    )
    assert len(reloaded.signals) == len(written.signals)
    assert len(reloaded.trades) == len(written.trades)


def test_summarize_trades_returns_per_symbol_stats() -> None:
    trades = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "AAA", "BBB", "BBB"],
            "net_return": [0.02, -0.01, 0.03, -0.005, 0.01],
        }
    )
    summary = summarize_trades(trades).set_index("symbol")

    assert summary.loc["AAA", "trade_count"] == 3
    assert summary.loc["AAA", "win_rate"] == pytest_approx(2 / 3)
    assert summary.loc["AAA", "total_return"] == pytest_approx(0.04)
    assert summary.loc["BBB", "best_trade"] == pytest_approx(0.01)
    assert summary.loc["BBB", "worst_trade"] == pytest_approx(-0.005)


def test_summarize_trades_handles_empty_input() -> None:
    summary = summarize_trades(pd.DataFrame(columns=["symbol", "net_return"]))
    assert summary.empty
    assert "trade_count" in summary.columns


def pytest_approx(value: float, rel: float = 1e-6) -> object:
    import pytest

    return pytest.approx(value, rel=rel)
