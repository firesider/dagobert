# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`trader` (Trader Workbench / "dagobert") is a pragmatic research toolkit for US equities and crypto via the Alpaca API. The repo previously also wrapped MetaTrader 5 (FX/CFD broker) and Yahoo Finance; that path was removed — see `git log` for the full picture.

Active workflow:

- **Research:** Alpaca OHLCV fetch → feature engineering → rule-based signals → lightweight backtest.

The repo's README, code comments, and CLI help text are written in German. Match that style when editing user-facing strings or docstrings.

**Heads-up on strategy thresholds.** `StrategyConfig` defaults (`pullback_tolerance=0.0025`, `long_rsi_floor=52`, `atr_pct_floor=0.003`, `atr_pct_ceiling=0.03`) were tuned for FX. They will fire less often and at different scales on equities and crypto. The first sweep on Alpaca history (May 2026) found only 2 eligible cells — both at the lower edge of the grid — so the FX defaults still ship; expand the grid downward (`long_rsi_floor` ≤ 48, `atr_pct_floor` ≤ 0.001) before re-running. Override via CLI flags meanwhile.

## Setup

The project uses Poetry inside a conda env (no separate venv — `poetry.toml` sets `virtualenvs.create = false`). Python is pinned to `>=3.11,<3.13` in `pyproject.toml`.

```bash
conda env create -f environment.yml
conda activate trader
python -m pip install poetry==2.3.2
poetry install --with dev,alpaca         # active workflow
poetry install --with dev,alpaca,docs    # adds matplotlib for scripts/render_data_flow_charts.py
```

Three optional groups are defined in `pyproject.toml`: `dev`, `alpaca`, `docs`. The active workflow needs `alpaca` — installing only `--with dev` will leave `alpaca-py` missing.

## Common commands

```bash
pytest -q                               # full test suite (pythonpath=src is configured)
pytest tests/test_pipeline.py -q        # one file
pytest tests/test_pipeline.py::test_build_indicator_frame_adds_expected_columns -q
ruff check .                            # lint (config in pyproject.toml [tool.ruff])
ruff format .                           # autoformat
mypy                                    # type-check src/ (config in pyproject.toml [tool.mypy])
pre-commit install                      # one-time: enable ruff hooks on commit
trader                                  # equivalent to `trader dataset`
trader dataset --symbols AAPL SPY --timeframe 1h --bars 1500
trader signals --symbols AAPL --strategy ema_rsi_pullback
trader backtest --symbols AAPL SPY --strategy breakout --bars 3000
trader dump-frames --symbols AAPL SPY BTC/USD --timeframe 1d --bars 500 --out-dir data/research
jupyter notebook notebooks/exploration.ipynb    # explore the dumped frames
trader sweep --quick                             # smoke threshold sweep (8 cells × 2 equity + 1 crypto symbols × 1 timeframe)
trader sweep                                     # full sweep — slow; calls Alpaca for the cohort
trader sweep-report data/sweep_results/<file>.parquet --out-dir data/sweep_results/<dir>  # heatmaps + scatter
trader backtest-report data/backtests/<run>/equity.csv --out-dir data/backtests/<run>     # equity/drawdown PNGs + REPORT.md
trader dashboard --data-dir data                                # local HTML dashboard for browsing artifacts
python scripts/render_data_flow_charts.py    # regenerate DATA_FLOW.md charts in docs/img/ (needs `docs` group)
```

`trader dump-frames` writes five parquet files into `--out-dir` (`ohlcv.parquet`, `indicators.parquet`, `signals.parquet`, `trades.parquet`, `equity.parquet`) — every stage of the research pipeline as a separate frame so you can iterate from a notebook without re-fetching. `src/trader/research.py` exposes `load_frames`, `summarize_trades`, and `plot_equity_curve` for the reload side; `notebooks/exploration.ipynb` is the canonical walkthrough.

`trader sweep` runs a grid search over `pullback_tolerance × long_rsi_floor × atr_pct_floor × atr_pct_ceiling` (~144 cells after rejecting floor≥ceiling) for `(equity, crypto) × (1d, 1h)` cohorts. It splits each symbol's history 70/30 in-sample / out-of-sample, scores cells by mean OOS Sharpe across the cohort with a `min_trades >= 30` guard, and writes `<timestamp>.parquet` (full grid) plus `<timestamp>_winners.json` (per-cohort winners) into `data/sweep_results/`.

`trader sweep-report` consumes a sweep parquet and renders heatmaps (Sharpe + trade-count, with eligibility overlay) and a Sharpe-vs-trades scatter into `--out-dir`, plus `REPORT.md` and `top_cells.csv`. `trader backtest-report` does the equivalent for a backtest run (equity + drawdown PNGs, best/worst trades). `trader dashboard` serves a local HTML index of saved sweep + backtest artifacts via `ThreadingHTTPServer` — no JS deps.

CI workflow was removed in commit `ec1b508` — local checks (`ruff check`, `ruff format --check`, `mypy`, `pytest`) are still wired via `pyproject.toml` and `.pre-commit-config.yaml`. Re-add `.github/workflows/ci.yml` from history if you want cloud CI back.

