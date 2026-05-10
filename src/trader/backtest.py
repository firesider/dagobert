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
    use_strategy_exits: bool = False


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict[str, float]


def run_walk_forward_backtest(
    features: pd.DataFrame,
    strategy_config: StrategyConfig | None = None,
    backtest_config: BacktestConfig | None = None,
    in_sample_fraction: float = 0.7,
) -> BacktestResult:
    if not 0.0 < in_sample_fraction < 1.0:
        raise ValueError("in_sample_fraction muss in (0, 1) liegen.")

    in_sample, out_of_sample = _split_by_symbol(features, in_sample_fraction)
    in_result = run_backtest(in_sample, strategy_config, backtest_config)
    out_result = run_backtest(out_of_sample, strategy_config, backtest_config)

    in_curve = in_result.equity_curve.copy()
    out_curve = out_result.equity_curve.copy()
    in_curve["sample"] = "in_sample"
    out_curve["sample"] = "out_of_sample"

    in_trades = in_result.trades.copy()
    out_trades = out_result.trades.copy()
    in_trades["sample"] = "in_sample"
    out_trades["sample"] = "out_of_sample"

    metrics = _prefix_metrics("in_sample", in_result.metrics)
    metrics.update(_prefix_metrics("out_of_sample", out_result.metrics))
    metrics["in_sample_fraction"] = float(in_sample_fraction)

    return BacktestResult(
        equity_curve=pd.concat([in_curve, out_curve], ignore_index=True),
        trades=pd.concat([in_trades, out_trades], ignore_index=True),
        metrics=metrics,
    )


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
    effective_asset_return, exit_reason = _apply_strategy_exits(
        frame=frame,
        direction=direction,
        close_to_close_return=asset_return,
        enabled=config.use_strategy_exits,
        default_stop_loss_pct=config.stop_loss_pct,
    )
    turnover = position.diff().abs().fillna(position.abs())
    trading_cost = turnover * ((config.fee_bps + config.slippage_bps) / 10_000.0)
    gross_strategy_return = position * effective_asset_return
    strategy_return = gross_strategy_return - trading_cost

    equity = config.initial_capital * (1.0 + strategy_return).cumprod()
    drawdown = (equity / equity.cummax()) - 1.0

    curve = frame[
        [
            "time",
            "signal",
            "signal_label",
            "close",
            "conviction_score",
            "strategy_name",
            "timeframe",
        ]
    ].copy()
    curve["position"] = position
    curve["asset_return"] = asset_return
    curve["effective_asset_return"] = effective_asset_return
    curve["exit_reason"] = exit_reason
    curve["gross_strategy_return"] = gross_strategy_return
    curve["strategy_return"] = strategy_return
    curve["equity"] = equity
    curve["drawdown"] = drawdown
    curve["benchmark_return"] = asset_return
    curve["benchmark_equity"] = config.initial_capital * (1.0 + asset_return).cumprod()
    curve["benchmark_drawdown"] = (
        curve["benchmark_equity"] / curve["benchmark_equity"].cummax()
    ) - 1.0

    trades = _extract_trades(
        frame,
        position,
        gross_strategy_return=gross_strategy_return,
        strategy_return=strategy_return,
        exit_reason=exit_reason,
    )
    metrics = _compute_symbol_metrics(curve, trades)
    return curve, trades, metrics


def _apply_strategy_exits(
    *,
    frame: pd.DataFrame,
    direction: pd.Series,
    close_to_close_return: pd.Series,
    enabled: bool,
    default_stop_loss_pct: float,
) -> tuple[pd.Series, pd.Series]:
    if not enabled:
        return close_to_close_return, pd.Series("signal", index=frame.index, dtype="object")

    previous_close = frame["close"].shift(1).replace(0, np.nan)
    high_return = ((frame["high"] / previous_close) - 1).fillna(close_to_close_return)
    low_return = ((frame["low"] / previous_close) - 1).fillna(close_to_close_return)
    stop_pct = (
        (
            frame["suggested_stop_loss_pct"]
            if "suggested_stop_loss_pct" in frame.columns
            else pd.Series(default_stop_loss_pct, index=frame.index)
        )
        .shift(1)
        .fillna(default_stop_loss_pct)
    )
    take_profit_pct = (
        (
            frame["suggested_take_profit_pct"]
            if "suggested_take_profit_pct" in frame.columns
            else stop_pct * 2
        )
        .shift(1)
        .fillna(stop_pct * 2)
    )

    effective = close_to_close_return.copy()
    reason = pd.Series("signal", index=frame.index, dtype="object")

    long_position = direction > 0
    long_stop = long_position & (low_return <= -stop_pct)
    long_take = long_position & ~long_stop & (high_return >= take_profit_pct)

    short_position = direction < 0
    short_stop = short_position & (high_return >= stop_pct)
    short_take = short_position & ~short_stop & (low_return <= -take_profit_pct)

    effective = effective.mask(long_stop, -stop_pct)
    effective = effective.mask(long_take, take_profit_pct)
    effective = effective.mask(short_stop, stop_pct)
    effective = effective.mask(short_take, -take_profit_pct)
    reason = reason.mask(long_stop | short_stop, "stop_loss")
    reason = reason.mask(long_take | short_take, "take_profit")

    return effective.astype("float64"), reason


