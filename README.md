# Trader Workbench

`trader` ist jetzt kein reines Forex-Feature-Skript mehr, sondern ein kleines, praxisnahes Trading-Repo fuer:

- historische Marktdaten
- technische Features
- regelbasierte Signale
- schnelle Signal-Backtests
- MetaTrader-5-Konto- und Symbol-Inspektion
- Vorpruefung von Orders inklusive Margin- und Risiko-Schaetzung

Der Fokus ist bewusst pragmatisch:

- lokal benutzbar
- offline testbar
- MT5-freundlich
- mit sauberer CLI
- mit einer README, die MetaTrader 5 nicht nur erwaehnt, sondern erklaert

## Was dieses Repo konkret kann

Das Repo deckt drei typische Arbeitsbereiche ab:

1. Research:
   OHLCV-Daten holen, Indikatoren bauen, Signale ableiten, Snapshots exportieren.
2. Simulation:
   Signale ueber einen einfachen, schnellen Backtest pruefen.
3. Broker-nahe Arbeit mit MT5:
   Kontoinfos, Symbolkatalog, Quotes, offene Positionen, Orders und `order_check()` aus Python verwenden.

Die wichtigsten Befehle sind:

```bash
trader dataset
trader signals
trader backtest
trader mt5-account
trader mt5-symbols
trader mt5-quote EURUSD
trader mt5-check-order EURUSD buy --equity 10000 --risk-fraction 0.01 --stop-loss-price 1.0950
```

## Projektstruktur

```text
.
├── .env.example
├── environment.yml
├── poetry.toml
├── pyproject.toml
├── README.md
├── data/
├── src/trader/
│   ├── __init__.py
│   ├── backtest.py
│   ├── cli.py
│   ├── config.py
│   ├── data_sources.py
│   ├── indicators.py
│   ├── mt5.py
│   ├── pipeline.py
│   ├── risk.py
│   └── strategies.py
└── tests/
```

## Schnellstart

### 1. Environment bauen

Mit `conda`:

```bash
conda env create -f environment.yml
conda activate trader
python -m pip install poetry==2.3.2
```

`poetry.toml` ist so gesetzt, dass Poetry in das aktive `conda`-Environment installiert und kein extra virtuelles Environment erzeugt.

### 2. Abhaengigkeiten installieren

Auf macOS oder Linux:

```bash
poetry install --with dev
```

Auf Windows mit MT5-Python-Anbindung:

```bash
poetry install --with dev,mt5
```

### 3. Testen

```bash
pytest -q
```

### 4. Erste Daten ziehen

```bash
trader dataset --symbols EURUSD GBPUSD USDJPY --timeframe 1h --bars 1500
```

### 5. Signale bauen

```bash
trader signals --symbols EURUSD GBPUSD --timeframe 1h --strategy ema_rsi_pullback
```

### 6. Schnellen Backtest laufen lassen

```bash
trader backtest --symbols EURUSD GBPUSD USDJPY --timeframe 1h --bars 3000 --strategy breakout
```

## Die Rolle von MetaTrader 5 in diesem Repo

MetaTrader 5 ist in diesem Repo nicht nur eine optionale Datenquelle. Es ist die Broker-nahe Schicht fuer:

- Konto- und Terminalstatus
- Symbol-Discovery
- Tick- und Quotendaten
- historische Bars
- Margin- und Profit-Schaetzung
- Vorpruefung von Orders ueber `order_check()`

Dieses Repo trennt dabei sauber zwischen:

- Research-Workflow: Daten, Features, Signale, Backtest
- Broker-Workflow: MT5-Terminal, Konto, Symbolregeln, Quotes, Order-Checks

Genau diese Trennung ist wichtig. Viele Trading-Repos vermischen das alles in einem Notebook und werden dadurch spaeter unwartbar.

## MetaTrader 5 verstehen: Plattform, Broker, Konto, Python

Wenn jemand "ich nutze MT5" sagt, kann das vier verschiedene Dinge bedeuten:

