import pytest

from trader.risk import (
    PositionSizingInput,
    implied_notional_exposure,
    position_size_from_stop,
    quantize_volume,
)


def test_quantize_volume_rounds_down_to_step() -> None:
    assert quantize_volume(0.237, step=0.01, minimum=0.01) == 0.23


def test_position_size_from_stop_uses_contract_and_step_constraints() -> None:
    volume = position_size_from_stop(
        PositionSizingInput(
            equity=10_000,
            risk_fraction=0.01,
            entry_price=1.1000,
            stop_price=1.0950,
            contract_size=100_000,
            volume_step=0.01,
            volume_min=0.01,
            volume_max=100.0,
        )
    )
    assert volume == 0.2


def test_implied_notional_exposure_caps_at_max_leverage() -> None:
    assert (
        implied_notional_exposure(risk_fraction=0.01, stop_loss_pct=0.005, max_leverage=1.5) == 1.5
    )


def test_implied_notional_exposure_returns_unleveraged_when_below_cap() -> None:
    # 0.005 risk_fraction / 0.01 stop_loss_pct = 0.5 — below the 1.0 default cap.
    assert implied_notional_exposure(risk_fraction=0.005, stop_loss_pct=0.01) == 0.5


def test_implied_notional_exposure_caps_at_default_max_leverage_for_aggressive_inputs() -> None:
    # risk_fraction / stop_loss_pct = 100 with the default cap of 1.0.
    assert implied_notional_exposure(risk_fraction=0.5, stop_loss_pct=0.005) == 1.0


def test_implied_notional_exposure_rejects_zero_stop_loss() -> None:
    with pytest.raises(ValueError, match="stop_loss_pct"):
        implied_notional_exposure(risk_fraction=0.01, stop_loss_pct=0.0)


def test_implied_notional_exposure_rejects_negative_stop_loss() -> None:
    with pytest.raises(ValueError, match="stop_loss_pct"):
        implied_notional_exposure(risk_fraction=0.01, stop_loss_pct=-0.005)


def test_implied_notional_exposure_rejects_out_of_range_risk_fraction() -> None:
    for bad in (0.0, -0.01, 1.5):
        with pytest.raises(ValueError, match="risk_fraction"):
            implied_notional_exposure(risk_fraction=bad, stop_loss_pct=0.01)


def test_implied_notional_exposure_rejects_non_positive_max_leverage() -> None:
    with pytest.raises(ValueError, match="max_leverage"):
        implied_notional_exposure(risk_fraction=0.01, stop_loss_pct=0.005, max_leverage=0.0)
