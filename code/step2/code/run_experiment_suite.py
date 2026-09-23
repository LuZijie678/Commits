#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import check_dataset_leakage
import experiment_manifest
import experiment_metrics
import experiment_report
import export_audit_samples
from experiment_tooling_common import load_config_json, load_json, write_json


def run_suite(*, config_path: Path, dry_run: bool) -> dict[str, Any]:
    config = load_config_json(config_path)
    if not config:
        raise RuntimeError(f"Invalid suite config: {config_path}")

    output_dir = Path(config.get("output_dir", ""))
    run_purpose = config.get("run_purpose", "analysis")
    source_data = Path(config.get("source_data", ""))
    fewshot_pool = Path(config.get("fewshot_pool", ""))
    fewshot_audit_report = Path(config.get("fewshot_audit_report", "")) if config.get("fewshot_audit_report", "") else None
    source_manifest = Path(config.get("source_manifest", "")) if config.get("source_manifest", "") else None
    fewshot_build_manifest = Path(config.get("fewshot_build_manifest", "")) if config.get("fewshot_build_manifest", "") else None
    strict_fewshot_audit = bool(config.get("strict_fewshot_audit", False))
    step_flags = dict(config.get("steps", {}) or {})

    manifest_path = output_dir / "experiment_manifest.json"
    metrics_path = output_dir / "experiment_metrics.json"
    metrics_md_path = output_dir / "experiment_metrics.md"
    report_json_path = output_dir / "experiment_report.json"
    report_md_path = output_dir / "experiment_report.md"
    leakage_path = output_dir / "dataset_leakage_report.json"
    audit_message_path = output_dir / "audit_message_sample.csv"
    audit_structural_path = output_dir / "audit_structural_sample.csv"
    audit_source_path = output_dir / "audit_source_sample.csv"

    actions: list[dict[str, Any]] = []
    if step_flags.get("manifest", True):
        actions.append({"step": "manifest", "out": str(manifest_path)})
    if step_flags.get("metrics", True):
        actions.append({"step": "metrics", "out": str(metrics_path)})
    if step_flags.get("report", True):
        actions.append({"step": "report", "out": str(report_json_path)})
    if step_flags.get("fewshot_audit", False) or fewshot_audit_report is not None:
        actions.append(
            {
                "step": "fewshot_audit",
                "path": str(fewshot_audit_report) if fewshot_audit_report is not None else "",
                "strict": strict_fewshot_audit,
            }
        )
    if step_flags.get("leakage", False):
        actions.append({"step": "leakage", "out": str(leakage_path)})
    if step_flags.get("audit_export", False):
        actions.append(
            {
                "step": "audit_export",
                "outputs": {
                    "message": str(audit_message_path),
                    "structural": str(audit_structural_path),
                    "source": str(audit_source_path),
                },
            }
        )

    payload = {
        "suite_name": config.get("suite_name", ""),
        "config_path": str(config_path),
        "output_dir": str(output_dir),
        "run_purpose": run_purpose,
        "dry_run": bool(dry_run),
        "actions": actions,
    }
    if dry_run:
        return payload
    if not output_dir.exists() or not output_dir.is_dir():
        raise RuntimeError(f"Output directory does not exist: {output_dir}")

    manifest = None
    if step_flags.get("manifest", True):
        manifest = experiment_manifest.build_manifest(
            project_root=Path.cwd(),
            config_path=Path(config.get("config_path", "")),
            source_data_path=source_data,
            fewshot_pool_path=fewshot_pool,
            source_manifest_path=source_manifest,
            fewshot_build_manifest_path=fewshot_build_manifest,
            output_dir=output_dir,
            run_purpose=run_purpose,
            random_seed=int(config.get("random_seed", config.get("seed", 42))),
        )
        write_json(manifest_path, manifest)

    metrics = None
    if step_flags.get("metrics", True):
        metrics = experiment_metrics.aggregate_experiment_metrics(output_dir=output_dir)
        write_json(metrics_path, metrics)
        from experiment_tooling_common import write_markdown

        write_markdown(metrics_md_path, experiment_metrics.render_markdown(metrics))

    if step_flags.get("report", True):
        if manifest is None:
            manifest = load_json(manifest_path)
        if metrics is None:
            metrics = load_json(metrics_path)
        run_metadata_path = output_dir / "run_metadata.json"
        gate_report_path = output_dir / "message_gate_report.json"
        fewshot_audit_payload = None
        if fewshot_audit_report is not None:
            if fewshot_audit_report.exists():
                fewshot_audit_payload = load_json(fewshot_audit_report)
            elif strict_fewshot_audit:
                raise RuntimeError(f"Few-shot audit report not found: {fewshot_audit_report}")
        report = experiment_report.build_experiment_report(
            manifest=manifest,
            metrics=metrics,
            run_metadata=load_json(run_metadata_path) if run_metadata_path.exists() else {},
            gate_report=load_json(gate_report_path) if gate_report_path.exists() else None,
            fewshot_audit=fewshot_audit_payload,
        )
        write_json(report_json_path, report)
        from experiment_tooling_common import write_markdown

        write_markdown(report_md_path, experiment_report.render_markdown(report))

    if step_flags.get("leakage", False):
        leakage_cfg = dict(config.get("leakage", {}) or {})
        dataset_specs: list[tuple[str, Path]] = []
        dataset_specs.append(("source", source_data))
        if fewshot_pool:
            dataset_specs.append(("fewshot", fewshot_pool))
        for item in leakage_cfg.get("datasets", []):
            if isinstance(item, str) and "=" in item:
                name, raw_path = item.split("=", 1)
                dataset_specs.append((name.strip(), Path(raw_path.strip())))
        payload_leakage = check_dataset_leakage.build_leakage_report(
            dataset_specs=dataset_specs,
            require_sha_disjoint=bool(leakage_cfg.get("require_sha_disjoint", True)),
            require_repo_disjoint=bool(leakage_cfg.get("require_repo_disjoint", True)),
            max_examples=int(leakage_cfg.get("max_examples", 10)),
        )
        write_json(leakage_path, payload_leakage)

    if step_flags.get("audit_export", False):
        audit_cfg = dict(config.get("audit_export", {}) or {})
        synthetic_input = output_dir / "synthetic_samples.jsonl"
        message_n = int(audit_cfg.get("message_n", 50))
        structural_n = int(audit_cfg.get("structural_n", 50))
        source_n = int(audit_cfg.get("source_n", 50))
        seed = int(audit_cfg.get("seed", config.get("random_seed", config.get("seed", 42))))
        export_audit_samples.export_audit_csv(
            input_path=synthetic_input,
            output_path=audit_message_path,
            audit_type="message",
            n=message_n,
            seed=seed,
            stratify_fields=list(audit_cfg.get("message_stratify", ["message_status"])),
        )
        export_audit_samples.export_audit_csv(
            input_path=synthetic_input,
            output_path=audit_structural_path,
            audit_type="structural",
            n=structural_n,
            seed=seed,
            stratify_fields=list(audit_cfg.get("structural_stratify", ["difficulty_level"])),
        )
        if source_data.exists():
            export_audit_samples.export_source_audit_csv(
                source_csv_path=source_data,
                output_path=audit_source_path,
                n=source_n,
                seed=seed,
            )

    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline post-run analysis suite for Step2 experiment outputs.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = run_suite(config_path=Path(args.config), dry_run=bool(args.dry_run))
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