1. Die Desktop-Plattform ist installiert.
2. Ein Broker-Konto ist in der Plattform eingeloggt.
3. Das konkrete Broker-Server-Setup stellt bestimmte Symbole bereit.
4. Die Python-Anbindung `MetaTrader5` verbindet Python per IPC mit dem lokalen Terminal.

Fuer die Python-Nutzung muessen diese Ebenen zusammenpassen:

- ein lokales MetaTrader-5-Terminal
- ein funktionierender Broker-Login
- die passende Python-Bibliothek
- das gewuenschte Symbol im Terminal bzw. in Market Watch

Das Repo kapselt genau diesen Teil in `src/trader/mt5.py`.

## Was MetaTrader 5 offiziell ist

Nach den offiziellen MetaTrader-5-Seiten ist MT5 eine Multi-Asset-Plattform fuer Forex, Stocks und Futures. In der Hilfe wird ausserdem beschrieben, dass ueber die Plattform neben Forex auch Optionen, Futures und Aktien gehandelt werden koennen. Die Plattform unterstuetzt sowohl Hedging als auch Netting, bietet Market Depth, historische Daten, News, Economic Calendar, technische Analyse und algorithmischen Handel.

Wichtig ist aber:

- Die Plattform ist multi-asset.
- Das konkrete Asset-Universum kommt trotzdem vom Broker.
- Nicht jeder Broker schaltet jede Asset-Klasse frei.
- Symbolnamen, Suffixe, Spreads, Marginregeln und Lotgroessen unterscheiden sich von Broker zu Broker.

## Welche Assets es in MT5 "gibt"

Die wichtigste Realitaet zuerst:

Es gibt in MT5 keine globale, universelle, fuer alle Benutzer identische Symbol-Liste.

Was du handeln kannst, haengt ab von:

- Broker
- Server
- Land und Regulierung
- Kontotyp
- Demo vs. Live
- Freigeschalteten Instrumenten

### Typische Asset-Klassen, die du in MT5 antreffen kannst

Offiziell ist MT5 klar als Multi-Asset-Plattform fuer Forex, Stocks und Futures positioniert. In realen Broker-Setups findest du haeufig zusaetzlich:

| Asset-Klasse | Typische Beispiele | Wichtige Hinweise |
| --- | --- | --- |
| Forex | `EURUSD`, `GBPUSD`, `USDJPY` | Spot-FX nutzt meist Tick-Volumen statt Boersenvolumen |
| Indizes / Index-CFDs | `US500`, `NAS100`, `GER40`, `UK100` | Symbolnamen und Suffixe variieren stark je Broker |
| Metalle | `XAUUSD`, `XAGUSD` | Vertragsgroesse und Pip-Wert unbedingt per Symbolinfo pruefen |
| Energie | `XBRUSD`, `XTIUSD`, `NGAS` | Handelszeiten und Rollovers beachten |
| Aktien | `AAPL`, `TSLA`, `BMW`, `VOW3` | Je nach Broker echte Boersenanbindung oder CFD-Abbildung |
| Futures | `ES`, `NQ`, `CL`, `GC` oder broker-spezifische Namen | Verfall, Tickgroesse, Margin und Sessions sind zentral |
| ETFs | `SPY`, `QQQ`, `EEM` oder CFD-Varianten | Nicht jeder MT5-Broker bietet ETFs an |
| Bonds | Staatsanleihen, Treasury- oder Bund-Symbole | Oft nur bei spezialisierten Brokern sichtbar |
| Optionen | broker-abhaengige Optionssymbole | Nicht Standard bei jedem MT5-Setup |
| Krypto / Crypto-CFDs | `BTCUSD`, `ETHUSD`, `SOLUSD` | Angebot ist stark regulierungs- und brokerabhaengig |
| Agricultural / Commodities | `COFFEE`, `CORN`, `SUGAR`, `WHEAT` | Meist als CFD oder Futures-nahe Produkte |

### Der entscheidende Punkt

Du solltest nie aus Dokumentation ableiten, dass ein bestimmtes Symbol wirklich in deinem Setup vorhanden ist.

Stattdessen:

