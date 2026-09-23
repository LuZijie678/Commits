from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "code" / "compare_threshold_methods_fixed_samples.py"
SPEC = importlib.util.spec_from_file_location("compare_threshold_methods_fixed_samples", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


def write_run_dir(base: Path, name: str, rows: list[dict]) -> Path:
    run_dir = base / name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_metadata.json").write_text(
        json.dumps(
            {
                "thresholds": {
                    "threshold_method": "kmeans_1d",
                    "t_reject": 0.76,
                    "t_pass": 0.80,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with (run_dir / "synthetic_samples.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return run_dir


def make_row(sample_id: str, weight: float) -> dict:
    return {
        "sample_id": sample_id,
        "generation_status": "generated",
        "sample_confidence": 1.0,
        "pair_quality_weight": 1.0,
        "synthetic_subject": f"subject {sample_id}",
        "message_scores": {
            "format": 1,
            "bertscore_compute_invalid": 0,
            "message_quality_weight": weight,
        },
    }


def test_compare_threshold_methods_reports_counts_and_diffs(tmp_path: Path):
    run_dir = write_run_dir(
        tmp_path,
        "fixed-run",
        [
            make_row("s1", 0.81),
            make_row("s2", 0.79),
            make_row("s3", 0.765),
            make_row("s4", 0.74),
        ],
    )

    report = MOD.compare_threshold_methods(
        run_dir=run_dir,
        methods=["kmeans_1d", "reference_quantile_band"],
    )

    assert report["run_name"] == "fixed-run"
    assert report["sample_count"] == 4
    assert sorted(report["methods"].keys()) == ["kmeans_1d", "reference_quantile_band"]
    assert report["methods"]["kmeans_1d"]["counts"]["pass"] >= 1
    assert report["methods"]["reference_quantile_band"]["counts"]["reject"] >= 1
    assert report["pairwise_diffs"][0]["left_method"] == "kmeans_1d"
    assert report["pairwise_diffs"][0]["right_method"] == "reference_quantile_band"
