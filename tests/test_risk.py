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
    assert implied_notional_exposure(risk_fraction=0.01, stop_loss_pct=0.005, max_leverage=1.5) == 1.5
