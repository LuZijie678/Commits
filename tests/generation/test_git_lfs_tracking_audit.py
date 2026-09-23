import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "tools"))

from audit_git_lfs_tracking import audit_tracking, classify_tracked_file


def test_classifies_runtime_outputs_without_flagging_canonical_datasets():
    assert classify_tracked_file("outputs/llm_generation_pilot_20260609T000000Z/generations/mock/out.jsonl") == "likely_temporary_outputs"
    assert classify_tracked_file("outputs/step3_balanced_diagnostic_readiness_20260604T014128Z/strict/step3_bootstrap_test.jsonl") == "likely_temporary_outputs"
    assert classify_tracked_file("datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv") == "likely_formal_data_assets"
    assert classify_tracked_file("datasets/m_verified/canonical/usable_m_with_real_diff.jsonl") == "likely_formal_data_assets"


def test_audit_tracking_reports_required_fields(tmp_path):
    tracked = [
        "outputs/llm_generation_pilot_20260609T000000Z/generations/mock/out.jsonl",
        "datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv",
        "README.md",
    ]
    lfs = ["abc123 * datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv"]
    report = audit_tracking(
        tracked_files=tracked,
        lfs_lines=lfs,
        gitattributes_text="datasets/**/*.csv filter=lfs diff=lfs merge=lfs -text\n",
        gitignore_text="outputs/llm_generation_pilot_*/\n",
        repo_root=tmp_path,
    )
    assert report["tracked_output_file_count"] == 1
    assert report["lfs_file_count"] == 1
    assert report["likely_temporary_outputs"]
    assert "datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv" in report["likely_formal_data_assets"]
    assert "tracked_outputs_by_experiment_root" in report
