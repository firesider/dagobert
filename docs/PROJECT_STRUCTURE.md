# Project Structure

This repository uses a standard `src/` layout. Source code, tests, generated
research outputs, documentation assets, scripts, and notebooks are kept in
separate top-level directories.

## Source Code

| Path | Purpose |
|---|---|
| `src/trader/alpaca.py` | Alpaca historical data client and canonical OHLCV normalization. |
| `src/trader/data_sources.py` | Thin market-data adapter layer. |
| `src/trader/indicators.py` | Technical indicator and feature engineering pipeline. |
| `src/trader/strategies.py` | Signal-generation strategies. |
| `src/trader/backtest.py` | Signal backtest engine, benchmark, walk-forward split, and exits. |
| `src/trader/risk.py` | Position sizing and risk helper functions. |
| `src/trader/pipeline.py` | High-level dataset build/save workflow. |
| `src/trader/research.py` | Dump/reload helpers for notebook exploration. |
| `src/trader/sweep.py` | Parameter sweep and ranking logic. |
| `src/trader/backtest_report.py` | Backtest report generation from saved artifacts. |
| `src/trader/sweep_report.py` | Sweep report generation from saved sweep results. |
| `src/trader/dashboard.py` | Local read-only dashboard for saved artifacts. |
| `src/trader/cli.py` | CLI entrypoint that wires the workflows together. |
| `src/trader/config.py` | Project defaults and timeframe/symbol helpers. |

## Tests

`tests/` mirrors the main behavior surfaces:

- data loading and normalization
- indicator pipeline
- strategies and backtest behavior
- risk helpers
- reports, sweep logic, and dashboard discovery

Python bytecode caches under `tests/__pycache__/` are generated artifacts and
should not be committed.

## Generated Outputs

`data/` is reserved for generated research artifacts:

- datasets and latest snapshots
- signal frames
- backtest equity/trades/metrics
- sweep results and winner files
- dashboard-readable outputs

Only `data/.gitkeep` belongs in version control. Everything else under `data/`
is ignored.

## Documentation And Assets

| Path | Purpose |
|---|---|
| `README.md` | Main user-facing guide. |
| `DATA_FLOW.md` | Detailed data-flow reference. |
| `docs/img/` | Static images referenced by documentation. |
| `docs/PROJECT_STRUCTURE.md` | This layout reference. |
| `CLAUDE.md` | Agent/session guidance, not runtime code. |

## Scripts And Notebooks

| Path | Purpose |
|---|---|
| `scripts/render_data_flow_charts.py` | Regenerates documentation chart images. |
| `notebooks/` | Notebook exploration entrypoints. |
| `Learning_Materials/` | Archived learning/reference material; not imported by the package. |

## Current Cleanup Notes

- `poetry.lock` still contains historical MT5/Yahoo package entries although
  `pyproject.toml` no longer declares those dependencies. Refresh the lock file
  with Poetry when dependency changes are next allowed.
- `Learning_Materials/` contains old MetaTrader examples. It is reference-only
  and excluded from linting.
