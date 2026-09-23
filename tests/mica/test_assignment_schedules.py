from __future__ import annotations

from code.mica.schedules.assignment_schedules import compute_assignment_entropy_coeff, compute_assignment_temperature


def test_assignment_temperature_anneals_from_high_to_low() -> None:
    spec = {"assignment_schedule": {"tau_start": 2.0, "tau_end": 1.0}}

    assert compute_assignment_temperature(step=0, total_steps=100, spec=spec) == 2.0
    assert compute_assignment_temperature(step=100, total_steps=100, spec=spec) == 1.0


def test_entropy_coeff_starts_positive_and_anneals_to_zero() -> None:
    spec = {"assignment_schedule": {"entropy_coeff_start": 0.02, "entropy_coeff_end": 0.0}}

    assert compute_assignment_entropy_coeff(step=0, total_steps=100, spec=spec) == 0.02
    assert compute_assignment_entropy_coeff(step=100, total_steps=100, spec=spec) == 0.0

