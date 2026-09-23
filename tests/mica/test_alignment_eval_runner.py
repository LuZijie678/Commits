from __future__ import annotations

import json

from code.mica.io_utils import read_json, write_jsonl
from code.mica.runners.run_alignment_eval import run_alignment_eval


def test_alignment_eval_runner_computes_full_metric_set(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    rows = tmp_path / "rows.jsonl"
    spec.write_text(json.dumps({"final_test_eval_only": True, "no_threshold_tuning_on_final_test": True}), encoding="utf-8")
    write_jsonl(
        rows,
        [
            {
                "sample_id": "s1",
                "gold_unit_to_intent": {"u1": "i1", "u2": "i2"},
                "pred_unit_to_slot": {"u1": "slot_1", "u2": "slot_2"},
                "oracle_unit_to_slot": {"u1": "slot_2", "u2": "slot_1"},
                "oracle_hunk_to_slot": {"h1": "slot_2", "h2": "slot_1"},
                "gold_hunk_to_intent": {"h1": "i1", "h2": "i2"},
                "pred_hunk_to_slot": {"h1": "slot_1", "h2": "slot_2"},
                "gold_count": 2,
                "pred_count": 2,
            }
        ],
    )

    summary = run_alignment_eval(eval_spec_path=spec, rows_jsonl=rows, output_root=tmp_path / "out", dry_run=True)
    saved = read_json(tmp_path / "out" / "alignment_eval_summary.json")

    assert summary["aggregate"]["mean_unit_accuracy"] == 1.0
    assert summary["aggregate"] == summary["aggregates"]["predicted_k"]
    assert summary["aggregates"]["oracle_k"]["sample_count"] == 1
    assert "mean_ari" in saved["aggregate"]
    assert saved["oracle_predicted_k_separately_reported"] is True
    assert {row["comparison_group"] for row in saved["main_table"]["rows"]} == {"oracle_k", "predicted_k"}
    assert saved["experiment_manifest"]["runner_name"] == "run_alignment_eval"
    assert saved["report_schema"]["schema_version"] == "mica-report-v1"
    assert saved["report_markdown_written"] is True


def test_alignment_eval_runner_excludes_uncertain_units_from_primary_metrics(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    rows = tmp_path / "rows.jsonl"
    spec.write_text(json.dumps({"final_test_eval_only": True, "no_threshold_tuning_on_final_test": True}), encoding="utf-8")
    write_jsonl(
        rows,
        [
            {
                "sample_id": "s1",
                "gold_unit_to_intent": {"u1": "i1", "u2": "i1", "u3": "i2"},
                "pred_unit_to_slot": {"u1": "slot_1", "u2": "slot_1", "u3": "slot_1"},
                "oracle_unit_to_slot": {"u1": "slot_2", "u2": "slot_2", "u3": "slot_3"},
                "gold_count": 2,
                "pred_count": 2,
                "uncertain_units": ["u3"],
            }
        ],
    )

    summary = run_alignment_eval(eval_spec_path=spec, rows_jsonl=rows, output_root=tmp_path / "out", dry_run=True)
    row = summary["rows"][0]

    assert row["alignment_mask_protocol"] == "foreground_only_excludes_uncertain_shared_support_mixed"
    assert row["excluded_alignment_unit_ids"] == ["u3"]
    assert row["predicted_k_metrics"]["pairwise_f1"] == 1.0
