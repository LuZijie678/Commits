from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.data.asset_registry import load_asset_registry, validate_asset_registry
from code.mica.eval.kmax_coverage import build_kmax_coverage_report
from code.mica.experiment.manifest_versioning import build_runner_experiment_manifest
from code.mica.io_utils import read_json, write_json, write_jsonl
from code.mica.run_manifest import build_run_manifest


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit exact-count Kmax readiness and export pending annotation queue.")
    parser.add_argument("--asset-registry", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--kmax", type=int, default=4)
    parser.add_argument("--kmax-tau", type=float)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser


def run_kmax_exact_count_audit(
    *,
    asset_registry_path: str | Path,
    output_root: str | Path,
    kmax: int = 4,
    kmax_tau: float | None = None,
    overwrite: bool = False,
    validate_only: bool = False,
    execute: bool = False,
) -> dict[str, Any]:
    if bool(validate_only) == bool(execute):
        raise ValueError("Kmax exact-count audit requires exactly one of --validate-only or --execute.")
    asset_registry = load_asset_registry(str(asset_registry_path))
    asset_registry_validation = validate_asset_registry(asset_registry)
    experiment_manifest = build_runner_experiment_manifest(
        runner_name="run_kmax_exact_count_audit",
        config_paths=[],
        asset_registry_path=str(asset_registry_path),
        seed=0,
        mode="execute" if execute else "validate_only",
        advisor_approval=False,
    )

    output_root_path = Path(output_root)
    _ensure_output_root(output_root_path, overwrite=overwrite)
    manifest_json = output_root_path / "kmax_exact_count_audit_manifest.json"
    report_json = output_root_path / "kmax_exact_count_report.json"
    exact_rows_jsonl = output_root_path / "kmax_exact_count_rows.jsonl"
    queue_jsonl = output_root_path / "kmax_exact_count_annotation_queue.jsonl"

    exact_rows = _load_exact_count_rows_from_registry(asset_registry)
    report = build_kmax_coverage_report(
        exact_rows,
        kmax=kmax,
        tau=kmax_tau,
    )
    queue_rows = _build_annotation_queue(asset_registry)
    report["annotation_queue_path"] = queue_jsonl.name if execute else None
    report["annotation_queue_row_count"] = len(queue_rows)
    report["annotation_gap_summary"] = _annotation_gap_summary(report=report, queue_rows=queue_rows)
    report["source_manifest_hashes"] = _source_manifest_hashes(asset_registry, exact_rows)
    report["asset_registry_validation"] = asset_registry_validation
    report["experiment_manifest"] = experiment_manifest

    if execute:
        write_json(report_json, report)
        write_jsonl(exact_rows_jsonl, exact_rows)
        write_jsonl(queue_jsonl, queue_rows)

    result = build_run_manifest(
        stage="stage1_kmax_exact_count_audit",
        mode="execute" if execute else "validate_only",
        output_root=str(output_root_path),
        flags={
            "training_enabled": False,
            "official_validation_executed": False,
            "completion_status": "completed" if execute else "not_executed",
            "kmax_frozen": report["selected_Kmax"]["status"] == "frozen_before_final_evaluation",
            "blocked_by_missing_asset": report["selected_Kmax"]["status"] != "frozen_before_final_evaluation",
            "metadata": {
                "report_path": report_json.name if execute else None,
                "exact_rows_path": exact_rows_jsonl.name if execute else None,
                "queue_path": queue_jsonl.name if execute else None,
                "exact_row_count": len(exact_rows),
                "queue_row_count": len(queue_rows),
                "experiment_manifest": experiment_manifest,
            },
        },
        inputs={
            "asset_registry": asset_registry_path,
            "kmax": kmax,
            "kmax_tau": kmax_tau,
        },
    )
    write_json(manifest_json, result)
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_kmax_exact_count_audit(
        asset_registry_path=args.asset_registry,
        output_root=args.output_root,
        kmax=args.kmax,
        kmax_tau=args.kmax_tau,
        overwrite=bool(args.overwrite),
        validate_only=bool(args.validate_only),
        execute=bool(args.execute),
    )
    return 0


def _load_exact_count_rows_from_registry(asset_registry: dict[str, Any]) -> list[dict[str, Any]]:
    assets = dict(asset_registry.get("assets", {}))
    rows: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for asset_name, payload in sorted(assets.items()):
        if not isinstance(payload, dict):
            continue
        if str(payload.get("status") or "") != "frozen":
            continue
        if str(payload.get("schema_version") or "") != "mica-formal-asset-manifest-v1":
            continue
        path = payload.get("path")
        if not path:
            continue
        manifest = read_json(path)
        for row in manifest.get("rows", []) if isinstance(manifest, dict) else []:
            if not isinstance(row, dict):
                continue
            key = (
                str(row.get("sample_id") or ""),
                str(row.get("split") or ""),
                str(row.get("source_type") or row.get("source_kind") or ""),
                str(row.get("commit_id") or row.get("source_sha") or ""),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            rows.append(dict(row, asset_name=str(asset_name)))
    return rows


def _build_annotation_queue(asset_registry: dict[str, Any]) -> list[dict[str, Any]]:
    assets = dict(asset_registry.get("assets", {}))
    queue_rows: list[dict[str, Any]] = []
    for asset_name in (
        "m_weak_train",
        "m_weak_dev",
        "m_weak_test",
        "hard_b_train",
        "hard_b_dev",
        "hard_b_test",
    ):
        payload = dict(assets.get(asset_name, {}))
        path = payload.get("path")
        if not path:
            continue
        manifest = read_json(path)
        for row in manifest.get("rows", []) if isinstance(manifest, dict) else []:
            if not isinstance(row, dict):
                continue
            queue_rows.append(
                {
                    "commit_id": str(row.get("commit_id") or row.get("sample_id") or ""),
                    "sample_id": str(row.get("sample_id") or ""),
                    "repository": str(row.get("repo") or row.get("repository") or ""),
                    "split_candidate": str(row.get("split") or payload.get("split") or "unspecified"),
                    "source_asset": asset_name,
                    "source_kind": str(row.get("source_kind") or row.get("source_type") or ""),
                    "current_weak_label": str(
                        row.get("weak_label")
                        or row.get("cardinality_label_type")
                        or row.get("source_type")
                        or row.get("source_kind")
                        or "unknown"
                    ),
                    "diff_evidence_reference": str(path),
                    "leakage_group": str(row.get("leakage_group") or ""),
                    "annotation_status": "pending",
                    "annotation_fields": {
                        "exact_k": None,
                        "adjudication_status": "pending",
                        "annotator": None,
                        "notes": "",
                    },
                }
            )
    return queue_rows


def _annotation_gap_summary(*, report: dict[str, Any], queue_rows: list[dict[str, Any]]) -> dict[str, Any]:
    train_dev_basis = dict(report.get("train_dev_selection_basis", {}))
    exact_multi = int(train_dev_basis.get("exact_real_multi_intent_row_count", 0) or 0)
    return {
        "exact_real_multi_intent_train_dev_rows": exact_multi,
        "additional_exact_multi_intent_rows_required": 1 if exact_multi <= 0 else 0,
        "queue_available": bool(queue_rows),
        "recommended_annotation_batch_size_min": max(25, 1 - exact_multi) if exact_multi <= 0 else 0,
    }


def _source_manifest_hashes(asset_registry: dict[str, Any], exact_rows: list[dict[str, Any]]) -> dict[str, str | None]:
    assets = dict(asset_registry.get("assets", {}))
    asset_names = sorted({str(row.get("asset_name") or "") for row in exact_rows if str(row.get("asset_name") or "")})
    return {
        asset_name: (dict(assets.get(asset_name, {})).get("sha256") or dict(assets.get(asset_name, {})).get("checksum"))
        for asset_name in asset_names
    }


def _ensure_output_root(path: Path, *, overwrite: bool) -> None:
    if path.exists():
        if any(path.iterdir()) and not overwrite:
            raise FileExistsError(f"Output directory is not empty: {path}")
    else:
        path.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
