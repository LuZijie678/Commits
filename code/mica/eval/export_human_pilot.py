from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from code.mica.eval.consumer_records import HumanPilotBlindMappingRecord, HumanPilotCandidateRecord
from code.mica.runners.consumer_runner_utils import atomic_write_jsonl, ensure_writable_output


def export_human_pilot_package(
    *,
    system_runs: list[dict[str, Any]],
    evidence_display_records: list[dict[str, Any]],
    annotator_output_jsonl: str | Path,
    mapping_output_jsonl: str | Path,
    seed: int,
    overwrite: bool = False,
) -> dict[str, Any]:
    ensure_writable_output(annotator_output_jsonl, overwrite=overwrite)
    ensure_writable_output(mapping_output_jsonl, overwrite=overwrite)
    evidence_index = {str(row.get("sample_id")): dict(row.get("evidence_display", {})) for row in evidence_display_records}
    grouped_candidates: dict[str, list[dict[str, Any]]] = {}
    for run in system_runs:
        system_name = str(run.get("system_name", "")).strip()
        plan_source = str(run.get("plan_source", "")).strip()
        for record in run.get("records", []) or []:
            sample_id = str(record.get("sample_id", ""))
            grouped_candidates.setdefault(sample_id, []).append(
                {
                    "system_name": system_name,
                    "plan_source": plan_source,
                    "record": dict(record),
                }
            )

    annotator_rows: list[dict[str, Any]] = []
    mapping_rows: list[dict[str, Any]] = []
    for sample_id in sorted(grouped_candidates):
        candidates = sorted(
            grouped_candidates[sample_id],
            key=lambda item: _blind_sort_key(seed=seed, sample_id=sample_id, system_name=item["system_name"]),
        )
        for index, candidate in enumerate(candidates, 1):
            record = candidate["record"]
            message = dict(record.get("message", {}))
            candidate_id = f"candidate_{index}"
            annotator_rows.append(
                HumanPilotCandidateRecord(
                    sample_id=sample_id,
                    evidence_display=evidence_index.get(sample_id, {}),
                    candidate_id=candidate_id,
                    subject=str(message.get("subject", "")),
                    body=[str(item) for item in message.get("body", [])],
                ).to_dict()
            )
            mapping_rows.append(
                HumanPilotBlindMappingRecord(
                    sample_id=sample_id,
                    candidate_id=candidate_id,
                    original_system_name=candidate["system_name"],
                    plan_source=candidate["plan_source"],
                    original_record_id=str(record.get("commit_id") or record.get("sample_id") or sample_id),
                ).to_dict()
            )

    atomic_write_jsonl(annotator_output_jsonl, annotator_rows, overwrite=overwrite)
    atomic_write_jsonl(mapping_output_jsonl, mapping_rows, overwrite=overwrite)
    return {
        "schema_version": "mica-human-pilot-export-v1",
        "seed": seed,
        "sample_count": len(grouped_candidates),
        "candidate_count": len(annotator_rows),
    }


def _blind_sort_key(*, seed: int, sample_id: str, system_name: str) -> str:
    payload = f"{seed}:{sample_id}:{system_name}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
