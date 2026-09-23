from __future__ import annotations

from code.mica.io_utils import read_json, write_json, write_jsonl
from code.mica.runners.run_ood_stress_eval import run_ood_stress_eval


def test_run_ood_stress_eval_writes_slice_summary(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    rows = tmp_path / "rows.jsonl"
    out = tmp_path / "out"
    write_json(spec, {"stage": "ood_stress_eval", "dryrun_only": True})
    write_jsonl(
        rows,
        [
            {"sample_id": "s1", "slices": ["cross_project"], "pairwise_f1": 0.7},
            {"sample_id": "s2", "slices": ["cross_project", "k_ge_3_stress"], "pairwise_f1": 0.5},
        ],
    )

    summary = run_ood_stress_eval(eval_spec_path=spec, rows_jsonl=rows, output_root=out, dry_run=True)
    saved = read_json(out / "ood_stress_eval_summary.json")

    assert summary["slice_report"]["slice_count"] == 2
    assert saved["thresholds_applied_to_pass_fail"] is False
