"""Command line interface for dataset building, signals, backtests, and MT5 utilities."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from trader.backtest import BacktestConfig, run_backtest
from trader.config import DEFAULT_FOREX_SYMBOLS, SUPPORTED_TIMEFRAMES
from trader.mt5 import MetaTrader5Client, Mt5Error
from trader.pipeline import build_forex_dataset, save_frame, save_latest_snapshot
from trader.risk import PositionSizingInput, position_size_from_stop
from trader.strategies import SUPPORTED_STRATEGIES, StrategyConfig, build_signal_frame, latest_signals


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Trader Workbench fuer Forex-Research, Signale, Backtests und MetaTrader 5."
    )
    subparsers = parser.add_subparsers(dest="command")

    _add_dataset_parser(subparsers)
    _add_signals_parser(subparsers)
    _add_backtest_parser(subparsers)
    _add_mt5_account_parser(subparsers)
    _add_mt5_symbols_parser(subparsers)
    _add_mt5_quote_parser(subparsers)
    _add_mt5_check_order_parser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
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
        if args.command == "mt5-account":
            return _run_mt5_account_command(args)
        if args.command == "mt5-symbols":
            return _run_mt5_symbols_command(args)
        if args.command == "mt5-quote":
            return _run_mt5_quote_command(args)
        if args.command == "mt5-check-order":
            return _run_mt5_check_order_command(args)
    except (RuntimeError, ValueError, Mt5Error) as exc:
        raise SystemExit(str(exc)) from exc

    raise SystemExit("Unbekannter CLI-Befehl.")


def _run_dataset_command(args: argparse.Namespace) -> int:
    dataset = build_forex_dataset(
        symbols=args.symbols,
        timeframe=args.timeframe,
        bars=args.bars,
        source=args.source,
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
    dataset = build_forex_dataset(
        symbols=args.symbols,
        timeframe=args.timeframe,
        bars=args.bars,
        source=args.source,
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
    dataset = build_forex_dataset(
        symbols=args.symbols,
        timeframe=args.timeframe,
        bars=args.bars,
        source=args.source,
    )
    result = run_backtest(
        dataset,
        strategy_config=_strategy_config_from_args(args),
        backtest_config=BacktestConfig(
            initial_capital=args.initial_capital,
            risk_per_trade=args.risk_per_trade,
            stop_loss_pct=args.stop_loss_pct,
            max_leverage=args.max_leverage,
            fee_bps=args.fee_bps,
            slippage_bps=args.slippage_bps,
            allow_short=not args.long_only,
        ),
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
    ):
        value = result.metrics.get(key)
        print(f"{key}: {value}")
    return 0


def _run_mt5_account_command(args: argparse.Namespace) -> int:
    with MetaTrader5Client.from_env() as client:
        account = client.account_info()
        terminal = client.terminal_info()
        positions = client.open_positions()
        orders = client.active_orders()

    payload = {
        "account": account,
        "terminal": terminal,
        "open_positions": len(positions),
        "active_orders": len(orders),
    }
    if args.output:
        _write_json(Path(args.output), payload)

    print(
        "Account:"
        f" login={account.get('login')} server={account.get('server')} "
        f"balance={account.get('balance')} equity={account.get('equity')} "
        f"margin_free={account.get('margin_free')}"
    )
    print(
        "Terminal:"
        f" company={terminal.get('company')} build={terminal.get('build')} connected={terminal.get('connected')}"
    )
    print(f"Open positions: {len(positions)}")
    print(f"Active orders: {len(orders)}")
    return 0


def _run_mt5_symbols_command(args: argparse.Namespace) -> int:
    with MetaTrader5Client.from_env() as client:
        frame = client.symbols(group=args.group)

    if args.contains:
        needle = args.contains.lower()
        mask = frame["name"].astype(str).str.lower().str.contains(needle, regex=False)
        mask |= frame["path"].astype(str).str.lower().str.contains(needle, regex=False)
        mask |= frame["description"].astype(str).str.lower().str.contains(needle, regex=False)
        frame = frame[mask]

    if args.asset_class:
        frame = frame[frame["asset_class"] == args.asset_class]

    frame = frame.reset_index(drop=True)
    if args.limit:
        frame = frame.head(args.limit)

    summary = (
        frame.groupby("asset_class", as_index=False)
        .size()
        .rename(columns={"size": "count"})
        .sort_values("count", ascending=False)
    )

    if args.output:
        save_frame(frame, Path(args.output))

    print(f"Symbole gefunden: {len(frame)}")
    if not summary.empty:
        print(summary.to_string(index=False))

    columns = [column for column in ("name", "asset_class", "path", "description") if column in frame.columns]
    if columns and not frame.empty:
        print(frame[columns].head(args.preview).to_string(index=False))
    return 0


def _run_mt5_quote_command(args: argparse.Namespace) -> int:
    with MetaTrader5Client.from_env() as client:
        info = client.symbol_info(args.symbol)
        quote = client.quote(args.symbol)

    payload = {"symbol_info": info, "quote": quote}
    if args.output:
        _write_json(Path(args.output), payload)

    print(
        f"{info.get('name')} [{info.get('asset_class')}] "
        f"bid={quote.get('bid')} ask={quote.get('ask')} last={quote.get('last')}"
    )
    print(
        f"path={info.get('path')} contract_size={info.get('trade_contract_size')} "
        f"volume_step={info.get('volume_step')} digits={info.get('digits')}"
    )
    return 0


def _run_mt5_check_order_command(args: argparse.Namespace) -> int:
    with MetaTrader5Client.from_env() as client:
        info = client.symbol_info(args.symbol)
        quote = client.quote(args.symbol)
        entry_price = args.entry_price or (quote["ask"] if args.side == "buy" else quote["bid"])

        volume = args.volume
        if volume is None:
            if args.equity is None or args.stop_loss_price is None:
                raise ValueError(
                    "Ohne --volume werden zusaetzlich --equity und --stop-loss-price benoetigt."
                )
            volume = position_size_from_stop(
                PositionSizingInput(
                    equity=args.equity,
                    risk_fraction=args.risk_fraction,
                    entry_price=entry_price,
                    stop_price=args.stop_loss_price,
                    contract_size=float(info.get("trade_contract_size") or 1.0),
                    volume_step=float(info.get("volume_step") or 0.01),
                    volume_min=float(info.get("volume_min") or 0.01),
                    volume_max=float(info.get("volume_max")) if info.get("volume_max") else None,
                )
            )

        margin_estimate = client.estimate_margin(args.symbol, args.side, volume, entry_price)
        order_check = client.check_market_order(
            symbol=args.symbol,
            side=args.side,
            volume=volume,
            stop_loss=args.stop_loss_price,
            take_profit=args.take_profit_price,
            deviation=args.deviation,
            comment=args.comment,
            magic=args.magic,
        )

        risk_at_stop = None
        reward_at_take_profit = None
        if args.stop_loss_price is not None:
            risk_at_stop = client.estimate_profit(
                args.symbol,
                args.side,
                volume,
                entry_price,
                args.stop_loss_price,
            )
        if args.take_profit_price is not None:
            reward_at_take_profit = client.estimate_profit(
                args.symbol,
                args.side,
                volume,
                entry_price,
                args.take_profit_price,
            )

    payload = {
        "symbol": info.get("name"),
        "asset_class": info.get("asset_class"),
        "entry_price": entry_price,
        "volume": volume,
        "margin_estimate": margin_estimate,
        "risk_at_stop": risk_at_stop,
        "reward_at_take_profit": reward_at_take_profit,
        "order_check": order_check,
    }
    if args.output:
        _write_json(Path(args.output), payload)

    print(
        f"{info.get('name')} {args.side} volume={volume} entry={entry_price} "
        f"margin_estimate={margin_estimate}"
    )
    if risk_at_stop is not None:
        print(f"risk_at_stop: {risk_at_stop}")
    if reward_at_take_profit is not None:
        print(f"reward_at_take_profit: {reward_at_take_profit}")
    print(f"retcode: {order_check.get('retcode')}")
    return 0


def _strategy_config_from_args(args: argparse.Namespace) -> StrategyConfig:
    return StrategyConfig(
        strategy=args.strategy,
        adx_threshold=args.adx_threshold,
        long_rsi_floor=args.long_rsi_floor,
        short_rsi_ceiling=args.short_rsi_ceiling,
        pullback_tolerance=args.pullback_tolerance,
        breakout_lookback=args.breakout_lookback,
    )


def _add_dataset_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "dataset",
        help="Lade Forex-Marktdaten und baue das Indikator-Feature-Set.",
    )
    _add_market_data_arguments(parser)
    parser.add_argument(
        "--output",
        default="data/forex_indicators.parquet",
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
    parser.add_argument("--stop-loss-pct", type=float, default=0.005, help="Annahme fuer Stop-Distanz")
    parser.add_argument("--max-leverage", type=float, default=1.0, help="Maximale Ziel-Exponierung")
    parser.add_argument("--fee-bps", type=float, default=1.0, help="Gebuehren in Basispunkten")
    parser.add_argument("--slippage-bps", type=float, default=1.0, help="Slippage in Basispunkten")
    parser.add_argument("--long-only", action="store_true", help="Ignoriere Short-Signale.")
    parser.add_argument(
        "--output",
        default="data/backtest_equity.csv",
        help="Zielpfad fuer Equity-Kurve und Portfolio-Serie",
    )


def _add_mt5_account_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "mt5-account",
        help="Lese Kontoinformationen, Terminal-Infos, offene Positionen und Orders aus.",
    )
    parser.add_argument("--output", help="Optionaler JSON-Zielpfad")


def _add_mt5_symbols_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "mt5-symbols",
        help="Liste und klassifiziere die bei deinem Broker verfuegbaren MT5-Symbole.",
    )
    parser.add_argument("--group", help='MT5 group-Filter wie "*FX*" oder "*, !EUR"')
    parser.add_argument("--contains", help="Filter fuer Name, Pfad oder Beschreibung")
    parser.add_argument(
        "--asset-class",
        choices=[
            "forex",
            "crypto",
            "metals",
            "energy",
            "futures",
            "indices",
            "etf",
            "bonds",
            "options",
            "stocks",
            "commodities",
            "unknown",
        ],
    )
    parser.add_argument("--limit", type=int, help="Begrenze die Ergebnismenge")
    parser.add_argument("--preview", type=int, default=20, help="Anzahl Zeilen fuer die Terminal-Vorschau")
    parser.add_argument("--output", help="CSV/Parquet/JSON Zielpfad")


def _add_mt5_quote_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "mt5-quote",
        help="Lese Tick- und Symbolinformationen fuer ein MT5-Symbol.",
    )
    parser.add_argument("symbol", help="Beispiel: EURUSD, XAUUSD, GER40.cash")
    parser.add_argument("--output", help="Optionaler JSON-Zielpfad")


def _add_mt5_check_order_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "mt5-check-order",
        help="Baue einen Market-Order-Request und pruefe ihn via MT5 order_check().",
    )
    parser.add_argument("symbol", help="MT5-Symbol")
    parser.add_argument("side", choices=["buy", "sell"])
    parser.add_argument("--volume", type=float, help="Lot-Groesse. Wenn nicht gesetzt, wird sie berechnet.")
    parser.add_argument("--equity", type=float, help="Kontokapital fuer automatische Groessenberechnung")
    parser.add_argument("--risk-fraction", type=float, default=0.01)
    parser.add_argument("--entry-price", type=float, help="Optional. Sonst aktueller Bid/Ask.")
    parser.add_argument("--stop-loss-price", type=float)
    parser.add_argument("--take-profit-price", type=float)
    parser.add_argument("--deviation", type=int, default=20)
    parser.add_argument("--magic", type=int, default=234000)
    parser.add_argument("--comment", default="trader-order-check")
    parser.add_argument("--output", help="Optionaler JSON-Zielpfad")


def _add_market_data_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=DEFAULT_FOREX_SYMBOLS,
        help="Forex-Symbole wie EURUSD GBPUSD USDJPY",
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
    parser.add_argument(
        "--source",
        default="auto",
        choices=["auto", "mt5", "yfinance"],
        help="Bevorzugte Datenquelle. 'auto' probiert zuerst MT5 und faellt dann auf yfinance zurueck.",
    )


def _add_strategy_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--strategy",
        default="ema_rsi_pullback",
        choices=SUPPORTED_STRATEGIES,
        help="Signal-Regelwerk",
    )
    parser.add_argument("--adx-threshold", type=float, default=18.0, help="Mindest-ADX fuer Trendstaerke")
    parser.add_argument("--long-rsi-floor", type=float, default=52.0, help="RSI-Untergrenze fuer Longs")
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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp,)):
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
