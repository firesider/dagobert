"""Command line interface for dataset building, signals, and backtests on Alpaca data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from trader.alpaca import AlpacaError
from trader.backtest import BacktestConfig, run_backtest, run_walk_forward_backtest
from trader.backtest_report import render_backtest_report
from trader.config import DEFAULT_ALPACA_SYMBOLS, SUPPORTED_TIMEFRAMES
from trader.dashboard import DashboardConfig, serve_dashboard
from trader.pipeline import build_dataset, save_frame, save_latest_snapshot
from trader.research import dump_frames
from trader.strategies import (
    SUPPORTED_STRATEGIES,
    StrategyConfig,
    build_signal_frame,
    latest_signals,
)
from trader.sweep import (
    CRYPTO_COHORT,
    EQUITY_COHORT,
    SweepConfig,
    SweepGrid,
    persist_results,
    pick_winners,
    run_sweep,
)
from trader.sweep_report import render_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Trader Workbench fuer Research, Signale und Backtests auf Basis von Alpaca."
    )
    subparsers = parser.add_subparsers(dest="command")

    _add_dataset_parser(subparsers)
    _add_signals_parser(subparsers)
    _add_backtest_parser(subparsers)
    _add_backtest_report_parser(subparsers)
    _add_dashboard_parser(subparsers)
    _add_dump_frames_parser(subparsers)
    _add_sweep_parser(subparsers)
    _add_sweep_report_parser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Load .env from CWD if present; existing environment variables win.
    load_dotenv(override=False)

    args_list = list(argv if argv is not None else sys.argv[1:])
    if not args_list:
        args_list = ["dataset"]
    elif args_list[0].startswith("-") and args_list[0] not in {"-h", "--help"}:
        args_list = ["dataset", *args_list]

    args = build_parser().parse_args(args_list)

    try:
        if args.command == "dataset":
            return _run_dataset_command(args)
        if args.command == "signals":
            return _run_signals_command(args)
        if args.command == "backtest":
            return _run_backtest_command(args)
        if args.command == "backtest-report":
            return _run_backtest_report_command(args)
        if args.command == "dashboard":
            return _run_dashboard_command(args)
        if args.command == "dump-frames":
            return _run_dump_frames_command(args)
        if args.command == "sweep":
            return _run_sweep_command(args)
        if args.command == "sweep-report":
            return _run_sweep_report_command(args)
    except (RuntimeError, ValueError, AlpacaError) as exc:
        raise SystemExit(str(exc)) from exc

    raise SystemExit("Unbekannter CLI-Befehl.")


def _run_dataset_command(args: argparse.Namespace) -> int:
    dataset = build_dataset(
        symbols=args.symbols,
        timeframe=args.timeframe,
        bars=args.bars,
    )

    full_path = save_frame(dataset, Path(args.output))
    latest_path = save_latest_snapshot(
        dataset,
        full_path.with_name(f"{full_path.stem}_latest.csv"),
    )

    print(
        f"Dataset gespeichert: {len(dataset)} Zeilen fuer {dataset['symbol'].nunique()} Symbole in {full_path}"
    )
    _print_failures(dataset)
    print(f"Letzter Snapshot: {latest_path}")
    return 0


def _run_signals_command(args: argparse.Namespace) -> int:
    dataset = build_dataset(
        symbols=args.symbols,
        timeframe=args.timeframe,
        bars=args.bars,
    )
    signal_frame = build_signal_frame(dataset, _strategy_config_from_args(args))
    latest = latest_signals(signal_frame)

    full_path = save_frame(signal_frame, Path(args.output))
    latest_path = save_frame(latest, full_path.with_name(f"{full_path.stem}_latest.csv"))

    print(f"Signal-Frame gespeichert: {len(signal_frame)} Zeilen in {full_path}")
    _print_failures(dataset)
    print(f"Letztes Signal-Snapshot: {latest_path}")
    if not latest.empty:
        print(latest.to_string(index=False))
    return 0


def _run_backtest_command(args: argparse.Namespace) -> int:
    dataset = build_dataset(
        symbols=args.symbols,
        timeframe=args.timeframe,
        bars=args.bars,
    )
    strategy_config = _strategy_config_from_args(args)
    backtest_config = BacktestConfig(
        initial_capital=args.initial_capital,
        risk_per_trade=args.risk_per_trade,
        stop_loss_pct=args.stop_loss_pct,
        max_leverage=args.max_leverage,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        allow_short=not args.long_only,
        use_strategy_exits=args.use_strategy_exits,
    )
    if args.walk_forward:
        result = run_walk_forward_backtest(
            dataset,
            strategy_config=strategy_config,
            backtest_config=backtest_config,
            in_sample_fraction=args.in_sample_fraction,
        )
    else:
        result = run_backtest(
            dataset,
            strategy_config=strategy_config,
            backtest_config=backtest_config,
        )

    output_path = save_frame(result.equity_curve, Path(args.output))
    trades_path = save_frame(result.trades, output_path.with_name(f"{output_path.stem}_trades.csv"))
    metrics_path = output_path.with_name(f"{output_path.stem}_metrics.json")
    _write_json(metrics_path, result.metrics)

    print(f"Backtest-Eigenkapitalkurve gespeichert: {output_path}")
    print(f"Trades gespeichert: {trades_path}")
    print(f"Kennzahlen gespeichert: {metrics_path}")
    _print_failures(dataset)
    for key in (
        "ending_capital",
        "total_return",
        "annualized_return",
        "annualized_volatility",
        "sharpe",
        "max_drawdown",
        "trade_count",
        "win_rate",
        "profit_factor",
        "benchmark_total_return",
        "benchmark_sharpe",
        "out_of_sample_total_return",
        "out_of_sample_sharpe",
        "out_of_sample_benchmark_total_return",
        "out_of_sample_benchmark_sharpe",
    ):
        value = result.metrics.get(key)
        if value is not None:
            print(f"{key}: {value}")
    return 0


def _run_dump_frames_command(args: argparse.Namespace) -> int:
    frames = dump_frames(
        out_dir=args.out_dir,
        symbols=args.symbols,
        timeframe=args.timeframe,
        bars=args.bars,
        strategy_config=_strategy_config_from_args(args),
    )
    out = Path(args.out_dir)
    print(f"Frames gespeichert in {out}:")
    print(f"  ohlcv:      {len(frames.ohlcv)} Zeilen")
    print(f"  indicators: {len(frames.indicators)} Zeilen")
    print(f"  signals:    {len(frames.signals)} Zeilen")
    print(f"  trades:     {len(frames.trades)} Zeilen")
    print(f"  equity:     {len(frames.equity)} Zeilen")
    return 0


def _run_backtest_report_command(args: argparse.Namespace) -> int:
    out_dir = render_backtest_report(
        args.equity,
        args.out_dir,
        trades_path=args.trades,
        metrics_path=args.metrics,
    )
    print(f"Backtest-Report gespeichert: {out_dir / 'REPORT.md'}")
    return 0


def _run_dashboard_command(args: argparse.Namespace) -> int:
    serve_dashboard(
        DashboardConfig(
            data_dir=Path(args.data_dir),
            host=args.host,
            port=args.port,
        )
    )
    return 0


def _run_sweep_command(args: argparse.Namespace) -> int:
    grid = SweepGrid.quick() if args.quick else SweepGrid()
    timeframes: tuple[str, ...] = tuple(args.timeframes)

    if args.quick:
        equity_symbols = (args.equity_symbols or list(EQUITY_COHORT))[:2]
        crypto_symbols = (args.crypto_symbols or list(CRYPTO_COHORT))[:1]
    else:
        equity_symbols = tuple(args.equity_symbols or EQUITY_COHORT)
        crypto_symbols = tuple(args.crypto_symbols or CRYPTO_COHORT)

    config = SweepConfig(
        grid=grid,
        timeframes=timeframes,
        equity_symbols=tuple(equity_symbols),
        crypto_symbols=tuple(crypto_symbols),
        in_sample_fraction=args.in_sample_fraction,
        min_trades=args.min_trades,
    )

    cells = len(grid.cells())
    total_runs = cells * len(timeframes) * (len(config.equity_symbols) + len(config.crypto_symbols))
    print(
        f"Starte Sweep: {cells} Zellen × {len(timeframes)} Timeframes × "
        f"{len(config.equity_symbols) + len(config.crypto_symbols)} Symbole = {total_runs} Backtests."
    )

    results = run_sweep(config)
    if results.empty:
        raise SystemExit(
            "Sweep lieferte keine Ergebnisse — vermutlich konnten keine Daten geladen werden."
        )

    winners = pick_winners(results, min_trades=args.min_trades)
    results_path, winners_path = persist_results(results, winners, args.out_dir, config=config)

    print(f"Ergebnisse: {results_path}")
    print(f"Winners:    {winners_path}")
    print(f"Eligible cells: {len(winners)}")
    if not winners.empty:
        print(
            winners[
                [
                    "cohort",
                    "timeframe",
                    "pullback_tolerance",
                    "long_rsi_floor",
                    "atr_pct_floor",
                    "atr_pct_ceiling",
                    "robust_score",
                    "oos_sharpe_mean",
                    "oos_excess_return_mean",
                    "oos_max_drawdown_mean",
                    "oos_trade_count_mean",
                ]
            ].to_string(index=False)
        )
    return 0


def _run_sweep_report_command(args: argparse.Namespace) -> int:
    out_dir = render_report(args.input, args.out_dir, min_trades=args.min_trades)
    print(f"Sweep-Report gespeichert: {out_dir / 'REPORT.md'}")
    return 0


def _strategy_config_from_args(args: argparse.Namespace) -> StrategyConfig:
    return StrategyConfig(
        strategy=args.strategy,
        adx_threshold=args.adx_threshold,
        long_rsi_floor=args.long_rsi_floor,
        short_rsi_ceiling=args.short_rsi_ceiling,
        pullback_tolerance=args.pullback_tolerance,
        breakout_lookback=args.breakout_lookback,
        mean_reversion_zscore=args.mean_reversion_zscore,
        momentum_lookback=args.momentum_lookback,
        momentum_roc_floor=args.momentum_roc_floor,
    )


def _add_dataset_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "dataset",
        help="Lade Marktdaten via Alpaca und baue das Indikator-Feature-Set.",
    )
    _add_market_data_arguments(parser)
    parser.add_argument(
        "--output",
        default="data/dataset.parquet",
        help="Zielpfad fuer das vollstaendige Feature-Set",
    )


def _add_signals_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "signals",
        help="Erzeuge Handels-Signale auf Basis der Feature-Pipeline.",
    )
    _add_market_data_arguments(parser)
    _add_strategy_arguments(parser)
    parser.add_argument(
        "--output",
        default="data/signals.parquet",
        help="Zielpfad fuer das vollstaendige Signal-Frame",
    )


def _add_backtest_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "backtest",
        help="Fuehre einen einfachen Signal-Backtest aus.",
    )
    _add_market_data_arguments(parser)
    _add_strategy_arguments(parser)
    parser.add_argument("--initial-capital", type=float, default=10_000.0, help="Startkapital")
    parser.add_argument("--risk-per-trade", type=float, default=0.01, help="Risikoanteil pro Trade")
    parser.add_argument(
        "--stop-loss-pct", type=float, default=0.005, help="Annahme fuer Stop-Distanz"
    )
    parser.add_argument("--max-leverage", type=float, default=1.0, help="Maximale Ziel-Exponierung")
    parser.add_argument("--fee-bps", type=float, default=1.0, help="Gebuehren in Basispunkten")
    parser.add_argument("--slippage-bps", type=float, default=1.0, help="Slippage in Basispunkten")
    parser.add_argument("--long-only", action="store_true", help="Ignoriere Short-Signale.")
    parser.add_argument(
        "--use-strategy-exits",
        action="store_true",
        help="Nutze ATR-basierte Stop/Take-Profit-Level aus dem Signal-Frame.",
    )
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        help="Teile jeden Symbolverlauf in in-sample/out-of-sample und schreibe beide Segmente.",
    )
    parser.add_argument(
        "--in-sample-fraction",
        type=float,
        default=0.7,
        help="Anteil der Bars fuer in-sample im --walk-forward Modus.",
    )
    parser.add_argument(
        "--output",
        default="data/backtest_equity.csv",
        help="Zielpfad fuer Equity-Kurve und Portfolio-Serie",
    )


def _add_backtest_report_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "backtest-report",
        help="Rendere Markdown/PNG-Report aus gespeicherten Backtest-Dateien.",
    )
    parser.add_argument(
        "equity",
        help="Pfad zur Equity-Kurve (.csv, .parquet oder .json).",
    )
    parser.add_argument(
        "--trades",
        default=None,
        help="Optionaler Pfad zur Trades-Datei. Default: <equity_stem>_trades.csv",
    )
    parser.add_argument(
        "--metrics",
        default=None,
        help="Optionaler Pfad zur Metrics-JSON. Default: <equity_stem>_metrics.json",
    )
    parser.add_argument(
        "--out-dir",
        default="data/backtest_report",
        help="Zielordner fuer REPORT.md, CSV-Summaries und PNG-Dateien.",
    )


def _add_dashboard_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "dashboard",
        help="Starte ein lokales Read-only Dashboard fuer gespeicherte Backtest/Sweep-Artefakte.",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Root-Ordner mit Backtest- und Sweep-Dateien.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host.")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port.")


def _add_sweep_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "sweep",
        help=(
            "Grid-Suche fuer StrategyConfig-Parameter auf Alpaca-Historie. "
            "Schreibt eine parquet-Tabelle aller Zellen plus winners.json."
        ),
    )
    parser.add_argument(
        "--out-dir",
        default="data/sweep_results",
        help="Zielordner fuer parquet- und winners-Dateien.",
    )
    parser.add_argument(
        "--timeframes",
        nargs="+",
        default=["1d", "1h"],
        choices=list(SUPPORTED_TIMEFRAMES),
        help="Welche Timeframes evaluiert werden.",
    )
    parser.add_argument(
        "--equity-symbols",
        nargs="+",
        default=None,
        help="Override fuer das Equity-Cohort (Default = trader.sweep.EQUITY_COHORT).",
    )
    parser.add_argument(
        "--crypto-symbols",
        nargs="+",
        default=None,
        help="Override fuer das Crypto-Cohort (Default = trader.sweep.CRYPTO_COHORT).",
    )
    parser.add_argument(
        "--in-sample-fraction",
        type=float,
        default=0.7,
        help="Anteil der Bars fuer in-sample (rest = out-of-sample).",
    )
    parser.add_argument(
        "--min-trades",
        type=int,
        default=30,
        help="Mindestzahl OOS-Trades pro Symbol fuer eine eligible Zelle.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Smoke-Modus: kleines Grid + kleinere Cohorts (zur Validierung).",
    )


def _add_sweep_report_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "sweep-report",
        help="Rendere PNG/Markdown-Report aus einer Sweep-Parquet-Datei.",
    )
    parser.add_argument("input", help="Pfad zur Sweep-Parquet-Datei.")
    parser.add_argument(
        "--out-dir",
        default="data/sweep_report",
        help="Zielordner fuer REPORT.md und PNG-Dateien.",
    )
    parser.add_argument(
        "--min-trades",
        type=int,
        default=30,
        help="Mindestzahl OOS-Trades fuer eligible Zellen im Report.",
    )


def _add_dump_frames_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "dump-frames",
        help=(
            "Schreibe alle Pipeline-Stufen (OHLCV, Indikatoren, Signale, "
            "Trades, Equity) als parquet fuer Notebook-Exploration."
        ),
    )
    _add_market_data_arguments(parser)
    _add_strategy_arguments(parser)
    parser.add_argument(
        "--out-dir",
        default="data/research",
        help="Zielordner fuer die fuenf parquet-Dateien",
    )


def _add_market_data_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=DEFAULT_ALPACA_SYMBOLS,
        help="Alpaca-Symbole wie AAPL MSFT SPY oder Crypto-Paare wie BTC/USD",
    )
    parser.add_argument(
        "--timeframe",
        default="1h",
        choices=SUPPORTED_TIMEFRAMES,
        help="Kerzenintervall fuer den Datenabruf",
    )
    parser.add_argument(
        "--bars",
        type=int,
        default=1500,
        help="Anzahl historischer Kerzen pro Symbol",
    )


def _add_strategy_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--strategy",
        default="ema_rsi_pullback",
        choices=SUPPORTED_STRATEGIES,
        help="Signal-Regelwerk",
    )
    parser.add_argument(
        "--adx-threshold", type=float, default=18.0, help="Mindest-ADX fuer Trendstaerke"
    )
    parser.add_argument(
        "--long-rsi-floor", type=float, default=52.0, help="RSI-Untergrenze fuer Longs"
    )
    parser.add_argument(
        "--short-rsi-ceiling",
        type=float,
        default=48.0,
        help="RSI-Obergrenze fuer Shorts",
    )
    parser.add_argument(
        "--pullback-tolerance",
        type=float,
        default=0.0025,
        help="Maximale relative Distanz zur EMA20 fuer Pullback-Einstiege",
    )
    parser.add_argument(
        "--breakout-lookback",
        type=int,
        default=20,
        help="Lookback-Fenster fuer Hoch/Tief-Breakouts",
    )
    parser.add_argument(
        "--mean-reversion-zscore",
        type=float,
        default=1.5,
        help="Z-Score-Schwelle fuer mean_reversion Signale",
    )
    parser.add_argument(
        "--momentum-lookback",
        type=int,
        default=20,
        help="Lookback-Fenster fuer momentum_trend ROC",
    )
    parser.add_argument(
        "--momentum-roc-floor",
        type=float,
        default=0.02,
        help="Mindest-ROC fuer momentum_trend Signale",
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")


def _json_default(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _print_failures(dataset: pd.DataFrame) -> None:
    failures = dataset.attrs.get("failures", [])
    if failures:
        print("Teilweise fehlgeschlagen:")
        for failure in failures:
            print(f" - {failure}")


if __name__ == "__main__":
    raise SystemExit(main())