CLI quirks worth knowing:
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

- **Data source (`data_sources.py`).** `fetch_ohlcv(request)` is a thin wrapper over `AlpacaDataSource.fetch`; it returns the canonical schema `time, open, high, low, close, volume, tick_volume, spread, real_volume, symbol, timeframe, data_source`. Alpaca fills `tick_volume`/`real_volume`/`spread` with `pd.NA`. Time is always UTC.

For a top-to-bottom reference of the data pipeline (schemas, every indicator column, sample charts), see [DATA_FLOW.md](./DATA_FLOW.md).

- **Time is always UTC.** Don't introduce naive datetimes anywhere downstream.

- **Indicator pipeline (`indicators.py`).** Wraps the `ta` library (`add_all_ta_features`) and adds custom price-action, pivot/Fibonacci, and regime features. When neither `tick_volume` nor `volume` is present (a holdover from the parked FX path; rare with Alpaca), `_attach_volume_proxy` constructs an `analysis_volume` from range + abs return and flags it with `volume_is_proxy=True`. Always feed `analysis_volume` (not `volume`) into volume-based indicators.

- **Strategy contract (`strategies.py`).** `build_signal_frame` requires the columns in `REQUIRED_SIGNAL_COLUMNS` (notably `ema_20`, `ema_50`, `trend_adx`, `momentum_rsi`, `rolling_high_20/_low_20`, `atr_pct`). Strategies emit an integer `signal ∈ {-1, 0, 1}` plus `conviction_score`, `suggested_stop_loss_pct`, `suggested_take_profit_pct`. Four strategies exist: `ema_rsi_pullback`, `breakout`, `mean_reversion`, `momentum_trend`; add new ones to `SUPPORTED_STRATEGIES` and dispatch in `build_signal_frame`. `StrategyConfig` carries the knobs: `adx_threshold`, `long_rsi_floor`, `short_rsi_ceiling`, `pullback_tolerance`, `breakout_lookback`, `mean_reversion_zscore`, `momentum_lookback`, `momentum_roc_floor`, `atr_pct_floor`, `atr_pct_ceiling`.

- **Backtest (`backtest.py`).** Per-symbol vectorized backtest using `signal.shift(1)` for next-bar execution; exposure is derived from `risk_per_trade / stop_loss_pct` and capped by `max_leverage` (`risk.implied_notional_exposure`). Fees and slippage are modeled in basis points on turnover. The portfolio curve is the equal-weight mean of per-symbol returns and is appended to the equity frame with `symbol="PORTFOLIO"`. Each per-symbol curve also carries `benchmark_return / benchmark_equity / benchmark_drawdown` (buy-and-hold of the asset) for side-by-side comparison. This is *not* a tick-accurate broker simulator — don't claim it is.

- **Walk-forward + intra-bar exits.** `run_walk_forward_backtest(features, in_sample_fraction=0.7)` splits each symbol's history by time and runs a separate `run_backtest` on each half, tagging rows with `sample ∈ {in_sample, out_of_sample}` and prefixing metric keys (`in_sample_*`, `out_of_sample_*`). When `BacktestConfig.use_strategy_exits=True`, `_apply_strategy_exits` inspects intra-bar `high`/`low` against `suggested_stop_loss_pct` / `suggested_take_profit_pct` and overrides the close-to-close return for that bar; trades carry an `exit_reason ∈ {signal, stop_loss, take_profit}` column. With the flag off (default), behavior matches the next-bar-on-signal-change baseline.

- **Reporting modules.** `src/trader/sweep_report.py` (heatmaps + scatter for sweep parquets), `src/trader/backtest_report.py` (PNG charts + `REPORT.md` for a backtest run), and `src/trader/dashboard.py` (local `ThreadingHTTPServer` HTML index over saved artifacts) — all import matplotlib lazily so they remain importable without the `docs` group.

- **Risk module (`risk.py`) has two distinct code paths.** `position_size_from_stop` is broker-near sizing that respects per-symbol metadata (`trade_contract_size`, `volume_step`, `volume_min`, `volume_max`); it is currently unused by the CLI but kept for downstream callers and future broker integration. `implied_notional_exposure` is the abstract backtest-only sizing. Don't conflate them.

## Alpaca connection settings

Read from environment by `AlpacaConnectionSettings.from_env()` in `src/trader/alpaca.py`:

- `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` — required
- `ALPACA_PAPER` (bool, default `true`)
- `ALPACA_DATA_FEED` (`iex` default; `sip` requires the paid tier)

Symbol routing in `AlpacaClient.copy_rates`: a `/` in the symbol (`BTC/USD`) routes to `CryptoHistoricalDataClient`; otherwise `StockHistoricalDataClient`. `DEFAULT_ALPACA_SYMBOLS` covers a handful of liquid US equities — pass `--symbols BTC/USD ETH/USD` (or similar) for crypto.

`.env.example` is the authoritative list of environment variables.

## Tests

`pytest.ini_options.pythonpath = ["src"]` is set in `pyproject.toml`, so tests can `from trader.x import y` without installing the package. Tests under `tests/` are pure-pandas and don't require any external service.
