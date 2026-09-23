from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[3] / "scripts" / "check_dataset_readiness.py"
SPEC = importlib.util.spec_from_file_location("check_dataset_readiness", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules["check_dataset_readiness"] = MOD
SPEC.loader.exec_module(MOD)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_live_dataset_tree(root: Path) -> None:
    write_text(root / "datasets/step1/canonical/annotated_dataset.csv", "sha\n1\n")
    write_text(
        root / "datasets/step1/canonical/prefilter_allcommits_step2_sha_and_expanded_annotated_disjoint.csv",
        "sha\n1\n",
    )
    write_text(root / "datasets/step1/runtime_support/resolved_metadata.csv", "sha\n1\n")
    write_text(root / "datasets/step1/runtime_support/resolved_commit_texts.jsonl", "{}\n")
    write_text(root / "datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv", "sha\n1\n")
    write_text(root / "datasets/derived/step1_source_pool/current/source_pool_metadata.json", "{}\n")
    write_text(root / "datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv", "sha\n1\n")
    write_text(
        root / "datasets/derived/step2_bridge/current/step2_source_candidates_from_step1_manifest.json",
        "{}\n",
    )
    write_text(root / "datasets/m_verified/canonical/usable_m_with_real_diff.csv", "sha\n1\n")
    write_text(root / "datasets/step2/delivery/current/fewshot_pool.db", "sqlite")
    write_text(root / "datasets/step2/delivery/current/build_manifest.json", "{}\n")
    write_text(root / "datasets/step2/delivery/current/preflight_report.json", "{}\n")


def test_collect_status_reports_ready_assets_and_warn_only_hard_b_lfs_pointer(tmp_path: Path) -> None:
    make_live_dataset_tree(tmp_path)
    write_text(
        tmp_path / "datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv",
        "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 123\n",
    )

    payload, has_error = MOD.collect_status(tmp_path)

    assert has_error is False
    assert payload["summary"]["ready"] is True
    assert payload["summary"]["error_count"] == 0
    assert payload["summary"]["warning_count"] >= 1
    assert (
        payload["assets"]["datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv"]["status"]
        == "lfs_pointer_only_warn"
    )
    assert (
        payload["assets"]["datasets/step2/delivery/current/fewshot_pool.db"]["status"]
        == "materialized_local_file"
    )


def test_collect_status_fails_when_required_live_asset_missing(tmp_path: Path) -> None:
    make_live_dataset_tree(tmp_path)

    payload, has_error = MOD.collect_status(tmp_path)
    assert has_error is False

    (tmp_path / "datasets/step2/delivery/current/build_manifest.json").unlink()
    payload, has_error = MOD.collect_status(tmp_path)

    assert has_error is True
    assert payload["summary"]["ready"] is False
    assert payload["summary"]["error_count"] >= 1
    assert (
        payload["assets"]["datasets/step2/delivery/current/build_manifest.json"]["status"]
        == "missing_required"
    )


def test_main_writes_status_json_and_returns_zero_for_warn_only_tree(tmp_path: Path, monkeypatch) -> None:
    make_live_dataset_tree(tmp_path)
    write_text(
        tmp_path / "datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv",
        "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 123\n",
    )
    output_path = tmp_path / "manifests/local_asset_status.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--repo-root",
            str(tmp_path),
            "--output",
            str(output_path),
        ],
    )

    code = MOD.main()

    assert code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["summary"]["ready"] is True
