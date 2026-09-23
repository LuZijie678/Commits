from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "export_step1_to_step2_source.py"


def make_diff(file_path: str) -> str:
    return "\n".join(
        [
            f"diff --git a/{file_path} b/{file_path}",
            f"--- a/{file_path}",
            f"+++ b/{file_path}",
            "@@ -1 +1 @@",
            "-old",
            "+new",
        ]
    )


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_exporter_accepts_conservative_atomic_sources_and_preserves_metadata(tmp_path: Path) -> None:
    input_csv = tmp_path / "conservative_atomic_sources.csv"
    output_csv = tmp_path / "step2_source.csv"
    manifest_json = tmp_path / "step2_source_manifest.json"
    write_csv(
        input_csv,
        [
            "repo",
            "sha",
            "commit_url",
            "type",
            "subject",
            "message",
            "git_diff",
            "model_prob",
            "model_tier",
            "tau_a",
            "tau_b",
            "rule_label",
            "rule_weight",
            "passed_rule_refilter",
            "conservative_tier",
            "selection_strategy",
            "selection_reason",
            "source_confidence",
        ],
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "commit_url": "https://github.com/owner/repo/commit/sha1",
                "type": "fix",
                "subject": "fix auth parser",
                "message": "fix auth parser in middleware",
                "git_diff": make_diff("src/auth.py"),
                "model_prob": "0.96",
                "model_tier": "A",
                "tau_a": "0.89",
                "tau_b": "0.41",
                "rule_label": "1",
                "rule_weight": "0.85",
                "passed_rule_refilter": "true",
                "conservative_tier": "A",
                "selection_strategy": "model_rule_refilter",
                "selection_reason": "model_tier_a_and_rule_positive",
                "source_confidence": "0.816",
            }
        ],
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(input_csv),
            "--output",
            str(output_csv),
            "--manifest",
            str(manifest_json),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    rows = list(csv.DictReader(output_csv.open("r", encoding="utf-8", newline="")))
    assert len(rows) == 1
    row = rows[0]
    assert row["manual_label"] == "A"
    assert row["source_confidence"] == "0.816"
    assert row["selection_strategy"] == "model_rule_refilter"
    assert row["conservative_tier"] == "A"

    manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
    assert manifest["export"]["input_format"] == "conservative_atomic_sources"
    assert manifest["paths"]["step1_conservative_atomic_sources_csv"] == str(input_csv)


def test_exporter_parse_args_defaults_use_datasets_bridge_layout(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["prog"])
    args = __import__("importlib").util.spec_from_file_location("step2_exporter", SCRIPT)
    assert args is not None
    module = __import__("importlib").util.module_from_spec(args)
    assert args.loader is not None
    args.loader.exec_module(module)
    parsed = module.parse_args()
    assert parsed.input == "../../datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv"
    assert parsed.output == "../../datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv"
    assert parsed.manifest == "../../datasets/derived/step2_bridge/current/step2_source_candidates_from_step1_manifest.json"


def test_exporter_keeps_legacy_resolved_candidates_compatibility(tmp_path: Path) -> None:
    input_csv = tmp_path / "resolved_candidates.csv"
    output_csv = tmp_path / "step2_source.csv"
    manifest_json = tmp_path / "step2_source_manifest.json"
    write_csv(
        input_csv,
        [
            "repo",
            "sha",
            "type",
            "subject",
            "message",
            "git_diff",
            "tier",
            "resolution_status",
        ],
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth parser",
                "message": "fix auth parser in middleware",
                "git_diff": make_diff("src/auth.py"),
                "tier": "A",
                "resolution_status": "resolved_full_diff",
            }
        ],
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(input_csv),
            "--output",
            str(output_csv),
            "--manifest",
            str(manifest_json),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    rows = list(csv.DictReader(output_csv.open("r", encoding="utf-8", newline="")))
    assert len(rows) == 1
    row = rows[0]
    assert row["manual_label"] == "A"
    assert row["source_confidence"] == ""

    manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
    assert manifest["export"]["input_format"] == "resolved_candidates"
    assert manifest["paths"]["step1_resolved_candidates_csv"] == str(input_csv)
