"""Risk and position sizing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor


@dataclass(frozen=True)
class PositionSizingInput:
    equity: float
    risk_fraction: float
    entry_price: float
    stop_price: float
    contract_size: float = 1.0
    volume_step: float = 0.01
    volume_min: float = 0.01
    volume_max: float | None = None


def risk_amount(equity: float, risk_fraction: float) -> float:
    if equity <= 0:
        raise ValueError("equity muss groesser als 0 sein.")
    if not 0 < risk_fraction <= 1:
        raise ValueError("risk_fraction muss im Bereich (0, 1] liegen.")
    return equity * risk_fraction


def quantize_volume(
    volume: float,
    step: float,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> float:
    if step <= 0:
        raise ValueError("step muss groesser als 0 sein.")
    if volume < 0:
        raise ValueError("volume darf nicht negativ sein.")

    quantized = floor((volume / step) + 1e-12) * step
    quantized = max(quantized, minimum)

    if maximum is not None:
        quantized = min(quantized, maximum)

    decimals = _step_decimals(step)
    return round(quantized, decimals)


def position_size_from_stop(sizing: PositionSizingInput) -> float:
    if sizing.entry_price <= 0 or sizing.stop_price <= 0:
        raise ValueError("entry_price und stop_price muessen groesser als 0 sein.")
    if sizing.contract_size <= 0:
        raise ValueError("contract_size muss groesser als 0 sein.")

    stop_distance = abs(sizing.entry_price - sizing.stop_price)
    if stop_distance <= 0:
        raise ValueError("stop_distance muss groesser als 0 sein.")

    loss_per_lot = stop_distance * sizing.contract_size
    raw_volume = risk_amount(sizing.equity, sizing.risk_fraction) / loss_per_lot
    return quantize_volume(
        volume=raw_volume,
        step=sizing.volume_step,
        minimum=sizing.volume_min,
        maximum=sizing.volume_max,
    )


def implied_notional_exposure(
    risk_fraction: float,
    stop_loss_pct: float,
    max_leverage: float = 1.0,
) -> float:
    if not 0 < risk_fraction <= 1:
        raise ValueError("risk_fraction muss im Bereich (0, 1] liegen.")
    if stop_loss_pct <= 0:
        raise ValueError("stop_loss_pct muss groesser als 0 sein.")
    if max_leverage <= 0:
        raise ValueError("max_leverage muss groesser als 0 sein.")

    return min(risk_fraction / stop_loss_pct, max_leverage)


def _step_decimals(step: float) -> int:
    text = f"{step:.10f}".rstrip("0")
    if "." not in text:
        return 0
    return len(text.split(".", maxsplit=1)[1])
