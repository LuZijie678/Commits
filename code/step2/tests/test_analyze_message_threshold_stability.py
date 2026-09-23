from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "code" / "analyze_message_threshold_stability.py"
SPEC = importlib.util.spec_from_file_location("analyze_message_threshold_stability", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


def write_run_dir(base: Path, name: str, *, t_reject: float, t_pass: float, step3_ready: int, samples: list[dict]) -> Path:
    run_dir = base / name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_metadata.json").write_text(
        json.dumps(
            {
                "thresholds": {
                    "message_threshold_source": "distribution_calibrated",
                    "threshold_method": "kmeans_1d",
                    "t_reject": t_reject,
                    "t_pass": t_pass,
                    "detail": {"centroids": [t_reject - 0.01, (t_reject + t_pass) / 2, t_pass + 0.01]},
                },
                "message_metrics": {
                    "pass": sum(1 for row in samples if row["message_status"] == "pass"),
                    "fallback": sum(1 for row in samples if row["message_status"] == "fallback"),
                    "reject": sum(1 for row in samples if row["message_status"] == "reject"),
                },
                "target_gate": {
                    "step3_ready_count": step3_ready,
                    "generated_count": len(samples),
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with (run_dir / "synthetic_samples.jsonl").open("w", encoding="utf-8") as handle:
        for row in samples:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return run_dir


def test_build_stability_report_tracks_threshold_drift_and_status_variability(tmp_path: Path):
    baseline = write_run_dir(
        tmp_path,
        "baseline",
        t_reject=0.75,
        t_pass=0.79,
        step3_ready=15,
        samples=[
            {"sample_id": "s1", "message_status": "pass", "synthetic_subject": "subject 1", "message_scores": {"message_quality_weight": 0.81}},
            {"sample_id": "s2", "message_status": "fallback", "synthetic_subject": "subject 2", "message_scores": {"message_quality_weight": 0.77}},
            {"sample_id": "s3", "message_status": "reject", "synthetic_subject": "subject 3", "message_scores": {"message_quality_weight": 0.74}},
        ],
    )
    variant = write_run_dir(
        tmp_path,
        "variant",
        t_reject=0.77,
        t_pass=0.80,
        step3_ready=13,
        samples=[
            {"sample_id": "s1", "message_status": "fallback", "synthetic_subject": "subject 1b", "message_scores": {"message_quality_weight": 0.79}},
            {"sample_id": "s2", "message_status": "reject", "synthetic_subject": "subject 2b", "message_scores": {"message_quality_weight": 0.765}},
            {"sample_id": "s3", "message_status": "reject", "synthetic_subject": "subject 3", "message_scores": {"message_quality_weight": 0.73}},
        ],
    )

    report = MOD.build_stability_report([baseline, variant], baseline_run_dir=baseline, near_threshold_margin=0.01)

    assert report["baseline_run"]["run_name"] == "baseline"
    assert report["threshold_drift"]["t_reject_min"] == 0.75
    assert report["threshold_drift"]["t_reject_max"] == 0.77
    assert report["threshold_drift"]["t_pass_min"] == 0.79
    assert report["threshold_drift"]["t_pass_max"] == 0.8
    assert report["aggregate"]["run_count"] == 2
    assert report["aggregate"]["step3_ready_min"] == 13
    assert report["aggregate"]["step3_ready_max"] == 15
    assert report["aggregate"]["status_variability_sample_count"] == 2
    unstable = {item["sample_id"]: item for item in report["status_variability"]}
    assert unstable["s1"]["statuses"] == ["fallback", "pass"]
    assert unstable["s2"]["statuses"] == ["fallback", "reject"]
    assert report["runs"][1]["near_threshold"]["reject_within_margin_count"] == 1
