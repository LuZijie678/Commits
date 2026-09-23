from __future__ import annotations

from code.mica.training.batch_adapters import (
    adapt_hard_b_batch,
    adapt_m_weak_batch,
    adapt_real_alignment_batch,
    adapt_strict_replay_batch,
    validate_train_batch,
)


def test_adapt_strict_replay_batch_requires_gold_supervision() -> None:
    batch = adapt_strict_replay_batch(
        {
            "sample_id": "s1",
            "source_kind": "strict_replay",
            "gold_count": 2,
            "gold_unit_to_intent": {"u1": "i1", "u2": "i2"},
            "edit_units": [{"unit_id": "u1"}, {"unit_id": "u2"}],
        }
    )

    assert batch.source_kind == "strict_replay"
    assert batch.gold_count == 2
    assert batch.gold_unit_to_intent == {"u1": "i1", "u2": "i2"}
    assert validate_train_batch(batch)["valid"] is True


def test_adapt_hard_b_batch_has_k1_without_alignment_requirement() -> None:
    batch = adapt_hard_b_batch({"sample_id": "hb1", "edit_units": [{"unit_id": "u1"}]})

    assert batch.source_kind == "hard_b"
    assert batch.gold_count == 1
    assert batch.gold_unit_to_intent is None
    assert validate_train_batch(batch)["valid"] is True


def test_adapt_m_weak_batch_uses_censored_label_not_exact_k2() -> None:
    batch = adapt_m_weak_batch({"sample_id": "mw1", "edit_units": [{"unit_id": "u1"}]})

    assert batch.source_kind == "m_weak"
    assert batch.weak_label == "censored_k_ge_2"
    assert batch.gold_count is None
    assert batch.metadata["exact_k_supervision_used"] is False


def test_adapt_real_alignment_batch_requires_alignment_gold() -> None:
    batch = adapt_real_alignment_batch(
        {
            "sample_id": "ra1",
            "split": "train",
            "gold_count": 2,
            "gold_unit_to_intent": {"u1": "i1", "u2": "i2"},
            "edit_units": [{"unit_id": "u1"}, {"unit_id": "u2"}],
        }
    )

    assert batch.source_kind == "real_alignment"
    assert batch.gold_count == 2
    assert validate_train_batch(batch)["valid"] is True


def test_validate_train_batch_reports_missing_fields() -> None:
    batch = adapt_real_alignment_batch({"sample_id": "broken"})
    validation = validate_train_batch(batch)

    assert validation["valid"] is False
    assert "missing_gold_count" in validation["diagnostics"]
