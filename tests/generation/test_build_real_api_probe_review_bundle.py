import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from build_real_api_probe_review_bundle import build_review_bundle
from fixtures import create_real_api_probe_review_fixture


def test_review_bundle_contains_five_probe_records(tmp_path):
    fixture = create_real_api_probe_review_fixture(tmp_path)
    result = build_review_bundle(
        output_root=fixture["output_root"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
    )
    bundle_text = result["bundle_path"].read_text(encoding="utf-8")
    rows = list(csv.DictReader(result["form_path"].open(encoding="utf-8")))
    assert len(rows) == 5
    assert bundle_text.count("## Record ") == 5


def test_review_bundle_includes_retrieval_and_oracle_sections(tmp_path):
    fixture = create_real_api_probe_review_fixture(tmp_path)
    result = build_review_bundle(
        output_root=fixture["output_root"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
    )
    bundle_text = result["bundle_path"].read_text(encoding="utf-8")
    assert "Retrieval Exemplars" in bundle_text
    assert "Similarity score: `0.9`" in bundle_text
    assert "Oracle Intent Plan" in bundle_text
    assert "Oracle intent count: `2`" in bundle_text


def test_review_form_has_strategy_specific_not_applicable_fields(tmp_path):
    fixture = create_real_api_probe_review_fixture(tmp_path)
    result = build_review_bundle(
        output_root=fixture["output_root"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
    )
    rows = list(csv.DictReader(result["form_path"].open(encoding="utf-8")))
    by_key = {(row["sample_id"], row["strategy"]): row for row in rows}
    assert by_key[("atomic_simple:sample1", "G1")]["manual_oracle_plan_copying"] == "not_applicable"
    assert by_key[("atomic_simple:sample1", "G1")]["manual_retrieval_example_reasonable"] == "not_applicable"
    assert by_key[("synthetic_multi:sample3", "G5")]["manual_oracle_plan_copying"] == ""
    assert by_key[("synthetic_multi:sample3", "G4")]["manual_retrieval_example_reasonable"] == ""
    assert by_key[("synthetic_multi:sample3", "G5")]["data_category"] == "synthetic_multi"


def test_review_bundle_uses_timestamped_outputs_and_does_not_leak_key(tmp_path, monkeypatch):
    fixture = create_real_api_probe_review_fixture(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key-value")
    first = build_review_bundle(
        output_root=fixture["output_root"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
        report_timestamp="20260610T110000Z",
    )
    second = build_review_bundle(
        output_root=fixture["output_root"],
        probe_result_json=fixture["probe_result_json"],
        reports_root=fixture["reports_root"],
        report_timestamp="20260610T110100Z",
    )
    assert first["bundle_path"] != second["bundle_path"]
    assert first["form_path"] != second["form_path"]
    assert "secret-key-value" not in first["bundle_path"].read_text(encoding="utf-8")
    assert "secret-key-value" not in first["form_path"].read_text(encoding="utf-8")


def test_review_bundle_can_render_mock_only_outputs(tmp_path):
    fixture = create_real_api_probe_review_fixture(tmp_path)
    real_path = fixture["output_root"] / "generations" / "real" / "generation_outputs.jsonl"
    mock_dir = fixture["output_root"] / "generations" / "mock"
    mock_dir.mkdir(parents=True, exist_ok=True)
    mock_dir.joinpath("generation_outputs.jsonl").write_text(real_path.read_text(encoding="utf-8"), encoding="utf-8")
    real_path.write_text("", encoding="utf-8")
    result = build_review_bundle(
        output_root=fixture["output_root"],
        probe_result_json=None,
        reports_root=fixture["reports_root"],
        mock_only=True,
        real_generation_pending=True,
    )
    bundle_text = result["bundle_path"].read_text(encoding="utf-8")
    assert "mock_only: `True`" in bundle_text
    assert "real_generation_pending: `True`" in bundle_text
    assert bundle_text.count("## Record ") == 5
