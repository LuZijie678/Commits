"""Recover per-setting metrics from the checked-in staged-curriculum report.

These files are reconstructions, not verified copies of the missing runtime
artifacts. Never write them to the original output paths.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reports" / "mica_stage1_staged_curriculum_result.json"
OUTPUT = ROOT / "recovered_artifacts" / "stage1_staged_curriculum_20260615T023159Z"
EXPECTED_SOURCE_SHA256 = "9774f41e92fb1e9e9cabff9509bc8f09daa35e31bf0bb32a8052a77e8b24983e"
EXPECTED_NAMES = (
    "T0_k2_only_reference",
    "T1_long_k2_specialization_then_gentle_k1_reintroduction",
    "T2_k2_specialization_with_replay_protected_mixed_training",
    "T3_align_preserving_mixed_training",
    "T4_freeze_slot_queries_after_k2_specialization",
    "T5_disable_deterministic_coupling_during_reintroduction",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_verified(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Refusing to overwrite different content: {path}")
        return
    path.write_bytes(data)


def main() -> None:
    source_bytes = SOURCE.read_bytes()
    source_hash = _sha256(source_bytes)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise ValueError(f"Source report hash changed: {source_hash}")

    payload = json.loads(source_bytes)
    settings = payload.get("settings")
    if not isinstance(settings, list) or [row.get("setting_name") for row in settings] != list(EXPECTED_NAMES):
        raise ValueError("Source report settings do not match the documented six runs")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    files = []
    for index, row in enumerate(settings):
        name = EXPECTED_NAMES[index]
        filename = f"{name}_metrics.reconstructed.json"
        data = _json_bytes(row)
        _write_verified(OUTPUT / filename, data)
        files.append(
            {
                "setting_name": name,
                "reconstructed_path": str((OUTPUT / filename).relative_to(ROOT)).replace("\\", "/"),
                "source_json_pointer": f"/settings/{index}",
                "byte_count": len(data),
                "sha256": _sha256(data),
            }
        )

    manifest = {
        "status": "reconstructed_from_checked_in_report",
        "original_runtime_files_found": False,
        "original_sha256_verified": False,
        "source_report_path": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "source_report_sha256": source_hash,
        "method": "Serialize each settings[i] object using the runner's json.dumps(ensure_ascii=False, indent=2) plus LF.",
        "caveat": "Content follows the report, but no original per-setting file exists for byte-for-byte comparison.",
        "files": files,
    }
    _write_verified(OUTPUT / "RECOVERY_MANIFEST.json", _json_bytes(manifest))
    print(f"Recovered {len(files)} report-derived metrics files into {OUTPUT}")


if __name__ == "__main__":
    main()