```bash
trader mt5-symbols
trader mt5-symbols --asset-class forex
trader mt5-symbols --contains gold
trader mt5-symbols --group "*USD*"
```

Damit bekommst du deinen realen Broker-Katalog statt einer theoretischen Liste.

## Warum Symbolnamen in MT5 oft verwirrend sind

MT5-Symbole sind broker-spezifisch. Beispiele:

- `EURUSD`
- `EURUSD.m`
- `EURUSD.pro`
- `GER40.cash`
- `US30`
- `BTCUSD`
- `XAUUSD`

Das bedeutet:

- gleiche Asset-Idee, aber anderer Symbolname
- andere Kontraktgroesse
- andere minimale Lotgroesse
- andere Stop-Level
- andere Handelszeiten

Deshalb liest dieses Repo Symbolinformationen direkt ueber MT5 aus, statt Annahmen zu treffen.

## Welche Symbol-Informationen du wirklich verstehen musst

Wenn du ein Instrument in MT5 handeln oder sauber analysieren willst, sind diese Felder entscheidend:

| Feld | Bedeutung | Warum es wichtig ist |
| --- | --- | --- |
| `name` | Exakter Symbolname | Du brauchst den echten Broker-Namen |
| `path` | Gruppierung im Terminal | Sehr hilfreich fuer Asset-Klassen und Broker-Struktur |
| `description` | Menschlich lesbarer Name | Gut fuer schnelle Identifikation |
| `digits` | Anzahl Nachkommastellen | Relevant fuer Preisformat und Stop-Berechnung |
| `point` | Kleinste Preis-Einheit | Basis fuer Tick/Pip-nahe Logik |
| `trade_contract_size` | Kontraktgroesse | Kritisch fuer Risiko und Lot-Sizing |
| `volume_min` | Minimale Lotgroesse | Order darf darunter nicht rausgehen |
| `volume_step` | Schrittgroesse | Lots muessen exakt auf diesen Schritt gerundet werden |
| `volume_max` | Maximale Lotgroesse | Obere Broker-Grenze |
| `currency_base` | Basiswaehrung des Symbols | Bei FX wichtig |
| `currency_profit` | Profitwaehrung | PnL-Interpretation |
| `currency_margin` | Marginwaehrung | Margin-Logik |
| `trade_mode` | Ob und wie handelbar | Manche Symbole sind nur sichtbar, aber nicht handelbar |
| `trade_stops_level` | Mindestabstand fuer Stops | Wichtig fuer `sl` und `tp` |
| `filling_mode` | Erlaubter Fill-Typ | Relevant fuer `order_check()` und `order_send()` |
| `order_mode` | Erlaubte Ordertypen | Nicht jedes Symbol erlaubt jede Orderart |

Mit dem Repo:

```bash
trader mt5-quote EURUSD
```

oder direkt in Python:

```python
from trader.mt5 import MetaTrader5Client

with MetaTrader5Client.from_env() as client:
    info = client.symbol_info("EURUSD")
    print(info["trade_contract_size"])
    print(info["volume_step"])
```

## MT5 und Python: wie die offizielle Integration funktioniert

Die offizielle Python-Integration stellt laut MQL5-Dokumentation unter anderem diese Kernfunktionen bereit:

| Funktion | Zweck |
| --- | --- |
| `initialize()` | Verbindung zum lokalen MT5-Terminal aufbauen |
| `login()` | Auf ein Handelskonto verbinden |
| `shutdown()` | Verbindung sauber schliessen |
| `account_info()` | Kontoinformationen lesen |
| `terminal_info()` | Terminalzustand lesen |
| `symbols_get()` | Symbolkatalog lesen |
| `symbol_info()` | Detaildaten eines Symbols lesen |
| `symbol_info_tick()` | Letzten Tick lesen |
| `symbol_select()` | Symbol in Market Watch aktivieren |
| `copy_rates_from_pos()` | Historische Bars holen |
| `copy_ticks_range()` | Tick-Historie holen |
| `positions_get()` | Offene Positionen lesen |
| `orders_get()` | Aktive Orders lesen |
| `order_calc_margin()` | Margin fuer geplante Orders schaetzen |
| `order_calc_profit()` | Erwartete PnL fuer Preis-Szenarien schaetzen |
| `order_check()` | Order vor Ausfuehrung pruefen |
| `order_send()` | Order an den Server schicken |

