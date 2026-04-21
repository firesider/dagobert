"""Lightweight signal backtesting utilities."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import numpy as np
import pandas as pd

from trader.config import TIMEFRAME_TO_MINUTES, validate_timeframe
from trader.risk import implied_notional_exposure
from trader.strategies import StrategyConfig, build_signal_frame


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 10_000.0
    risk_per_trade: float = 0.01
    stop_loss_pct: float = 0.005
    max_leverage: float = 1.0
    fee_bps: float = 1.0
    slippage_bps: float = 1.0
    allow_short: bool = True


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict[str, float]


def run_backtest(
    features: pd.DataFrame,
    strategy_config: StrategyConfig | None = None,
    backtest_config: BacktestConfig | None = None,
) -> BacktestResult:
    strategy = strategy_config or StrategyConfig()
    config = backtest_config or BacktestConfig()

    signal_frame = build_signal_frame(features, strategy)
    equity_frames: list[pd.DataFrame] = []
    trades: list[pd.DataFrame] = []
    symbol_metrics: list[dict[str, float]] = []

    for symbol, symbol_frame in signal_frame.groupby("symbol", sort=True):
        curve, trade_frame, metrics = _run_single_symbol_backtest(symbol_frame.copy(), config)
        curve["symbol"] = symbol
        trade_frame["symbol"] = symbol
        metrics["symbol"] = symbol
        equity_frames.append(curve)
        trades.append(trade_frame)
        symbol_metrics.append(metrics)

    equity_curve = pd.concat(equity_frames, ignore_index=True)
    trade_log = pd.concat(trades, ignore_index=True) if trades else pd.DataFrame()

    portfolio_curve = _build_portfolio_curve(equity_curve, config.initial_capital)
    portfolio_metrics = _compute_portfolio_metrics(portfolio_curve, trade_log)
    portfolio_metrics["symbols_tested"] = float(len(symbol_metrics))
    portfolio_metrics["avg_symbol_sharpe"] = float(
        np.nanmean([metrics.get("sharpe", np.nan) for metrics in symbol_metrics])
    )

    combined_curve = pd.concat([equity_curve, portfolio_curve], ignore_index=True)
    return BacktestResult(equity_curve=combined_curve, trades=trade_log, metrics=portfolio_metrics)


def _run_single_symbol_backtest(
    frame: pd.DataFrame,
    config: BacktestConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    frame = frame.sort_values("time").reset_index(drop=True)

    direction = frame["signal"].shift(1).fillna(0)
    if not config.allow_short:
        direction = direction.clip(lower=0)

    exposure = implied_notional_exposure(
        risk_fraction=config.risk_per_trade,
        stop_loss_pct=config.stop_loss_pct,
        max_leverage=config.max_leverage,
    )
    position = direction * exposure
    asset_return = frame["close"].pct_change().fillna(0.0)
    turnover = position.diff().abs().fillna(position.abs())
    trading_cost = turnover * ((config.fee_bps + config.slippage_bps) / 10_000.0)
    strategy_return = (position * asset_return) - trading_cost

    equity = config.initial_capital * (1.0 + strategy_return).cumprod()
    drawdown = (equity / equity.cummax()) - 1.0

    curve = frame[
        ["time", "signal", "signal_label", "close", "conviction_score", "strategy_name", "timeframe"]
    ].copy()
    curve["position"] = position
    curve["asset_return"] = asset_return
    curve["strategy_return"] = strategy_return
    curve["equity"] = equity
    curve["drawdown"] = drawdown

    trades = _extract_trades(frame, position, exposure, config)
    metrics = _compute_symbol_metrics(curve, trades)
    return curve, trades, metrics


def _extract_trades(
    frame: pd.DataFrame,
    position: pd.Series,
    exposure: float,
    config: BacktestConfig,
) -> pd.DataFrame:
    entries = (position != 0) & position.ne(position.shift(1).fillna(0))
    trade_ids = entries.cumsum()
    active = frame.copy()
    active["position"] = position
    active["trade_id"] = trade_ids
    active = active[active["position"] != 0].copy()

    if active.empty:
        return pd.DataFrame(
            columns=[
                "trade_id",
                "entry_time",
                "exit_time",
                "direction",
                "entry_price",
                "exit_price",
                "bars_held",
                "gross_return",
                "net_return",
            ]
        )

    trades: list[dict[str, float | int | str | pd.Timestamp]] = []
    for trade_id, trade_frame in active.groupby("trade_id", sort=True):
        start = trade_frame.iloc[0]
        end = trade_frame.iloc[-1]
        direction = "long" if start["position"] > 0 else "short"
        price_return = (end["close"] / start["close"]) - 1
        signed_return = price_return if direction == "long" else -price_return
        gross_return = signed_return * exposure
        round_trip_cost = 2 * ((config.fee_bps + config.slippage_bps) / 10_000.0)
        net_return = gross_return - round_trip_cost

        trades.append(
            {
                "trade_id": int(trade_id),
                "entry_time": start["time"],
                "exit_time": end["time"],
                "direction": direction,
                "entry_price": float(start["close"]),
                "exit_price": float(end["close"]),
                "bars_held": int(len(trade_frame)),
                "gross_return": float(gross_return),
                "net_return": float(net_return),
            }
        )

    return pd.DataFrame(trades)


def _build_portfolio_curve(equity_curve: pd.DataFrame, initial_capital: float) -> pd.DataFrame:
    returns = (
        equity_curve.pivot(index="time", columns="symbol", values="strategy_return")
        .sort_index()
        .fillna(0.0)
    )
    portfolio_return = returns.mean(axis=1)
    equity = initial_capital * (1.0 + portfolio_return).cumprod()
    drawdown = (equity / equity.cummax()) - 1.0

    portfolio_curve = pd.DataFrame(
        {
            "time": returns.index,
            "signal": np.nan,
            "signal_label": "portfolio",
            "close": np.nan,
            "conviction_score": np.nan,
            "strategy_name": "portfolio",
            "timeframe": _dominant_timeframe(equity_curve),
            "position": np.nan,
            "asset_return": np.nan,
            "strategy_return": portfolio_return.to_numpy(),
            "equity": equity.to_numpy(),
            "drawdown": drawdown.to_numpy(),
            "symbol": "PORTFOLIO",
        }
    )
    return portfolio_curve.reset_index(drop=True)


def _compute_symbol_metrics(curve: pd.DataFrame, trades: pd.DataFrame) -> dict[str, float]:
    periods_per_year = _periods_per_year(curve["timeframe"].iloc[0] if not curve.empty else "1d")
    returns = curve["strategy_return"]
    ending_equity = float(curve["equity"].iloc[-1]) if not curve.empty else 0.0
    total_return = (ending_equity / curve["equity"].iloc[0]) - 1 if len(curve) > 1 else 0.0
    vol = float(returns.std(ddof=0)) if len(returns) else 0.0
    sharpe = (returns.mean() / vol * sqrt(periods_per_year)) if vol > 0 else 0.0

    return {
        "total_return": float(total_return),
        "annualized_return": _annualized_return(curve["equity"], periods_per_year),
        "annualized_volatility": float(vol * sqrt(periods_per_year)),
        "sharpe": float(sharpe),
        "max_drawdown": float(curve["drawdown"].min()) if not curve.empty else 0.0,
        "trade_count": float(len(trades)),
        "win_rate": float((trades["net_return"] > 0).mean()) if len(trades) else 0.0,
    }


def _compute_portfolio_metrics(
    curve: pd.DataFrame,
    trades: pd.DataFrame,
) -> dict[str, float]:
    periods_per_year = _periods_per_year(_dominant_timeframe(curve))
    returns = curve["strategy_return"].fillna(0.0)
    ending_equity = float(curve["equity"].iloc[-1]) if not curve.empty else 0.0
    total_return = (ending_equity / curve["equity"].iloc[0]) - 1 if len(curve) > 1 else 0.0
    vol = float(returns.std(ddof=0)) if len(returns) else 0.0
    sharpe = (returns.mean() / vol * sqrt(periods_per_year)) if vol > 0 else 0.0

    gross_profit = trades.loc[trades["net_return"] > 0, "net_return"].sum() if len(trades) else 0.0
    gross_loss = abs(trades.loc[trades["net_return"] < 0, "net_return"].sum()) if len(trades) else 0.0

    return {
        "initial_capital": float(curve["equity"].iloc[0]) if not curve.empty else 0.0,
        "ending_capital": ending_equity,
        "total_return": float(total_return),
        "annualized_return": _annualized_return(curve["equity"], periods_per_year),
        "annualized_volatility": float(vol * sqrt(periods_per_year)),
        "sharpe": float(sharpe),
        "max_drawdown": float(curve["drawdown"].min()) if not curve.empty else 0.0,
        "trade_count": float(len(trades)),
        "win_rate": float((trades["net_return"] > 0).mean()) if len(trades) else 0.0,
        "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else float("inf"),
    }


def _annualized_return(equity: pd.Series, periods_per_year: int) -> float:
    if len(equity) <= 1 or equity.iloc[0] <= 0:
        return 0.0
    total_periods = len(equity) - 1
    return float((equity.iloc[-1] / equity.iloc[0]) ** (periods_per_year / total_periods) - 1)


def _periods_per_year(timeframe: str) -> int:
    minutes = TIMEFRAME_TO_MINUTES[validate_timeframe(timeframe)]
    return int(round((365 * 24 * 60) / minutes))


def _dominant_timeframe(frame: pd.DataFrame) -> str:
    if "timeframe" not in frame.columns or frame.empty:
        return "1d"
    timeframe = frame["timeframe"].dropna()
    return str(timeframe.mode().iloc[0]) if not timeframe.empty else "1d"
