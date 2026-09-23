from __future__ import annotations

import json

from code.mica.io_utils import read_json, write_jsonl
from code.mica.runners.run_real_domain_detection_eval import run_real_domain_detection_eval


def test_real_domain_eval_runner_computes_metrics_and_writes_md(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    rows = tmp_path / "rows.jsonl"
    spec.write_text(json.dumps({"final_test_eval_only": True, "no_threshold_tuning_on_final_test": True}), encoding="utf-8")
    write_jsonl(
        rows,
        [
            {"task": "RealDomainSplit", "label": 0, "score": 0.1},
            {"task": "RealDomainSplit", "label": 0, "score": 0.2},
            {"task": "RealDomainSplit", "label": 1, "score": 0.8},
            {"task": "RealDomainSplit", "label": 1, "score": 0.9},
            {"task": "RealDomainSelective", "in_scope_label": 1, "risk_score": 0.2, "covered": True, "abstained": False},
            {"task": "RealDomainSelective", "in_scope_label": 0, "risk_score": 0.8, "covered": False, "abstained": True},
            {"task": "RealDomainSelective", "in_scope_label": 1, "risk_score": 0.7, "covered": False, "abstained": True},
            {"task": "RealDomainSelective", "in_scope_label": 0, "risk_score": 0.1, "covered": True, "abstained": False},
        ],
    )

    summary = run_real_domain_detection_eval(eval_spec_path=spec, rows_jsonl=rows, output_root=tmp_path / "out", dry_run=True)
    saved = read_json(tmp_path / "out" / "real_domain_detection_eval_summary.json")

    assert summary["metrics"]["auroc"] == 1.0
    assert saved["real_domain_split"]["row_count"] == 4
    assert saved["real_domain_split"]["table"]["table_name"] == "real_domain_split"
    assert saved["real_domain_split"]["metric_registry_validation"]["valid"] is True
    assert saved["real_domain_selective"]["row_count"] == 4
    assert saved["real_domain_selective"]["table"]["table_name"] == "real_domain_selective"
    assert saved["real_domain_selective"]["metrics"]["coverage"] == 0.5
    assert saved["real_domain_selective"]["metrics"]["abstention_precision"] == 0.5
    assert saved["real_domain_selective"]["metrics"]["implicit_risk_threshold_used"] is False
    assert saved["real_domain_selective"]["metric_registry_validation"]["valid"] is True
    assert saved["real_domain_selective"]["thresholds_selected_on_final_test"] is False
    assert saved["experiment_manifest"]["runner_name"] == "run_real_domain_detection_eval"
    assert saved["report_schema"]["schema_version"] == "mica-report-v1"
    assert saved["report_markdown_written"] is True