Dieses Repo nutzt genau diese MT5-Ideen in einer etwas saubereren Python-Schicht.

## Wichtige Installationsrealitaet fuer MetaTrader5-Python

Stand 21. April 2026:

- Auf PyPI war die offizielle `MetaTrader5`-Version `5.0.5735` gelistet.
- Die bereitgestellten Wheels waren Windows-x86-64-Builds.

Praktische Konsequenz:

- Windows ist der normale Zielpfad fuer die offizielle native MT5-Python-Nutzung.
- Auf macOS oder Linux kannst du das Repo trotzdem sinnvoll fuer Research und Backtests nutzen.
- Wenn MT5-Python lokal nicht verfuegbar ist, faellt dieses Repo fuer historische Forex-Daten automatisch auf `yfinance` zurueck.

Das ist genau der Grund, warum `MetaTrader5` hier als optionale Poetry-Group `mt5` gefuehrt wird.

## MT5-Konfiguration im Repo

Lege deine Zugangsdaten ueber Environment-Variablen fest:

```bash
export MT5_PATH="C:\\Program Files\\MetaTrader 5\\terminal64.exe"
export MT5_LOGIN="12345678"
export MT5_PASSWORD="replace-me"
export MT5_SERVER="Broker-Server"
export MT5_TIMEOUT="60000"
export MT5_PORTABLE="false"
```

Oder nutze die Vorlage in `.env.example`.

Verwendete Variablen:

- `MT5_PATH`
- `MT5_LOGIN`
- `MT5_PASSWORD`
- `MT5_SERVER`
- `MT5_TIMEOUT`
- `MT5_PORTABLE`

## Warum dieses Repo bei Datenquellen zwischen MT5 und yfinance unterscheidet

### MT5

Vorteile:

- brokernahe Daten
- echte Symbolnamen
- Tick-Volumen
- Spread-Felder
- fuer spaetere Orderlogik und Live-Checks besser geeignet

Nachteile:

- lokales Terminal noetig
- Brokerkonto noetig
- Python-Bibliothek praktisch Windows-zentriert

### yfinance

Vorteile:

- schnell
- bequem
- fuer Research und Smoke-Tests lokal sehr praktisch
- laeuft ohne Broker-Terminal

Nachteile:

- nicht brokergleich
- nicht fuer Execution gedacht
- bei Spot-FX ist Volumen oft leer oder nur begrenzt nutzbar

### Was dieses Repo macht

Die Datenquellenlogik ist:

- `source=mt5`: nur MT5
- `source=yfinance`: nur Yahoo Finance
- `source=auto`: zuerst MT5, sonst Fallback auf `yfinance`

## Was die Feature-Pipeline erzeugt

Das Repo baut aus OHLCV-Daten ein breites TA-Set mit:

- Trend-Indikatoren
- Momentum-Indikatoren
- Volatilitaets-Indikatoren
- volumenbezogenen Indikatoren
- Price-Action-Features
- Pivot-Levels
- Fibonacci-Levels
- Rolling-Volatility- und Z-Score-Features
- Regime-Labels

Zusatzfeatures aus `indicators.py` sind unter anderem:

- `ema_20`
- `ema_50`
- `sma_50`
- `sma_200`
- `ema_20_over_50`
- `return_1`
- `log_return_1`
- `range_pct`
- `body_pct`
- `upper_wick_pct`
- `lower_wick_pct`
- `atr_pct`
- `realized_vol_20`
- `realized_vol_60`
- `close_zscore_20`
- `rolling_high_20`
- `rolling_low_20`
- `pivot_point`
- `pivot_support_1`
- `pivot_resistance_1`
- `fib_618_20`
- `trend_regime`
- `trend_strength_regime`

