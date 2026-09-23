from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from code.mica.io_utils import read_json, write_json

def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Future Stage 2 Input Audit",
        "",
        f"- `audit_only`: {payload['audit_only']}",
        f"- `stage2_training_enabled`: {payload['stage2_training_enabled']}",
        f"- `requires_stage1_official_validation`: {payload['requires_stage1_official_validation']}",
        "",
        "## Inputs",
        "",
        f"- `hard_b_loaded`: {payload['hard_b_loaded']}",
        f"- `m_weak_loaded`: {payload['m_weak_loaded']}",
        "",
        "## Diagnostics",
        "",
    ]
    for item in payload["diagnostics"]:
        lines.append(f"- `{item['code']}`: {item['message']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit future Stage 2 inputs without enabling training.")
    parser.add_argument("--stage1-freeze-report", required=True)
    parser.add_argument("--hard-b-path")
    parser.add_argument("--m-weak-path")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--pseudo-label", action="store_true")
    return parser


def _summarize_optional_input(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "row_count": 0, "field_names": [], "field_presence_summary": {}, "duplicate_sample_id_count": 0, "duplicate_sha_count": 0, "possible_split_values": [], "leakage_check_ready": False}
    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = read_json(path)
        field_names = sorted(payload.keys()) if isinstance(payload, dict) else []
        rows = [payload] if isinstance(payload, dict) else []
        return _row_summary(rows, field_names)
    if suffix == ".jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        field_names = sorted(rows[0].keys()) if rows else []
        return _row_summary(rows, field_names)
    if suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
        return _row_summary(rows, list(reader.fieldnames or []))
    return {"exists": True, "row_count": 0, "field_names": [], "field_presence_summary": {}, "duplicate_sample_id_count": 0, "duplicate_sha_count": 0, "possible_split_values": [], "leakage_check_ready": False}


def _row_summary(rows: list[dict[str, Any]], field_names: list[str]) -> dict[str, Any]:
    sample_ids = [str(row.get("sample_id")) for row in rows if row.get("sample_id") not in {None, ""}]
    shas = [str(row.get("sha")) for row in rows if row.get("sha") not in {None, ""}]
    split_values = sorted({str(row.get("split")) for row in rows if row.get("split") not in {None, ""}})
    field_presence_summary = {
        "sample_id": any("sample_id" in row and row.get("sample_id") not in {None, ""} for row in rows),
        "repo": any("repo" in row and row.get("repo") not in {None, ""} for row in rows),
        "sha": any("sha" in row and row.get("sha") not in {None, ""} for row in rows),
        "git_diff_or_diff": any(any(key in row and row.get(key) not in {None, ""} for key in ("git_diff", "diff")) for row in rows),
        "weak_label": any(any(key in row and row.get(key) not in {None, ""} for key in ("weak_label", "label", "is_multi_intent")) for row in rows),
        "split": any("split" in row and row.get("split") not in {None, ""} for row in rows),
    }
    return {
        "exists": True,
        "row_count": len(rows),
        "field_names": field_names,
        "field_presence_summary": field_presence_summary,
        "duplicate_sample_id_count": len(sample_ids) - len(set(sample_ids)),
        "duplicate_sha_count": len(shas) - len(set(shas)),
        "possible_split_values": split_values,
        "leakage_check_ready": field_presence_summary["sample_id"] and field_presence_summary["sha"],
    }


def audit_future_stage2_inputs(
    *,
    stage1_freeze_report_path: str | Path,
    output_root: str | Path,
    audit_only: bool = False,
    hard_b_path: str | Path | None = None,
    m_weak_path: str | Path | None = None,
    train: bool = False,
    calibrate: bool = False,
    pseudo_label: bool = False,
) -> dict[str, Any]:
    if train or calibrate or pseudo_label:
        raise ValueError("Stage 2 training/calibration is forbidden before official Stage 1 validation and advisor approval.")
    if not audit_only:
        raise ValueError("Future Stage 2 input audit requires explicit --audit-only.")

    freeze_report = read_json(Path(stage1_freeze_report_path))
    hard_b_summary = _summarize_optional_input(Path(hard_b_path)) if hard_b_path else {"exists": False, "row_count": 0, "field_names": [], "field_presence_summary": {}, "duplicate_sample_id_count": 0, "duplicate_sha_count": 0, "possible_split_values": [], "leakage_check_ready": False}
    m_weak_summary = _summarize_optional_input(Path(m_weak_path)) if m_weak_path else {"exists": False, "row_count": 0, "field_names": [], "field_presence_summary": {}, "duplicate_sample_id_count": 0, "duplicate_sha_count": 0, "possible_split_values": [], "leakage_check_ready": False}
    diagnostics: list[dict[str, Any]] = []
    if freeze_report.get("stage2_allowed") is not False:
        diagnostics.append({"code": "stage2_not_blocked", "severity": "warning", "message": "Freeze report no longer blocks Stage 2."})

    result = {
        "run_id": f"future_stage2_input_audit_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stage2_training_enabled": False,
        "stage2_preparation_only": True,
        "audit_only": True,
        "requires_stage1_official_validation": True,
        "hard_b_loaded": bool(hard_b_summary["exists"]),
        "m_weak_loaded": bool(m_weak_summary["exists"]),
        "pseudo_label_generated": False,
        "pseudo_label_enabled": False,
        "threshold_tuning_performed": False,
        "threshold_tuning_enabled": False,
        "training_invoked": False,
        "leakage_preparation_only": True,
        "hard_b_summary": hard_b_summary,
        "m_weak_summary": m_weak_summary,
        "diagnostics": diagnostics,
    }
    output_root_path = Path(output_root)
    write_json(output_root_path / "future_stage2_input_audit.json", result)
    _write_markdown(output_root_path / "future_stage2_input_audit.md", result)
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    audit_future_stage2_inputs(
        stage1_freeze_report_path=args.stage1_freeze_report,
        hard_b_path=args.hard_b_path,
        m_weak_path=args.m_weak_path,
        output_root=args.output_root,
        audit_only=bool(args.audit_only),
        train=bool(args.train),
        calibrate=bool(args.calibrate),
        pseudo_label=bool(args.pseudo_label),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
