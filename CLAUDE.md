# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`trader` (Trader Workbench / "dagobert") is a pragmatic research toolkit for US equities and crypto via the Alpaca API. The Forex/MT5 path is parked: `trader/mt5.py`, the yfinance branch in `data_sources.py`, and the four `mt5-*` CLI subcommands are commented out in `cli.py` but the modules remain on disk and can be reactivated by uncommenting the imports/wiring.

Active workflow:

- **Research:** Alpaca OHLCV fetch → feature engineering → rule-based signals → lightweight backtest.

The repo's README, code comments, and CLI help text are written in German. Match that style when editing user-facing strings or docstrings.

**Heads-up on strategy thresholds.** `StrategyConfig` defaults (`pullback_tolerance=0.0025`, `long_rsi_floor=52`, `atr_pct` clipping at `[0.003, 0.03]`) were tuned for FX. They will fire less often and at different scales on equities. Re-calibrate when you have meaningful signal counts.

## Setup

The project uses Poetry inside a conda env (no separate venv — `poetry.toml` sets `virtualenvs.create = false`).

```bash
conda env create -f environment.yml
conda activate trader
python -m pip install poetry==2.3.2
poetry install --with dev               # macOS / Linux
poetry install --with dev,mt5           # Windows only — MT5 wheel is win32-only
```

The `mt5` group is gated by `markers = "sys_platform == 'win32'"`, so on macOS/Linux the `MetaTrader5` import will fail. That's expected: `data_sources.fetch_ohlcv(..., source="auto")` automatically falls back to `yfinance`.

## Common commands

```bash
pytest -q                               # full test suite (pythonpath=src is configured)
pytest tests/test_pipeline.py -q        # one file
pytest tests/test_pipeline.py::test_build_indicator_frame_adds_expected_columns -q
trader                                  # equivalent to `trader dataset`
trader dataset --symbols AAPL SPY --timeframe 1h --bars 1500
trader signals --symbols AAPL --strategy ema_rsi_pullback
trader backtest --symbols AAPL SPY --strategy breakout --bars 3000
# mt5-* commands are commented out in cli.py — the FX broker workflow is parked.
```

CLI quirks worth knowing (see `cli.py:37`):
- Calling `trader` with no args defaults to `dataset`.
- If the first arg starts with `-` (e.g. `trader --symbols ...`), it's rewritten to `trader dataset --symbols ...`.

## Architecture

The package lives under `src/trader/`. Module dependency direction:

```
cli  ──►  pipeline ──►  data_sources ──►  alpaca
              └────►  indicators
cli  ──►  strategies ──►  (consumes indicator frame)
cli  ──►  backtest   ──►  strategies, risk
```

Key cross-cutting concerns:

- **Data source abstraction (`data_sources.py`).** `fetch_ohlcv(request, source=...)` still accepts `"auto"|"mt5"|"yfinance"|"alpaca"` at the function level, but the CLI exposes only `"alpaca"` (default). The other branches are kept for callers that import `fetch_ohlcv` directly. Returned schema is fixed: `time, open, high, low, close, volume, tick_volume, spread, real_volume, symbol, timeframe, data_source`. Alpaca fills `tick_volume`/`real_volume`/`spread` with `pd.NA`. Time is always UTC.

For a top-to-bottom reference of the data pipeline (sources, schemas, every indicator column, sample charts), see [DATA_FLOW.md](./DATA_FLOW.md).

- **Time is always UTC.** MT5 epoch seconds and yfinance datetimes are both converted to UTC `pd.Timestamp` before any feature work. Don't introduce naive datetimes anywhere downstream.

- **Indicator pipeline (`indicators.py`).** Wraps the `ta` library (`add_all_ta_features`) and adds custom price-action, pivot/Fibonacci, and regime features. Spot-FX often lacks usable volume; `_attach_volume_proxy` constructs an `analysis_volume` from range + abs return when neither `tick_volume` nor `volume` is present, and flags it with `volume_is_proxy=True`. Always feed `analysis_volume` (not `volume`) into volume-based indicators.

- **Strategy contract (`strategies.py`).** `build_signal_frame` requires the columns in `REQUIRED_SIGNAL_COLUMNS` (notably `ema_20`, `ema_50`, `trend_adx`, `momentum_rsi`, `rolling_high_20/_low_20`, `atr_pct`). Strategies emit an integer `signal ∈ {-1, 0, 1}` plus `conviction_score`, `suggested_stop_loss_pct`, `suggested_take_profit_pct`. Two strategies exist: `ema_rsi_pullback` and `breakout`; add new ones to `SUPPORTED_STRATEGIES` and dispatch in `build_signal_frame`.

- **Backtest (`backtest.py`).** Per-symbol vectorized backtest using `signal.shift(1)` for next-bar execution; exposure is derived from `risk_per_trade / stop_loss_pct` and capped by `max_leverage` (`risk.implied_notional_exposure`). Fees and slippage are modeled in basis points on turnover. The portfolio curve is the equal-weight mean of per-symbol returns and is appended to the equity frame with `symbol="PORTFOLIO"`. This is *not* a tick-accurate broker simulator — don't claim it is.

- **Risk module (`risk.py`) has two distinct code paths.** `position_size_from_stop` is the live/broker-near sizing that respects MT5 symbol metadata (`trade_contract_size`, `volume_step`, `volume_min`, `volume_max`); it is used by `trader mt5-check-order`. `implied_notional_exposure` is the abstract backtest-only sizing. Don't conflate them.

- **MT5 client (`mt5.py`) is parked.** The module is intact on disk for tests (`tests/test_mt5.py` still passes against a fake MT5 module) and for future reactivation, but the four `mt5-*` CLI subcommands and the corresponding imports in `cli.py` are commented out. To reactivate FX/MT5: uncomment the import block in `cli.py:15` and the `_run_mt5_*` / `_add_mt5_*` blocks lower in the file, plus restore `--source` choices.

## Alpaca connection settings

Read from environment by `AlpacaConnectionSettings.from_env()` in `src/trader/alpaca.py`:

- `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` — required for `--source alpaca`
- `ALPACA_PAPER` (bool, default `true`)
- `ALPACA_DATA_FEED` (`iex` default; `sip` requires the paid tier)

Alpaca is data-only in this repo: there is no Alpaca counterpart to the four `mt5-*` CLI commands. `order_check` / `order_calc_margin` / `order_calc_profit` have no Alpaca equivalent, so the broker workflow stays on MT5. Symbol routing in `AlpacaClient.copy_rates`: a `/` in the symbol (`BTC/USD`) routes to `CryptoHistoricalDataClient`; otherwise `StockHistoricalDataClient`. The default `--symbols` list is still FX, so `--source alpaca` requires the user to pass `--symbols AAPL SPY` (or similar) explicitly.

## Tests

`pytest.ini_options.pythonpath = ["src"]` is set in `pyproject.toml`, so tests can `from trader.x import y` without installing the package. Tests under `tests/` are pure-pandas and don't require MT5; `test_mt5.py` injects a fake module rather than importing the real one. Keep MT5-dependent tests fakeable the same way.