## Forex-spezifische Datenrealitaet

### Volumen

Bei Spot-FX gibt es kein zentrales Boersenvolumen wie bei Aktien.

Deshalb gilt:

- MT5 liefert oft `tick_volume`
- `real_volume` ist nicht fuer jedes Symbol sinnvoll befuellt
- `yfinance` hat bei FX oft gar kein belastbares Volumen

Das Repo loest das so:

- wenn Tick- oder Realvolumen brauchbar ist, wird es genutzt
- sonst wird ein `analysis_volume`-Proxy gebaut
- `volume_is_proxy` zeigt an, ob ein Proxy verwendet wurde

### Spread

Wenn Daten aus MT5 kommen, ist `spread` besonders wertvoll fuer:

- Liquiditaetsfilter
- Session-Vergleiche
- Slippage-Schaetzung
- Vorsicht bei News-Zeiten

## Die integrierten Strategien

Die Strategien sind bewusst einfache, nachvollziehbare Baselines. Sie sind kein Versprechen auf Alpha, sondern ein sauberer Startpunkt.

### `ema_rsi_pullback`

Logik:

- Trendfilter ueber `ema_20` vs. `ema_50`
- Staerkefilter ueber `ADX`
- Pullback-Naehe an die schnelle EMA
- RSI-Bestaetigung

Typische Nutzung:

```bash
trader signals --symbols EURUSD GBPUSD --strategy ema_rsi_pullback --timeframe 1h
```

### `breakout`

Logik:

- Trend-/Staerkefilter ueber `ADX`
- Breakout ueber rollierende Hochs und Tiefs
- Lookback konfigurierbar ueber `--breakout-lookback`

Typische Nutzung:

```bash
trader signals --symbols EURUSD GBPUSD --strategy breakout --breakout-lookback 20
```

## Wie der Backtest in diesem Repo funktioniert

Der Backtest in `backtest.py` ist absichtlich leichtgewichtig:

- Signale werden auf Bar-Ebene ausgewertet
- Positionen werden aus dem Signal abgeleitet
- Fees und Slippage werden in Basispunkten angenaehert
- Exponierung wird aus `risk_per_trade / stop_loss_pct` abgeleitet und durch `max_leverage` begrenzt

Das ist gut fuer:

- schnelle Strategie-Sanity-Checks
- Vergleich einfacher Regelwerke
- Pipeline-Regressionstests

Das ist nicht dasselbe wie:

- tickgenaue Broker-Simulation
- exakte Intrabar-Ausfuehrung
- echte Session-, Feiertags- oder Partial-Fill-Modellierung

Beispiel:

```bash
trader backtest \
  --symbols EURUSD GBPUSD USDJPY \
  --timeframe 1h \
  --bars 3000 \
  --strategy ema_rsi_pullback \
  --initial-capital 10000 \
  --risk-per-trade 0.01 \
  --stop-loss-pct 0.005 \
  --fee-bps 1 \
  --slippage-bps 1
```

Erzeugte Dateien:

- Equity-Kurve
- Trades als CSV
- Kennzahlen als JSON

## CLI-Referenz

### `trader dataset`

Baut das komplette Indikator-Feature-Set.

Beispiel:

```bash
trader dataset --symbols EURUSD GBPUSD USDJPY --timeframe 1h --bars 2000
```

### `trader signals`

Baut Signale auf Basis der Features.

Beispiel:

```bash
trader signals --symbols EURUSD GBPUSD --strategy breakout --timeframe 4h --bars 2500
```

### `trader backtest`

Fuehrt einen schnellen Signal-Backtest aus.

Beispiel:

```bash
trader backtest --symbols EURUSD GBPUSD USDJPY --strategy ema_rsi_pullback --timeframe 1h
```

### `trader mt5-account`

Liest:

- `account_info()`
- `terminal_info()`
- offene Positionen
- aktive Orders

Beispiel:

```bash
trader mt5-account
```

### `trader mt5-symbols`

Listet alle im Terminal sichtbaren Broker-Symbole und klassifiziert sie heuristisch in Asset-Klassen.

