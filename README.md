# Dagobert Trader Workbench

Ein kleines Trading-Repo mit klaren Schichten:

- `research`: Daten, Features, Signale, Backtests
- `broker`: MT5-Integration und Risiko-Helfer
- `demo`: Demo-Account-Pipeline, Observability, Dashboard
- `examples`: sehr einfache Lern- und Showcase-Skripte
- `apps`: alle offiziellen Einstiegspunkte

Die wichtigste Aufräumregel in diesem Repo ist jetzt: Fachlogik bleibt im Paket, ausführbare Skripte liegen gesammelt unter [src/trader/apps](/Users/fabian/Python/finance/dagobert/src/trader/apps).

## Struktur

```text
src/trader/
├── apps/       # offizielle Einstiegspunkte
├── research/   # Daten, Features, Signale, Backtests
├── broker/     # MT5 + Risiko
├── demo/       # kompletter Demo-Workflow
├── examples/   # kleine, didaktische Skripte
└── *.py        # nur noch Compatibility-Wrapper
```

Die Dateien direkt unter `src/` bleiben nur als Legacy-Wrapper für alte `python src/...` Aufrufe. Neue Einstiege liegen in `src/trader/apps/`.

## Setup

```bash
conda env create -f environment.yml
conda activate trader
python -m pip install poetry==2.3.2
poetry install --with dev
```

Für MT5 unter Windows:

```bash
poetry install --with dev,mt5
```

Tests:

```bash
pytest -q
```

## Hauptbefehle

### Kern-CLI

```bash
trader dataset --symbols EURUSD GBPUSD USDJPY --timeframe 1h --bars 1500
trader signals --symbols EURUSD GBPUSD --timeframe 1h --strategy ema_rsi_pullback
trader backtest --symbols EURUSD GBPUSD USDJPY --timeframe 1h --bars 3000 --strategy breakout
trader mt5-account
trader mt5-symbols --asset-class forex
trader mt5-quote EURUSD
trader mt5-check-order EURUSD buy --equity 10000 --risk-fraction 0.01 --stop-loss-price 1.0950
```

### Demo-Workflow

```bash
trader-demo-pipeline --symbol EURUSD --source yfinance
trader-demo-pipeline --symbol EURUSD --source mt5
trader-demo-pipeline --symbol EURUSD --source mt5 --live --trade-volume 0.01

trader-demo-observability report --database data/demo_account_pipeline.sqlite
trader-demo-observability export-training --database data/demo_account_pipeline.sqlite --output data/retraining_examples.csv
trader-demo-observability retrain-model --database data/demo_account_pipeline.sqlite --output data/retrained_model.json

trader-demo-dashboard --database data/demo_account_pipeline.sqlite
```

### Einfache Beispiele

```bash
trader-example-train --symbol AAPL
trader-example-monitor --symbol AAPL --period 5d --interval 1m --poll-seconds 60 --max-checks 15
trader-example-review --symbol ALL

trader-eval-train-test
trader-eval-cv
trader-eval-report
```

### Ohne Poetry-Skripte

```bash
env PYTHONPATH=src python -m trader.apps.demo_account_pipeline --symbol EURUSD --source yfinance
env PYTHONPATH=src python -m trader.apps.demo_observability report --database data/demo_account_pipeline.sqlite
env PYTHONPATH=src python -m trader.apps.demo_dashboard --database data/demo_account_pipeline.sqlite
```

## Modulgrenzen

### `src/trader/research`

- [config.py](/Users/fabian/Python/finance/dagobert/src/trader/research/config.py)
- [data_sources.py](/Users/fabian/Python/finance/dagobert/src/trader/research/data_sources.py)
- [indicators.py](/Users/fabian/Python/finance/dagobert/src/trader/research/indicators.py)
- [strategies.py](/Users/fabian/Python/finance/dagobert/src/trader/research/strategies.py)
- [pipeline.py](/Users/fabian/Python/finance/dagobert/src/trader/research/pipeline.py)
- [backtest.py](/Users/fabian/Python/finance/dagobert/src/trader/research/backtest.py)

### `src/trader/broker`

- [mt5.py](/Users/fabian/Python/finance/dagobert/src/trader/broker/mt5.py)
- [risk.py](/Users/fabian/Python/finance/dagobert/src/trader/broker/risk.py)

### `src/trader/demo`

- [account_pipeline.py](/Users/fabian/Python/finance/dagobert/src/trader/demo/account_pipeline.py)
- [observability.py](/Users/fabian/Python/finance/dagobert/src/trader/demo/observability.py)
- [dashboard.py](/Users/fabian/Python/finance/dagobert/src/trader/demo/dashboard.py)

### `src/trader/examples`

- [simple_rich_workflows.py](/Users/fabian/Python/finance/dagobert/src/trader/examples/simple_rich_workflows.py)
- [hardcoded_eval_workflows.py](/Users/fabian/Python/finance/dagobert/src/trader/examples/hardcoded_eval_workflows.py)

### `src/trader/apps`

Nur Einstiegspunkte. Keine Fachlogik.

## Regeln für neuen Code

- Neue Fachlogik nie in `apps/`.
- Neue Datenquellen in `research/data_sources.py`.
- Neue Features in `research/indicators.py`.
- Neue Strategien in `research/strategies.py`.
- Neue Backtest-Logik in `research/backtest.py`.
- Neue MT5-Helfer in `broker/mt5.py`.
- Neue Risiko-Logik in `broker/risk.py`.
- Neue Demo-Bausteine in `demo/`.
- Neue kurze Lernskripte in `examples/`.

## Wichtige Hinweise

- Live-MT5-Ausführung benötigt `MetaTrader5` und ein lokal laufendes MT5-Terminal. In diesem Repo ist das für Windows gedacht.
- Die Demo-Datenbank liegt standardmäßig unter `data/demo_account_pipeline.sqlite`.
- Die `yfinance`-Beispiele benötigen Internetzugriff.
- Die alten Modulnamen unter `src/trader/*.py` bleiben als dünner Compatibility-Layer bestehen, damit bestehende Imports nicht sofort brechen.

## Weitere Doku

- [REPO_LAZY_READER.md](/Users/fabian/Python/finance/dagobert/docs/REPO_LAZY_READER.md)
- [DEMO_ACCOUNT_WORKFLOW_COMPACT.md](/Users/fabian/Python/finance/dagobert/docs/DEMO_ACCOUNT_WORKFLOW_COMPACT.md)
- [DEMO_ACCOUNT_WORKFLOW_WIKI.md](/Users/fabian/Python/finance/dagobert/docs/DEMO_ACCOUNT_WORKFLOW_WIKI.md)
