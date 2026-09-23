import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from build_real_api_probe_review_bundle import build_review_bundle
from evaluate_real_api_probe_go_no_go import evaluate_probe_go_no_go
from fixtures import create_real_api_probe_review_fixture
from validate_real_api_probe_manual_review import validate_manual_review


def _write_review_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def _complete_review_csv(path: Path, *, prompt_defect: bool = False, hallucination_rows: int = 0) -> None:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    for idx, row in enumerate(rows):
        row["manual_format_ok"] = "true"
        row["manual_faithful"] = "true"
        row["manual_complete"] = "true"
        row["manual_concise"] = "true"
        row["manual_oversegmentation"] = "false"
        row["manual_omission"] = "false"
        row["manual_hallucination"] = "true" if idx < hallucination_rows else "false"
        row["manual_oracle_plan_copying"] = "false" if row["strategy"] == "G5" else "not_applicable"
        row["manual_retrieval_example_reasonable"] = "true" if row["strategy"] in {"G4", "G5"} else "not_applicable"
        row["manual_prompt_defect_detected"] = "true" if prompt_defect else "false"
        row["manual_overall_accept"] = "false" if prompt_defect or idx < hallucination_rows else "true"
        row["manual_confidence"] = "high"
        row["manual_failure_category"] = "prompt_defect" if prompt_defect else ("hallucination" if idx < hallucination_rows else "none")
        row["notes"] = "reviewed"
        row["reviewer"] = "advisor"
        row["reviewed_at"] = "2026-06-10T10:00:00Z"
    _write_review_rows(path, rows)


def test_go_no_go_blocks_prompt_defect(tmp_path):
    fixture = create_real_api_probe_review_fixture(tmp_path)
    bundle = build_review_bundle(
        output_root=fixture["output_root"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
    )
    _complete_review_csv(bundle["form_path"], prompt_defect=True)
    validation = validate_manual_review(
        review_csv=bundle["form_path"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
    )
    report = evaluate_probe_go_no_go(
        probe_result_json=fixture["probe_result_json"],
        manual_review_validation_json=Path(validation["report_json_path"]),
        preflight_json=fixture["preflight_json"],
        reports_root=fixture["reports_root"],
    )
    assert report["recommend_65_request_canary"] is False
    assert report["reason"] == "prompt_revision_required"


def test_go_no_go_blocks_hallucination_rate_above_threshold(tmp_path):
    fixture = create_real_api_probe_review_fixture(tmp_path)
    bundle = build_review_bundle(
        output_root=fixture["output_root"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
    )
    _complete_review_csv(bundle["form_path"], hallucination_rows=2)
    validation = validate_manual_review(
        review_csv=bundle["form_path"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
    )
    report = evaluate_probe_go_no_go(
        probe_result_json=fixture["probe_result_json"],
        manual_review_validation_json=Path(validation["report_json_path"]),
        preflight_json=fixture["preflight_json"],
        reports_root=fixture["reports_root"],
    )
    assert report["recommend_65_request_canary"] is False
    assert report["failed_gates"]["manual_hallucination_rate"] is False


def test_go_no_go_returns_true_when_all_gates_pass(tmp_path):
    fixture = create_real_api_probe_review_fixture(tmp_path)
    bundle = build_review_bundle(
        output_root=fixture["output_root"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
    )
    _complete_review_csv(bundle["form_path"])
    validation = validate_manual_review(
        review_csv=bundle["form_path"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
    )
    report = evaluate_probe_go_no_go(
        probe_result_json=fixture["probe_result_json"],
        manual_review_validation_json=Path(validation["report_json_path"]),
        preflight_json=fixture["preflight_json"],
        reports_root=fixture["reports_root"],
    )
    assert report["recommend_65_request_canary"] is True
    assert report["reason"] == "all_gates_passed"


def test_go_no_go_blocks_when_manual_review_incomplete_and_keeps_key_out_of_reports(tmp_path, monkeypatch):
    fixture = create_real_api_probe_review_fixture(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key-value")
    bundle = build_review_bundle(
        output_root=fixture["output_root"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
    )
    validation = validate_manual_review(
        review_csv=bundle["form_path"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
    )
    report = evaluate_probe_go_no_go(
        probe_result_json=fixture["probe_result_json"],
        manual_review_validation_json=Path(validation["report_json_path"]),
        preflight_json=fixture["preflight_json"],
        reports_root=fixture["reports_root"],
    )
    assert report["recommend_65_request_canary"] is False
    assert report["reason"] == "manual_review_incomplete"
    text = Path(report["report_json_path"]).read_text(encoding="utf-8") + Path(report["report_md_path"]).read_text(encoding="utf-8")
    assert "secret-key-value" not in text
