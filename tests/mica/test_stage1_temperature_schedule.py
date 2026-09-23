from __future__ import annotations

from code.mica.train.train_stage1_sanity import assignment_temperature_for_epoch


def test_assignment_temperature_schedule_anneals_between_bounds() -> None:
    first = assignment_temperature_for_epoch(epoch_index=0, total_epochs=3, tau_start=1.5, tau_end=0.7)
    middle = assignment_temperature_for_epoch(epoch_index=1, total_epochs=3, tau_start=1.5, tau_end=0.7)
    last = assignment_temperature_for_epoch(epoch_index=2, total_epochs=3, tau_start=1.5, tau_end=0.7)

    assert first == 1.5
    assert last == 0.7
    assert first > middle > last