Beispiele:

```bash
trader mt5-symbols
trader mt5-symbols --asset-class forex
trader mt5-symbols --contains gold
trader mt5-symbols --group "*USD*"
```

### `trader mt5-quote`

Liest Symbol- und Tickdaten.

Beispiel:

```bash
trader mt5-quote EURUSD
```

### `trader mt5-check-order`

Baut einen Market-Order-Request, schaetzt Margin, prueft optional risiko-basiert die Lotgroesse und ruft `order_check()` auf.

Direkte Lotangabe:

```bash
trader mt5-check-order EURUSD buy --volume 0.10 --stop-loss-price 1.0950 --take-profit-price 1.1100
```

Lotgroesse aus Risiko:

```bash
trader mt5-check-order \
  EURUSD buy \
  --equity 10000 \
  --risk-fraction 0.01 \
  --stop-loss-price 1.0950 \
  --take-profit-price 1.1100
```

## Python-Beispiele

### Historische Bars via Repo-Abstraktion

```python
from trader.data_sources import FetchRequest, fetch_ohlcv

frame = fetch_ohlcv(
    FetchRequest(symbol="EURUSD", timeframe="1h", bars=1000),
    source="auto",
)
print(frame.tail())
```

### Features und Signale in Python

```python
from trader.pipeline import build_forex_dataset
from trader.strategies import StrategyConfig, build_signal_frame, latest_signals

dataset = build_forex_dataset(["EURUSD", "GBPUSD"], timeframe="1h", bars=2000, source="auto")
signals = build_signal_frame(dataset, StrategyConfig(strategy="ema_rsi_pullback"))
print(latest_signals(signals))
```

### MT5-Konto und Symbole

```python
from trader.mt5 import MetaTrader5Client

with MetaTrader5Client.from_env() as client:
    print(client.account_info())
    print(client.asset_summary())
    print(client.symbols().head())
```

## Risikomodell im Repo

`risk.py` enthaelt zwei unterschiedliche Logiken:

1. Live-/Broker-nahe Lotgroessen-Schaetzung:
   Lotgroesse aus Kontogroesse, Risikoanteil, Entry, Stop und Kontraktgroesse.
2. Backtest-Exposure:
   Ableitung einer groben Ziel-Exponierung aus `risk_per_trade` und `stop_loss_pct`.

Die Live-nahe Schaetzung ist besonders relevant fuer MT5, weil dort diese Felder vom Symbol abhangen:

- `trade_contract_size`
- `volume_step`
- `volume_min`
- `volume_max`

Darum berechnet das Repo Lotgroessen nicht aus harten Annahmen, sondern anhand realer Symbolinfos, wenn MT5 verfuegbar ist.

## Netting vs. Hedging

MT5 unterstuetzt laut offizieller Produktseite sowohl Hedging als auch Netting.

Praktisch bedeutet das:

- Forex-/CFD-Konten arbeiten oft hedging-orientiert
- Boersen- oder futures-nahe Konten arbeiten oft netting-orientiert

Das beeinflusst:

- wie Positionen dargestellt werden
- ob mehrere Long/Short-Positionen parallel moeglich sind
- wie du Orders und Positionslogik modellieren solltest

Dieses Repo liest Positionen und Orders aus, erzwingt aber kein bestimmtes Kontomodell auf Repo-Ebene.

## Ordertypen in MT5 kurz erklaert

Die offizielle Hilfe trennt:

- Market Orders
- Pending Orders
- Stop Loss / Take Profit als angehaengte Schutzorders

Pending Orders gibt es in MT5 in mehreren Varianten, typischerweise:

- Buy Limit
- Sell Limit
- Buy Stop
- Sell Stop
- Buy Stop Limit
- Sell Stop Limit

Dieses Repo exponiert in der CLI aktuell bewusst den sicheren Preflight-Pfad fuer Market Orders ueber `order_check()`. Das ist absichtlich konservativ.

## Zeit und Zeitzonen

Ein oft uebersehener Punkt:

