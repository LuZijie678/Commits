#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from experiment_tooling_common import (
    build_protocol_blockers,
    detect_pool_type,
    get_git_info,
    infer_run_valid_for_paper,
    load_config_json,
    make_run_id,
    recursive_redact,
    summarize_offline_formal_assets,
    summarize_input_path,
    utc_now_iso,
    write_json,
)


MANIFEST_VERSION = "step2_experiment_manifest_v1"


def build_manifest(
    *,
    project_root: Path,
    config_path: Path,
    source_data_path: Path,
    fewshot_pool_path: Path,
    source_manifest_path: Path | None,
    fewshot_build_manifest_path: Path | None,
    output_dir: Path,
    run_purpose: str,
    random_seed: int,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    config = load_config_json(config_path)
    source_info = summarize_input_path(source_data_path)
    fewshot_info = summarize_input_path(fewshot_pool_path)
    config_info = summarize_input_path(config_path)
    fewshot_info["type"] = detect_pool_type(fewshot_pool_path)
    formal_assets = summarize_offline_formal_assets(
        config=config,
        source_data_path=source_data_path,
        fewshot_pool_path=fewshot_pool_path,
        source_manifest_path=source_manifest_path,
        fewshot_build_manifest_path=fewshot_build_manifest_path,
        run_purpose=run_purpose,
    )
    blockers = build_protocol_blockers(run_purpose, config, source_info, fewshot_info, formal_assets)
    run_valid_for_paper = infer_run_valid_for_paper(run_purpose, config) and not blockers

    payload: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "created_at_utc": utc_now_iso(),
        "project_root": str(project_root.resolve()),
        "git": get_git_info(project_root),
        "run": {
            "run_id": make_run_id(run_purpose, output_dir, config_path, random_seed),
            "run_purpose": run_purpose,
            "config_path": str(config_path),
            "output_dir": str(output_dir),
            "random_seed": int(random_seed),
        },
        "inputs": {
            "source_data": source_info,
            "fewshot_pool": fewshot_info,
            "config": config_info,
            "source_manifest": formal_assets.get("source_manifest", {}),
            "fewshot_build_manifest": formal_assets.get("fewshot_build_manifest", {}),
        },
        "protocol": {
            "message_stage_mandatory": bool(config.get("message_stage_enabled", True)),
            "message_gate_mandatory": bool(config.get("message_gate_enabled", True)),
            "few_shot_mandatory": bool(config.get("fewshot_enabled", True)),
            "formal_assets_ready": bool(formal_assets.get("formal_assets_ready", False)),
            "run_valid_for_paper": bool(run_valid_for_paper),
            "blockers": blockers,
        },
        "notes": list(notes or []),
    }
    return recursive_redact(payload)


def validate_manifest_dict(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_top = ["manifest_version", "created_at_utc", "project_root", "git", "run", "inputs", "protocol", "notes"]
    for key in required_top:
        if key not in payload:
            errors.append(f"missing_top_level:{key}")
    if payload.get("manifest_version") != MANIFEST_VERSION:
        errors.append("invalid_manifest_version")
    run = payload.get("run", {}) or {}
    for key in ["run_id", "run_purpose", "config_path", "output_dir", "random_seed"]:
        if key not in run:
            errors.append(f"missing_run_field:{key}")
    inputs = payload.get("inputs", {}) or {}
    for key in ["source_data", "fewshot_pool", "config", "source_manifest", "fewshot_build_manifest"]:
        if key not in inputs:
            errors.append(f"missing_input_field:{key}")
    protocol = payload.get("protocol", {}) or {}
    for key in [
        "message_stage_mandatory",
        "message_gate_mandatory",
        "few_shot_mandatory",
        "formal_assets_ready",
        "run_valid_for_paper",
        "blockers",
    ]:
        if key not in protocol:
            errors.append(f"missing_protocol_field:{key}")
    serialized = json.dumps(payload, ensure_ascii=False)
    for token in ["DEEPSEEK_API_KEY", "deepseek_api_key", "api_key", "SECRET_KEY_SHOULD_NOT_LEAK"]:
        if token == "DEEPSEEK_API_KEY":
            continue
        if token in serialized:
            errors.append("sensitive_value_present")
            break
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or validate an offline Step2 experiment manifest.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--config", required=True)
    create_parser.add_argument("--source-data", required=True)
    create_parser.add_argument("--fewshot-pool", required=True)
    create_parser.add_argument("--source-manifest", default="")
    create_parser.add_argument("--fewshot-build-manifest", default="")
    create_parser.add_argument("--output-dir", required=True)
    create_parser.add_argument("--run-purpose", required=True, choices=["formal", "api_smoke", "debug", "preflight", "analysis"])
    create_parser.add_argument("--random-seed", type=int, default=42)
    create_parser.add_argument("--out", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("manifest_path")
    return parser.parse_args()


def cmd_create(args: argparse.Namespace) -> int:
    manifest = build_manifest(
        project_root=Path.cwd(),
        config_path=Path(args.config),
        source_data_path=Path(args.source_data),
        fewshot_pool_path=Path(args.fewshot_pool),
        source_manifest_path=Path(args.source_manifest) if args.source_manifest else None,
        fewshot_build_manifest_path=Path(args.fewshot_build_manifest) if args.fewshot_build_manifest else None,
        output_dir=Path(args.output_dir),
        run_purpose=args.run_purpose,
        random_seed=args.random_seed,
    )
    errors = validate_manifest_dict(manifest)
    write_json(Path(args.out), manifest)
    if errors:
        print(json.dumps({"ok": False, "errors": errors, "manifest_path": args.out}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, "manifest_path": args.out}, ensure_ascii=False, indent=2))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_manifest_dict(payload)
    print(json.dumps({"ok": not errors, "errors": errors, "manifest_path": str(path)}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


def main() -> None:
    args = parse_args()
    if args.command == "create":
        raise SystemExit(cmd_create(args))
    if args.command == "validate":
        raise SystemExit(cmd_validate(args))
    raise SystemExit(2)


if __name__ == "__main__":
    main()
