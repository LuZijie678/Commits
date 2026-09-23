from __future__ import annotations

import json

from code.mica.io_utils import read_json, write_jsonl
from code.mica.runners.run_message_utility_eval import run_message_utility_eval


def test_message_utility_eval_runner_computes_proxy_metrics(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    rows = tmp_path / "rows.jsonl"
    spec.write_text(json.dumps({"final_test_eval_only": True, "no_threshold_tuning_on_final_test": True}), encoding="utf-8")
    write_jsonl(
        rows,
        [
            {
                "sample_id": "s1",
                "rendering_mode": "predicted_slots",
                "structured_intent_plan": {"intents": [{"subject": "update auth token", "type": "update", "scope": "auth", "body": "token"}]},
                "message": "update auth token validation",
                "evidence_terms": ["update", "auth", "token", "validation"],
                "proxy_not_human_eval": True,
            },
            {
                "sample_id": "s1",
                "rendering_mode": "oracle_slots",
                "structured_intent_plan": {"intents": [{"subject": "update auth token", "type": "update", "scope": "auth", "body": "token"}]},
                "message": "update auth token",
                "evidence_terms": ["update", "auth", "token"],
                "proxy_not_human_eval": True,
            },
            {
                "sample_id": "s1",
                "rendering_mode": "direct_diff",
                "structured_intent_plan": {"intents": [{"subject": "update auth token", "type": "update", "scope": "auth", "body": "token"}]},
                "message": "update auth token validation",
                "evidence_terms": ["update", "auth", "token", "validation"],
                "proxy_not_human_eval": True,
            }
        ],
    )

    summary = run_message_utility_eval(eval_spec_path=spec, rows_jsonl=rows, output_root=tmp_path / "out", dry_run=True)
    saved = read_json(tmp_path / "out" / "message_utility_eval_summary.json")

    assert summary["proxy_not_human_eval"] is True
    assert "specificity_proxy_mean" in saved
    assert saved["message_utility_modes_separately_reported"] is True
    assert set(saved["mode_summaries"]) == {"direct_diff", "oracle_slots", "predicted_slots"}
    assert saved["oracle_vs_predicted_rendering"]["paired_count"] == 1
    assert {row["comparison_group"] for row in saved["main_table"]["rows"]} == {"direct_diff", "oracle_slots", "predicted_slots"}
    assert saved["experiment_manifest"]["runner_name"] == "run_message_utility_eval"
    assert saved["report_schema"]["schema_version"] == "mica-report-v1"
    assert saved["report_markdown_written"] is True
