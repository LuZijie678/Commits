from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "code" / "run_multiseed_step2_baseline.py"
SPEC = importlib.util.spec_from_file_location("run_multiseed_step2_baseline", MODULE_PATH)
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
                    "t_reject": 0.75,
                    "t_pass": 0.79,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "message_gate_report.json").write_text(
        json.dumps(
            {
                "message_gate_passed": True,
                "target_gate_passed": False,
                "step3_ready_count": 2,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with (run_dir / "synthetic_samples.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return run_dir


def make_row(sample_id: str, status: str, weight: float) -> dict:
    return {
        "sample_id": sample_id,
        "message_status": status,
        "synthetic_subject": f"subject {sample_id}",
        "message_scores": {
            "message_quality_weight": weight,
        },
    }


def test_summarize_run_reads_counts_from_samples_and_gate_report(tmp_path: Path):
    run_dir = write_run_dir(
        tmp_path,
        "seed_7",
        [
            make_row("s1", "pass", 0.81),
            make_row("s2", "fallback", 0.78),
            make_row("s3", "reject", 0.73),
        ],
    )

    summary = MOD.summarize_run(run_dir)

    assert summary["run_dir"] == str(run_dir)
    assert summary["threshold_method"] == "kmeans_1d"
    assert summary["t_reject"] == 0.75
    assert summary["t_pass"] == 0.79
    assert summary["step3_ready_count"] == 2
    assert summary["generated_count"] == 3
    assert summary["pass"] == 1
    assert summary["fallback"] == 1
    assert summary["reject"] == 1
    assert summary["message_gate_passed"] is True
    assert summary["target_gate_passed"] is False
