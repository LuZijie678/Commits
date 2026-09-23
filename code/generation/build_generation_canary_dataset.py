from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from build_generation_pilot_dataset import build_pilot_dataset
from common import read_json, read_jsonl, rel_path, repo_path, safe_text, utc_timestamp, write_json, write_jsonl
from repo_identity import attach_repo_identity


MANUAL_REVIEW_FIELDS = [
    "sample_id",
    "data_category",
    "strategy",
    "generated_subject",
    "reference_subject",
    "manual_format_ok",
    "manual_faithful",
    "manual_complete",
    "manual_concise",
    "manual_oversegmentation",
    "manual_omission",
    "manual_hallucination",
    "notes",
]


def build_canary_dataset(config: dict[str, Any], output_root: Path | None = None) -> dict[str, Any]:
    is_probe = "probe" in str(config.get("experiment_name", ""))
    default_root = f"outputs/llm_generation_real_api_probe_{utc_timestamp()}" if is_probe else f"outputs/llm_generation_canary_{utc_timestamp()}"
    output_root = output_root or repo_path(config.get("output_root") or default_root)
    fixed_probe_dataset_root = safe_text((config.get("data_sources") or {}).get("fixed_probe_dataset_root"))
    fixed_probe_root = repo_path(fixed_probe_dataset_root) if is_probe and fixed_probe_dataset_root else None
    if is_probe and fixed_probe_root and (fixed_probe_root / "dataset" / "canary_all.jsonl").exists():
        return _reuse_fixed_probe_dataset(fixed_probe_root, output_root)
    result = build_pilot_dataset(config, output_root)
    dataset_dir = output_root / "dataset"
    all_rows = read_jsonl(dataset_dir / "pilot_all.jsonl")
    manifest = dict(result["manifest"])
    manifest["schema_version"] = "llm_generation_real_api_probe_dataset_v1" if is_probe else "llm_generation_canary_dataset_v1"
    manifest["output_root"] = rel_path(output_root)
    manifest["canary_scope"] = "4-sample real API provider probe" if is_probe else "20-sample low-cost real API canary preparation"
    write_jsonl(dataset_dir / "canary_all.jsonl", all_rows)
    for category in ["atomic_simple", "hard_b", "synthetic_multi", "M_real_multi"]:
        src = dataset_dir / f"pilot_{category}.jsonl"
        rows = read_jsonl(src)
        write_jsonl(dataset_dir / f"canary_{category}.jsonl", rows)
    write_json(dataset_dir / "canary_manifest.json", manifest)
    write_json(dataset_dir / "canary_leakage_report.json", result["leakage"])
    _write_manual_review_template(output_root / "reports" / "canary_manual_review_template.csv", all_rows)
    return {"output_root": output_root, "manifest": manifest, "leakage": result["leakage"], "rows": all_rows}


def _reuse_fixed_probe_dataset(fixed_probe_root: Path, output_root: Path) -> dict[str, Any]:
    dataset_dir = output_root / "dataset"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    rows_by_name: dict[str, list[dict[str, Any]]] = {}
    for name in [
        "pilot_atomic_simple.jsonl",
        "pilot_hard_b.jsonl",
        "pilot_synthetic_multi.jsonl",
        "pilot_M_real_multi.jsonl",
        "pilot_all.jsonl",
        "canary_atomic_simple.jsonl",
        "canary_hard_b.jsonl",
        "canary_synthetic_multi.jsonl",
        "canary_M_real_multi.jsonl",
        "canary_all.jsonl",
    ]:
        rows = [attach_repo_identity(row) for row in read_jsonl(fixed_probe_root / "dataset" / name)]
        rows_by_name[name] = rows
        write_jsonl(dataset_dir / name, rows)
    source_manifest = fixed_probe_root / "dataset" / "canary_manifest.json"
    source_leakage = fixed_probe_root / "dataset" / "canary_leakage_report.json"
    source_pilot_manifest = fixed_probe_root / "dataset" / "pilot_dataset_manifest.json"
    source_pilot_leakage = fixed_probe_root / "dataset" / "pilot_leakage_report.json"
    manifest = {
        **(read_json(source_manifest) if source_manifest.exists() else {}),
        "schema_version": "llm_generation_real_api_probe_dataset_v1",
        "output_root": rel_path(output_root),
        "fixed_probe_dataset_root": rel_path(fixed_probe_root),
        "reuse_mode": "frozen_probe_dataset",
    }
    leakage = read_json(source_leakage) if source_leakage.exists() else {"passed": True, "overlaps": {}, "policy": "reused frozen probe dataset"}
    pilot_manifest = {
        **(read_json(source_pilot_manifest) if source_pilot_manifest.exists() else {}),
        "output_root": rel_path(output_root),
        "fixed_probe_dataset_root": rel_path(fixed_probe_root),
        "reuse_mode": "frozen_probe_dataset",
    }
    pilot_leakage = read_json(source_pilot_leakage) if source_pilot_leakage.exists() else leakage
    write_json(dataset_dir / "pilot_dataset_manifest.json", pilot_manifest)
    write_json(dataset_dir / "pilot_leakage_report.json", pilot_leakage)
    write_json(dataset_dir / "canary_manifest.json", manifest)
    write_json(dataset_dir / "canary_leakage_report.json", leakage)
    _write_manual_review_template(output_root / "reports" / "canary_manual_review_template.csv", rows_by_name["canary_all.jsonl"])
    return {"output_root": output_root, "manifest": manifest, "leakage": leakage, "rows": rows_by_name["canary_all.jsonl"]}


def _write_manual_review_template(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANUAL_REVIEW_FIELDS)
        writer.writeheader()
        for row in rows:
            for strategy in ["G0", "G1", "G4"] + (["G5"] if row.get("data_category") == "synthetic_multi" else []):
                writer.writerow(
                    {
                        "sample_id": row.get("sample_id", ""),
                        "data_category": row.get("data_category", ""),
                        "strategy": strategy,
                        "generated_subject": "",
                        "reference_subject": row.get("subject_reference", ""),
                    }
                )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/llm_generation_canary.mock.json")
    parser.add_argument("--output-root")
    args = parser.parse_args()
    config = json.loads(repo_path(args.config).read_text(encoding="utf-8"))
    result = build_canary_dataset(config, repo_path(args.output_root) if args.output_root else None)
    print(f"wrote {result['manifest']['selected_counts']} to {rel_path(result['output_root'])}")


if __name__ == "__main__":
    main()
