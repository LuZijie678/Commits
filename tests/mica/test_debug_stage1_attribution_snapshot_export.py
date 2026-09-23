from __future__ import annotations

import json
from types import SimpleNamespace

from code.mica.io_utils import read_jsonl, write_jsonl


def _sample(sample_id: str = "sample_debug") -> SimpleNamespace:
    unit = SimpleNamespace(
        unit_id=f"{sample_id}::u0001",
        hunk_id=f"{sample_id}::h0001",
        file_path="src/auth/token.py",
        patch_text="@@",
        added_lines=["+ validate_token(token)"],
        deleted_lines=["- token"],
        context_lines=[],
        file_role="source",
        language="python",
        identifiers=["token", "validate_token"],
        gold_intent_id=0,
        enclosing_symbol_type="function",
        enclosing_symbol_name="validate_token",
        enclosing_symbol_signature=None,
        enclosing_symbol_old_span=None,
        enclosing_symbol_new_span=None,
        enclosing_symbol_old_text=None,
        enclosing_symbol_new_text=None,
        enclosing_symbol_resolution_status="resolved",
        context_clipped=False,
        provenance_status="strict_unique_atomic",
        source_atomic_commit_ids=["atomic_a"],
    )
    return SimpleNamespace(
        sample_id=sample_id,
        source_kind="strict_replay",
        edit_units=[unit],
    )


def test_build_backend_snapshot_rows_from_debug_batch_exports_into_review_ready_plan(tmp_path) -> None:
    from code.mica.runners.export_consumer_plans import export_consumer_plans
    from code.mica.runners.export_stage1_predictions import export_stage1_predictions
    from code.mica.train.debug_stage1_attribution import build_backend_snapshot_rows_from_debug_batch

    class FakeBackend:
        def forward(self, batch):
            return {
                "count_probs": [0.96, 0.04],
                "pb_count_probs": [0.95, 0.05],
                "slot_exist_probs": [0.97, 0.02],
                "assignments": {f"{batch.sample_ids[0]}::u0001": "slot_1"},
                "assignment_scores": {f"{batch.sample_ids[0]}::u0001": {"slot_1": 0.97, "slot_null": 0.01}},
                "diagnostics": {"release_decision": "decompose", "selective_risk_score": 0.11},
                "predicted_count": 1,
                "active_slot_indices": [0],
            }

    batch_rows = build_backend_snapshot_rows_from_debug_batch(
        batch_samples=[_sample()],
        tensor_batch={"unit_mask": [[1]], "gold_counts": [1]},
        backend=FakeBackend(),
    )

    snapshot_jsonl = tmp_path / "backend_snapshots.jsonl"
    prediction_jsonl = tmp_path / "predictions.jsonl"
    prediction_errors = tmp_path / "prediction_errors.jsonl"
    plan_jsonl = tmp_path / "plans.jsonl"
    plan_errors = tmp_path / "plan_errors.jsonl"
    write_jsonl(snapshot_jsonl, batch_rows)

    prediction_summary = export_stage1_predictions(
        backend_snapshot_jsonl=snapshot_jsonl,
        output_jsonl=prediction_jsonl,
        error_jsonl=prediction_errors,
        strict=False,
    )
    plan_summary = export_consumer_plans(
        prediction_jsonl=prediction_jsonl,
        output_jsonl=plan_jsonl,
        error_jsonl=plan_errors,
        review_ready=True,
        strict=False,
    )

    plans = read_jsonl(plan_jsonl)
    assert prediction_summary["sample_counts"]["exported"] == 1
    assert plan_summary["review_ready_exported_count"] == 1
    assert plans[0]["decision"] == "decompose"
    assert plans[0]["predicted_k"] == 1
    assert plans[0]["commit_id"] == "sample_debug"


def test_build_backend_snapshot_rows_from_samples_is_one_row_per_sample() -> None:
    from code.mica.runners.export_stage1_predictions import build_backend_snapshot_rows_from_samples

    class FakeBackend:
        def forward(self, batch):
            return {
                "count_probs": [0.96, 0.04],
                "pb_count_probs": [0.95, 0.05],
                "slot_exist_probs": [0.97, 0.02],
                "assignments": {f"{batch.sample_ids[0]}::u0001": "slot_1"},
                "assignment_scores": {f"{batch.sample_ids[0]}::u0001": {"slot_1": 0.97, "slot_null": 0.01}},
                "diagnostics": {"release_decision": "decompose", "selective_risk_score": 0.11},
                "predicted_count": 1,
                "active_slot_indices": [0],
            }

    rows = build_backend_snapshot_rows_from_samples(
        batch_samples=[_sample("sample_a"), _sample("sample_b")],
        tensor_batch={"unit_mask": [[1], [1]], "gold_counts": [1, 1]},
        backend=FakeBackend(),
    )

    assert [row["sample_id"] for row in rows] == ["sample_a", "sample_b"]
    assert rows[0]["train_batch"]["sample_ids"] == ["sample_a"]
    assert rows[1]["train_batch"]["sample_ids"] == ["sample_b"]


def test_debug_stage1_main_forwards_backend_snapshot_arg(monkeypatch, capsys) -> None:
    from code.mica.train import debug_stage1_attribution as module

    captured: dict[str, object] = {}

    def fake_run_stage1_attribution_debug(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(module, "run_stage1_attribution_debug", fake_run_stage1_attribution_debug)

    exit_code = module.main(
        [
            "--config",
            "code/mica/configs/mica_stage1_sanity.yaml",
            "--backend-snapshot-jsonl",
            "tmp/backend_snapshots.jsonl",
        ]
    )

    assert exit_code == 0
    assert captured["cli_backend_snapshot_jsonl"] == "tmp/backend_snapshots.jsonl"
    assert json.loads(capsys.readouterr().out)["ok"] is True
