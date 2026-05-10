# Trader Workbench

> **Datenfluss-Dokumentation:** [DATA_FLOW.md](./DATA_FLOW.md) erklaert Schritt fuer Schritt, woher alle Daten kommen, wie sie transformiert werden und wo sie landen — inklusive Mermaid-Diagramme, Schema-Tabellen und Beispielcharts.

`trader` ist ein kleines, praxisnahes Research-Repo fuer **US-Aktien und Crypto** ueber die Alpaca-API. Der Fokus liegt auf:

- historischen Marktdaten
- technischen Features
- regelbasierten Signalen
- schnellen Signal-Backtests

Bewusst pragmatisch: lokal benutzbar, offline testbar, mit sauberer CLI und ausfuehrlicher Datenfluss-Doku. Das Repo ist kein OMS/EMS und kein tickgenauer Exchange-Simulator — fuer das Live-Trading brauchst du eine Broker-Schicht, die hier nicht enthalten ist.

> Hinweis: das Repo wrappte frueher zusaetzlich MetaTrader 5 (FX/CFD-Broker) und Yahoo Finance. Diese Pfade wurden entfernt; siehe `git log` fuer die historische Implementation.

## Projektstruktur

```text
.
├── .env.example
├── environment.yml
├── poetry.toml
├── pyproject.toml
├── README.md
├── DATA_FLOW.md
├── data/
├── src/trader/
│   ├── __init__.py
│   ├── alpaca.py
│   ├── backtest.py
│   ├── cli.py
│   ├── config.py
│   ├── data_sources.py
│   ├── indicators.py
│   ├── pipeline.py
│   ├── risk.py
│   └── strategies.py
└── tests/
```

## Schnellstart

### 1. Environment bauen

```bash
conda env create -f environment.yml
conda activate trader
python -m pip install poetry==2.3.2
```

`poetry.toml` ist so gesetzt, dass Poetry in das aktive `conda`-Environment installiert und kein extra virtuelles Environment erzeugt.

### 2. Abhaengigkeiten installieren

```bash
poetry install --with dev,alpaca
```

Optional fuer Daten-Pipeline-Charts (`scripts/render_data_flow_charts.py`):

```bash
poetry install --with dev,alpaca,docs
```

### 3. Alpaca-Keys eintragen

Kopiere die Vorlage und trage Paper-Keys aus https://app.alpaca.markets/ ein:

```bash
cp .env.example .env
set -a; source .env; set +a
```

### 4. Testen

```bash
pytest -q
ruff check .
mypy
```

### 5. Erste Daten ziehen

```bash
trader dataset --symbols AAPL MSFT SPY --timeframe 1h --bars 1500
```

### 6. Signale bauen

```bash
trader signals --symbols AAPL --strategy ema_rsi_pullback --timeframe 1h
```

### 7. Schnellen Backtest laufen lassen

```bash
trader backtest --symbols AAPL SPY --strategy breakout --bars 3000 --timeframe 1d
```

## CLI-Referenz

### `trader dataset`

Baut das komplette Indikator-Feature-Set.

```bash
trader dataset --symbols AAPL SPY --timeframe 1h --bars 2000
trader dataset --symbols BTC/USD ETH/USD --timeframe 1d --bars 500
```

### `trader signals`

Baut Signale auf Basis der Features.

```bash
trader signals --symbols AAPL --strategy breakout --timeframe 4h --bars 2500
```

### `trader backtest`

Fuehrt einen schnellen Signal-Backtest aus und schreibt Equity-Kurve, Trades und Kennzahlen.

```bash
trader backtest --symbols AAPL SPY MSFT --strategy ema_rsi_pullback --timeframe 1h
```

## Python-Beispiele

### Historische Bars

```python
from trader.data_sources import FetchRequest, fetch_ohlcv

frame = fetch_ohlcv(FetchRequest(symbol="AAPL", timeframe="1h", bars=1000))
print(frame.tail())
```