def _extract_trades(
    frame: pd.DataFrame,
    position: pd.Series,
    gross_strategy_return: pd.Series,
    strategy_return: pd.Series,
    exit_reason: pd.Series,
) -> pd.DataFrame:
    entries = (position != 0) & position.ne(position.shift(1).fillna(0))
    trade_ids = entries.cumsum()
    active = frame.copy()
    active["position"] = position
    active["gross_strategy_return"] = gross_strategy_return
    active["strategy_return"] = strategy_return
    active["exit_reason"] = exit_reason
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
                "exit_reason",
                "gross_return",
                "net_return",
            ]
        )

    trades: list[dict[str, float | int | str | pd.Timestamp]] = []
    for trade_id, trade_frame in active.groupby("trade_id", sort=True):
        start = trade_frame.iloc[0]
        end = trade_frame.iloc[-1]
        direction = "long" if start["position"] > 0 else "short"
        gross_return = (1.0 + trade_frame["gross_strategy_return"]).prod() - 1.0
        net_return = (1.0 + trade_frame["strategy_return"]).prod() - 1.0
        exit_reasons = trade_frame.loc[trade_frame["exit_reason"] != "signal", "exit_reason"]
        reason = str(exit_reasons.iloc[-1]) if not exit_reasons.empty else "signal"

        trades.append(
            {
                "trade_id": int(trade_id),
                "entry_time": start["time"],
                "exit_time": end["time"],
                "direction": direction,
                "entry_price": float(start["close"]),
                "exit_price": float(end["close"]),
                "bars_held": int(len(trade_frame)),
                "exit_reason": reason,
                "gross_return": float(gross_return),
                "net_return": float(net_return),
            }
        )

    return pd.DataFrame(trades)


def _build_portfolio_curve(equity_curve: pd.DataFrame, initial_capital: float) -> pd.DataFrame:
    returns = equity_curve.pivot(
        index="time", columns="symbol", values="strategy_return"
    ).sort_index()
    if "benchmark_return" in equity_curve.columns:
        benchmark_returns = equity_curve.pivot(
            index="time", columns="symbol", values="benchmark_return"
        ).sort_index()
    else:
        benchmark_returns = returns.copy()
    # Equal-weight mean over symbols *that have a bar at this time*. NaN-returns
    # (a symbol with no bar at t) must not be silently treated as a zero return
    # — that would dilute the average and under-weight symbols with gaps.
    portfolio_return = returns.mean(axis=1, skipna=True).fillna(0.0)
    benchmark_return = benchmark_returns.mean(axis=1, skipna=True).fillna(0.0)
    equity = initial_capital * (1.0 + portfolio_return).cumprod()
    drawdown = (equity / equity.cummax()) - 1.0
    benchmark_equity = initial_capital * (1.0 + benchmark_return).cumprod()
    benchmark_drawdown = (benchmark_equity / benchmark_equity.cummax()) - 1.0

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
            "benchmark_return": benchmark_return.to_numpy(),
            "benchmark_equity": benchmark_equity.to_numpy(),
            "benchmark_drawdown": benchmark_drawdown.to_numpy(),
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
        "benchmark_total_return": _total_return(curve["benchmark_equity"]),
        "benchmark_annualized_return": _annualized_return(
            curve["benchmark_equity"], periods_per_year
        ),
        "benchmark_annualized_volatility": _annualized_volatility(
            curve["benchmark_return"], periods_per_year
        ),
        "benchmark_sharpe": _sharpe(curve["benchmark_return"], periods_per_year),
        "benchmark_max_drawdown": float(curve["benchmark_drawdown"].min())
        if not curve.empty
        else 0.0,
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
    gross_loss = (
        abs(trades.loc[trades["net_return"] < 0, "net_return"].sum()) if len(trades) else 0.0
    )

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
        "benchmark_ending_capital": float(curve["benchmark_equity"].iloc[-1])
        if not curve.empty
        else 0.0,
        "benchmark_total_return": _total_return(curve["benchmark_equity"]),
        "benchmark_annualized_return": _annualized_return(
            curve["benchmark_equity"], periods_per_year
        ),
        "benchmark_annualized_volatility": _annualized_volatility(
            curve["benchmark_return"], periods_per_year
        ),
        "benchmark_sharpe": _sharpe(curve["benchmark_return"], periods_per_year),
        "benchmark_max_drawdown": float(curve["benchmark_drawdown"].min())
        if not curve.empty
        else 0.0,
    }


def _split_by_symbol(frame: pd.DataFrame, fraction: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    in_frames: list[pd.DataFrame] = []
    out_frames: list[pd.DataFrame] = []
    for _, symbol_frame in frame.sort_values(["symbol", "time"]).groupby("symbol", sort=True):
        cutoff = max(1, int(len(symbol_frame) * fraction))
        in_frames.append(symbol_frame.iloc[:cutoff].copy())
        out_frames.append(symbol_frame.iloc[cutoff:].copy())

    if not in_frames:
        return frame.copy(), frame.copy()
    return pd.concat(in_frames, ignore_index=True), pd.concat(out_frames, ignore_index=True)


def _prefix_metrics(prefix: str, metrics: dict[str, float]) -> dict[str, float]:
    return {f"{prefix}_{key}": value for key, value in metrics.items()}


def _total_return(equity: pd.Series) -> float:
    if len(equity) <= 1 or equity.iloc[0] <= 0:
        return 0.0
    return float((equity.iloc[-1] / equity.iloc[0]) - 1)


def _annualized_volatility(returns: pd.Series, periods_per_year: int) -> float:
    returns = returns.fillna(0.0)
    vol = float(returns.std(ddof=0)) if len(returns) else 0.0
    return float(vol * sqrt(periods_per_year))


def _sharpe(returns: pd.Series, periods_per_year: int) -> float:
    returns = returns.fillna(0.0)
    vol = float(returns.std(ddof=0)) if len(returns) else 0.0
    return float(returns.mean() / vol * sqrt(periods_per_year)) if vol > 0 else 0.0


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
