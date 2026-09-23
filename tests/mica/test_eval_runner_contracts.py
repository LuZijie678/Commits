from __future__ import annotations

import json

import pytest

from code.mica.io_utils import read_json, write_jsonl
from code.mica.runners.run_alignment_eval import main as alignment_main
from code.mica.runners.run_message_utility_eval import main as message_main
from code.mica.runners.run_real_domain_detection_eval import main as domain_main


def test_real_domain_eval_runner_requires_dry_run_and_writes_contract(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    rows = tmp_path / "rows.jsonl"
    spec.write_text(json.dumps({"final_test_eval_only": True, "no_threshold_tuning_on_final_test": True}), encoding="utf-8")
    write_jsonl(rows, [{"label": 0, "score": 0.1}, {"label": 1, "score": 0.9}])

    with pytest.raises(ValueError, match="--dry-run"):
        domain_main(["--eval-spec", str(spec), "--rows-jsonl", str(rows), "--output-root", str(tmp_path / "out_fail")])

    domain_main(["--eval-spec", str(spec), "--rows-jsonl", str(rows), "--output-root", str(tmp_path / "out"), "--dry-run"])
    saved = read_json(tmp_path / "out" / "real_domain_detection_eval_summary.json")
    assert saved["dry_run"] is True
    assert "auroc" in saved["metrics"]


def test_alignment_eval_runner_writes_oracle_and_predicted_contract(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    rows = tmp_path / "rows.jsonl"
    spec.write_text(json.dumps({"final_test_eval_only": True, "no_threshold_tuning_on_final_test": True}), encoding="utf-8")
    write_jsonl(
        rows,
        [
            {
                "sample_id": "s1",
                "gold_unit_to_intent": {"u1": "i1", "u2": "i2"},
                "pred_unit_to_slot": {"u1": "s1", "u2": "s2"},
                "oracle_unit_to_slot": {"u1": "s2", "u2": "s1"},
                "gold_hunk_to_intent": {"h1": "i1", "h2": "i2"},
                "pred_hunk_to_slot": {"h1": "s1", "h2": "s2"},
                "gold_count": 2,
                "pred_count": 2,
            }
        ],
    )

    alignment_main(["--eval-spec", str(spec), "--rows-jsonl", str(rows), "--output-root", str(tmp_path / "out"), "--dry-run"])
    saved = read_json(tmp_path / "out" / "alignment_eval_summary.json")
    assert saved["dry_run"] is True
    assert "oracle_k_metrics" in saved["rows"][0]
    assert "predicted_k_metrics" in saved["rows"][0]
    assert saved["oracle_predicted_k_separately_reported"] is True
    assert set(saved["aggregates"]) == {"oracle_k", "predicted_k"}
    assert {row["comparison_group"] for row in saved["main_table"]["rows"]} == {"oracle_k", "predicted_k"}


def test_message_utility_eval_runner_marks_proxy_not_human_eval(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    rows = tmp_path / "rows.jsonl"
    spec.write_text(json.dumps({"final_test_eval_only": True, "no_threshold_tuning_on_final_test": True}), encoding="utf-8")
    write_jsonl(
        rows,
        [
            {
                "structured_intent_plan": {"intents": [{"subject": "auth token"}]},
                "message": "update auth token",
                "evidence_terms": ["update", "auth", "token"],
            }
        ],
    )

    message_main(["--eval-spec", str(spec), "--rows-jsonl", str(rows), "--output-root", str(tmp_path / "out"), "--dry-run"])
    saved = read_json(tmp_path / "out" / "message_utility_eval_summary.json")
    assert saved["dry_run"] is True
    assert saved["proxy_not_human_eval"] is True