### Features und Signale

```python
from trader.pipeline import build_dataset
from trader.strategies import StrategyConfig, build_signal_frame, latest_signals

dataset = build_dataset(["AAPL", "SPY"], timeframe="1h", bars=2000)
signals = build_signal_frame(dataset, StrategyConfig(strategy="ema_rsi_pullback"))
print(latest_signals(signals))
```

## Symbol-Konventionen

`AlpacaClient.copy_rates` routet anhand des Symbol-Strings:

- ohne `/` (`AAPL`, `MSFT`, `SPY`) → `StockHistoricalDataClient`
- mit `/` (`BTC/USD`, `ETH/USD`) → `CryptoHistoricalDataClient`

`DEFAULT_ALPACA_SYMBOLS` deckt eine Handvoll liquider US-Aktien ab; Crypto-Paare gibst du via `--symbols` an.

## Strategien

Beide Strategien sind bewusst einfache, nachvollziehbare Baselines — kein Versprechen auf Alpha.

### `ema_rsi_pullback`

- Trendfilter: `ema_20` vs. `ema_50`
- Staerke: `trend_adx` ueber `--adx-threshold`
- Pullback: relative Distanz zur EMA20 unter `--pullback-tolerance`
- Momentum: RSI ueber `--long-rsi-floor` (Long) / unter `--short-rsi-ceiling` (Short)

### `breakout`

- 20-Bar Hoch/Tief als Trigger (`rolling_high_20` / `rolling_low_20`)
- ADX-Filter wie oben

> **Heads-up:** Die Defaults (`pullback_tolerance=0.0025`, `long_rsi_floor=52`, ATR-Clip `[0.003, 0.03]`) wurden urspruenglich auf FX kalibriert. Auf US-Aktien und Crypto feuern sie seltener oder bei anderen Skalen. Eine datengetriebene Kalibrierung auf Alpaca-Historie ist geplant; bis dahin ueber CLI-Flags ueberschreiben.

## Backtest-Mechanik

- Per-Symbol vektorisiert; `signal.shift(1)` fuer Next-Bar-Execution
- Position size = `risk_per_trade / stop_loss_pct`, gedeckelt auf `--max-leverage`
- Gebuehren und Slippage in Basispunkten auf den Turnover
- Portfoliokurve = gleichgewichteter Mittelwert der Per-Symbol-Returns, im Equity-Frame als `symbol="PORTFOLIO"`

Das ist *kein* tickgenauer Broker-Simulator. Ergebnisse sind als Sanity-Checks zu lesen, nicht als Backtest-Wahrheit.

## Risikomodul

`risk.py` enthaelt zwei Pfade, die nicht vermischt werden duerfen:

1. `position_size_from_stop` — broker-nahe Lotberechnung mit Symbol-Metadaten (`trade_contract_size`, `volume_step`, `volume_min`, `volume_max`). Aktuell ungenutzt; bleibt fuer zukuenftige Broker-Integration.
2. `implied_notional_exposure` — abstrakte Backtest-Sizing, die der Backtest verwendet.

## Zeit und Zeitzonen

Alle Bar-Zeiten sind UTC. `_normalize_frame` (`alpaca.py`) konvertiert vor dem Feature-Building, alles downstream rechnet in UTC.

## Grenzen

- Kein OMS/EMS, keine Live-Order-Pfade.
- Backtest ist vektorisiert, nicht tickgenau.
- Keine Slippage-Modellierung jenseits konstanter Basispunkte.
- Strategie-Defaults stammen aus dem alten FX-Workflow und sind nicht auf US-Aktien/Crypto kalibriert.

## Weiterlesen

- [DATA_FLOW.md](./DATA_FLOW.md) — vollstaendige Daten-Pipeline mit Schemas, Diagrammen und Beispielcharts
- [CLAUDE.md](./CLAUDE.md) — Hinweise fuer Claude Code Sessions, die in diesem Repo arbeiten
