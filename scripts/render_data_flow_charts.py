"""Render the three sample charts referenced by DATA_FLOW.md.

Outputs into docs/img/:
  - aapl_price_with_emas.png
  - aapl_signals_breakout.png
  - portfolio_equity_curve.png

Run:  python scripts/render_data_flow_charts.py

Requires: ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY in environment, plus the
optional `docs` Poetry group (matplotlib).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from trader.backtest import BacktestConfig, run_backtest  # noqa: E402
from trader.data_sources import FetchRequest, fetch_ohlcv  # noqa: E402
from trader.indicators import build_indicator_frame  # noqa: E402
from trader.strategies import StrategyConfig, build_signal_frame  # noqa: E402

OUT_DIR = REPO_ROOT / "docs" / "img"
PRICE_BARS = 200
BACKTEST_BARS = 1000
PORTFOLIO_SYMBOLS = ("AAPL", "MSFT", "SPY")


def _require_credentials() -> None:
    if not os.getenv("ALPACA_API_KEY_ID") or not os.getenv("ALPACA_API_SECRET_KEY"):
        sys.stderr.write(
            "ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY must be set. "
            "Source your .env first:  set -a; source .env; set +a\n"
        )
        sys.exit(2)


def _fetch_indicators(symbol: str, bars: int, timeframe: str = "1d") -> pd.DataFrame:
    raw = fetch_ohlcv(FetchRequest(symbol=symbol, timeframe=timeframe, bars=bars), source="alpaca")
    return build_indicator_frame(raw)


def render_price_with_emas(out_path: Path) -> None:
    frame = _fetch_indicators("AAPL", PRICE_BARS)
    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=200)
    ax.plot(frame["time"], frame["close"], label="close", color="#1f1f1f", linewidth=1.4)
    ax.plot(frame["time"], frame["ema_20"], label="EMA 20", color="#2563eb", linewidth=1.2)
    ax.plot(frame["time"], frame["ema_50"], label="EMA 50", color="#dc2626", linewidth=1.2)
    ax.set_title(f"AAPL daily close + EMA20 / EMA50  (last {PRICE_BARS} bars, source: alpaca)")
    ax.set_xlabel("date (UTC)")
    ax.set_ylabel("price (USD)")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def render_signals_breakout(out_path: Path) -> None:
    frame = _fetch_indicators("AAPL", PRICE_BARS)
    signals = build_signal_frame(frame, StrategyConfig(strategy="breakout"))
    longs = signals[signals["signal"] == 1]
    shorts = signals[signals["signal"] == -1]

    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=200)
    ax.plot(signals["time"], signals["close"], label="close", color="#1f1f1f", linewidth=1.2)
    ax.scatter(
        longs["time"], longs["close"], marker="^", color="#15803d", s=42, label="long", zorder=3
    )
    ax.scatter(
        shorts["time"], shorts["close"], marker="v", color="#b91c1c", s=42, label="short", zorder=3
    )
    ax.set_title(f"AAPL daily close with breakout-strategy signals  ({PRICE_BARS} bars)")
    ax.set_xlabel("date (UTC)")
    ax.set_ylabel("price (USD)")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def render_portfolio_equity(out_path: Path) -> None:
    raw_frames = [
        fetch_ohlcv(FetchRequest(symbol=s, timeframe="1d", bars=BACKTEST_BARS), source="alpaca")
        for s in PORTFOLIO_SYMBOLS
    ]
    enriched = pd.concat([build_indicator_frame(f) for f in raw_frames], ignore_index=True)
    result = run_backtest(
        enriched,
        strategy_config=StrategyConfig(strategy="breakout"),
        backtest_config=BacktestConfig(),
    )
    curve = result.equity_curve

    palette = {"AAPL": "#2563eb", "MSFT": "#16a34a", "SPY": "#ca8a04", "PORTFOLIO": "#111827"}
    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=200)
    for symbol in [*PORTFOLIO_SYMBOLS, "PORTFOLIO"]:
        sub = curve[curve["symbol"] == symbol].sort_values("time")
        if sub.empty:
            continue
        is_portfolio = symbol == "PORTFOLIO"
        ax.plot(
            sub["time"],
            sub["equity"],
            label=symbol,
            color=palette.get(symbol, "#6b7280"),
            linewidth=2.2 if is_portfolio else 1.1,
            alpha=1.0 if is_portfolio else 0.85,
        )
    ax.set_title(
        f"Portfolio equity curve — breakout strategy, {BACKTEST_BARS} daily bars × "
        f"{', '.join(PORTFOLIO_SYMBOLS)}"
    )
    ax.set_xlabel("date (UTC)")
    ax.set_ylabel("equity (USD)")
    ax.axhline(
        BacktestConfig().initial_capital, color="#9ca3af", linestyle="--", linewidth=0.8, alpha=0.7
    )
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def main() -> int:
    _require_credentials()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    targets = [
        ("aapl_price_with_emas.png", render_price_with_emas),
        ("aapl_signals_breakout.png", render_signals_breakout),
        ("portfolio_equity_curve.png", render_portfolio_equity),
    ]
    for filename, render in targets:
        path = OUT_DIR / filename
        print(f"rendering {path.relative_to(REPO_ROOT)} ...", flush=True)
        render(path)

    print(f"done. {len(targets)} files in {OUT_DIR.relative_to(REPO_ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
