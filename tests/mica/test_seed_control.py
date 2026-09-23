from __future__ import annotations

from code.mica.experiment.seed_control import set_reproducible_seed


def test_set_reproducible_seed_returns_repeatable_summary() -> None:
    first = set_reproducible_seed(42)
    second = set_reproducible_seed(42)

    assert first["seed"] == second["seed"] == 42
    assert first["python_hash_seed"] == second["python_hash_seed"]
