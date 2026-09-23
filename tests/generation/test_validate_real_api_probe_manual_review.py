import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from build_real_api_probe_review_bundle import build_review_bundle
from fixtures import create_real_api_probe_review_fixture
from validate_real_api_probe_manual_review import validate_manual_review


def _fill_review_form(path: Path) -> None:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    for row in rows:
        row["manual_format_ok"] = "true"
        row["manual_faithful"] = "true"
        row["manual_complete"] = "true"
        row["manual_concise"] = "true"
        row["manual_oversegmentation"] = "false"
        row["manual_omission"] = "false"
        row["manual_hallucination"] = "false"
        if row["strategy"] == "G5":
            row["manual_oracle_plan_copying"] = "false"
        if row["strategy"] in {"G4", "G5"}:
            row["manual_retrieval_example_reasonable"] = "true"
        row["manual_prompt_defect_detected"] = "false"
        row["manual_overall_accept"] = "true"
        row["manual_confidence"] = "high"
        row["manual_failure_category"] = "none"
        row["notes"] = "ok"
        row["reviewer"] = "advisor"
        row["reviewed_at"] = "2026-06-10T09:30:00Z"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def test_validation_fails_for_unfilled_review_csv(tmp_path):
    fixture = create_real_api_probe_review_fixture(tmp_path)
    bundle = build_review_bundle(
        output_root=fixture["output_root"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
    )
    report = validate_manual_review(
        review_csv=bundle["form_path"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
    )
    assert report["manual_review_completed"] is False
    assert report["reviewed_record_count"] == 0
    assert any("manual_format_ok" in error for error in report["errors"])


def test_validation_requires_reviewer_and_reviewed_at(tmp_path):
    fixture = create_real_api_probe_review_fixture(tmp_path)
    bundle = build_review_bundle(
        output_root=fixture["output_root"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
    )
    _fill_review_form(bundle["form_path"])
    rows = list(csv.DictReader(bundle["form_path"].open(encoding="utf-8")))
    rows[0]["reviewer"] = ""
    rows[1]["reviewed_at"] = ""
    with bundle["form_path"].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    report = validate_manual_review(
        review_csv=bundle["form_path"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
    )
    assert report["manual_review_completed"] is False
    assert any("reviewer" in error for error in report["errors"])
    assert any("reviewed_at" in error for error in report["errors"])


def test_validation_catches_failure_category_inconsistency(tmp_path):
    fixture = create_real_api_probe_review_fixture(tmp_path)
    bundle = build_review_bundle(
        output_root=fixture["output_root"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
    )
    _fill_review_form(bundle["form_path"])
    rows = list(csv.DictReader(bundle["form_path"].open(encoding="utf-8")))
    rows[0]["manual_hallucination"] = "true"
    rows[0]["manual_failure_category"] = "none"
    rows[0]["manual_overall_accept"] = "false"
    with bundle["form_path"].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    report = validate_manual_review(
        review_csv=bundle["form_path"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
    )
    assert report["manual_review_completed"] is False
    assert any("hallucination" in error for error in report["errors"])


def test_validation_accepts_not_applicable_rules_and_keeps_key_out_of_reports(tmp_path, monkeypatch):
    fixture = create_real_api_probe_review_fixture(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key-value")
    bundle = build_review_bundle(
        output_root=fixture["output_root"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
    )
    _fill_review_form(bundle["form_path"])
    report = validate_manual_review(
        review_csv=bundle["form_path"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
    )
    assert report["manual_review_completed"] is True
    text = Path(report["report_json_path"]).read_text(encoding="utf-8") + Path(report["report_md_path"]).read_text(encoding="utf-8")
    assert "secret-key-value" not in text
