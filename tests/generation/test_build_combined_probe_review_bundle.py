import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from build_combined_probe_review_bundle import build_combined_probe_review_bundle
from fixtures import create_real_api_probe_review_fixture, create_targeted_regression_fixture


def test_combined_bundle_contains_six_records_and_ftxui_evidence(tmp_path):
    base = create_real_api_probe_review_fixture(tmp_path / "base")
    targeted = create_targeted_regression_fixture(tmp_path / "targeted")

    result = build_combined_probe_review_bundle(
        base_probe_output_root=base["output_root"],
        base_probe_result_json=base["probe_result_json"],
        targeted_output_root=targeted["output_root"],
        reports_root=tmp_path / "reports",
    )
    rows = list(csv.DictReader(result["form_path"].open(encoding="utf-8")))
    text = result["bundle_path"].read_text(encoding="utf-8")
    assert len(rows) == 6
    assert "ArthurSonzogni/FTXUI" in text
    assert "arthursonzogni/ftxui" in text
    assert "same_repo_canonical" in text