- MT5 speichert Bar- und Tickzeiten in UTC
- Python-Datetimes sollten fuer MT5-Abfragen ebenfalls in UTC aufgebaut werden

Die offizielle `copy_ticks_range()`-Dokumentation weist genau auf diesen UTC-Punkt hin.

Im Repo werden Zeitspalten deshalb durchgaengig UTC-normalisiert.

## Grenzen dieses Repos

Dieses Repo ist funktional, aber bewusst nicht ueber-engineered.

Es ist nicht:

- ein vollstaendiges Portfolio-Management-System
- ein institutional-grade OMS/EMS
- ein tickgenauer Exchange-Simulator
- eine Garantie fuer Live-Execution-Kompatibilitaet bei jedem Broker

Besonders wichtig:

- Brokerregeln koennen `type_filling`, Stop-Distanzen, Lotgroessen und erlaubte Ordertypen beeinflussen
- `order_check()` ist immer sinnvoll, bevor du echtes `order_send()` verwendest
- Symbolnamen und Kontraktregeln niemals raten, sondern mit MT5 lesen
- `yfinance` ist fuer Research okay, aber kein Broker-Ersatz

## Empfohlener Arbeitsablauf

### Nur Research

```bash
trader dataset --source yfinance
trader signals --source yfinance
trader backtest --source yfinance
```

### Research plus brokernahe Symbolpruefung

```bash
trader mt5-account
trader mt5-symbols --asset-class forex
trader mt5-quote EURUSD
```

### Order-Idee vorpruefen

```bash
trader mt5-check-order EURUSD buy --equity 10000 --risk-fraction 0.01 --stop-loss-price 1.0950
```

## Offizielle Quellen

Die wichtigsten Punkte in dieser README wurden an offiziellen MetaTrader-/MQL5-Quellen gegengeprueft:

- MetaTrader 5 Produktseite:
  https://www.metatrader5.com/en/trading-platform
- MetaTrader 5 fuer Forex, Stocks und Futures:
  https://www.metatrader5.com/en/trading-platform/forex-stock-markets
- MT5 Hilfe / Trading Platform Manual:
  https://www.metatrader5.com/en/terminal/help
- Python-Integration Uebersicht:
  https://www.mql5.com/en/docs/integration/python_metatrader5
- `initialize()`:
  https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py
- `login()`:
  https://www.mql5.com/en/docs/python_metatrader5/mt5login_py
- `account_info()`:
  https://www.mql5.com/en/docs/python_metatrader5/mt5accountinfo_py
- `symbols_get()`:
  https://www.mql5.com/en/docs/python_metatrader5/mt5symbolsget_py
- `symbol_info()`:
  https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py
- `symbol_info_tick()`:
  https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfotick_py
- `copy_rates_from_pos()`:
  https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrompos_py
- `copy_ticks_range()`:
  https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py
- `positions_get()`:
  https://www.mql5.com/en/docs/python_metatrader5/mt5positionsget_py
- `orders_get()`:
  https://www.mql5.com/en/docs/python_metatrader5/mt5ordersget_py
- `order_calc_margin()`:
  https://www.mql5.com/en/docs/python_metatrader5/mt5ordercalcmargin_py
- `order_calc_profit()`:
  https://www.mql5.com/en/docs/python_metatrader5/mt5ordercalcprofit_py
- `order_check()`:
  https://www.mql5.com/en/docs/python_metatrader5/mt5ordercheck_py
- `order_send()`:
  https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py
- `shutdown()`:
  https://www.mql5.com/en/docs/python_metatrader5/mt5shutdown_py
- PyPI-Paket `MetaTrader5`:
  https://pypi.org/project/metatrader5/

## Kurzfazit

Wenn du nur einen Satz aus dieser README mitnimmst, dann diesen:

MetaTrader 5 ist multi-asset, aber dein reales handelbares Universum ist immer brokerabhaengig. Genau deshalb bietet dieses Repo nicht nur Theorie ueber Assets, sondern auch Kommandos, mit denen du dein tatsaechliches MT5-Setup direkt ausliest.
