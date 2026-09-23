from __future__ import annotations

from code.mica.schedules.loss_schedules import compute_alpha_pb_schedule, compute_lambda_cal_schedule


def test_lambda_cal_schedule_stays_zero_during_warmup_then_rises() -> None:
    spec = {"cardinality_schedule": {"kl_warmup_fraction": 0.2, "lambda_cal_max": 0.05}}

    assert compute_lambda_cal_schedule(step=10, total_steps=100, spec=spec) == 0.0
    assert compute_lambda_cal_schedule(step=30, total_steps=100, spec=spec) > 0.0


def test_alpha_pb_schedule_reads_start_and_end_values() -> None:
    spec = {"cardinality_schedule": {"alpha_pb_start": 0.2, "alpha_pb_end": 0.6}}

    assert compute_alpha_pb_schedule(step=0, total_steps=100, spec=spec) == 0.2
    assert compute_alpha_pb_schedule(step=100, total_steps=100, spec=spec) == 0.6

