from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from code.mica.io_utils import _coerce_path, read_json, read_jsonl


RUNNER_ERROR_SCHEMA_VERSION = "mica-consumer-runner-error-v1"
RUNNER_ERROR_TYPES = {
    "adapter_error",
    "consumer_rejected",
    "internal_error",
    "invalid_input",
    "io_error",
    "output_exists",
    "schema_validation_error",
    "verifier_rejected",
}


def build_runner_error(
    *,
    error_type: str,
    message: str,
    line_number: int | None = None,
    sample_id: str | None = None,
    record_index: int | None = None,
) -> dict[str, Any]:
    if error_type not in RUNNER_ERROR_TYPES:
        raise ValueError(f"unsupported runner error_type {error_type!r}")
    return {
        "schema_version": RUNNER_ERROR_SCHEMA_VERSION,
        "error_type": error_type,
        "message": str(message),
        "line_number": line_number,
        "sample_id": sample_id,
        "record_index": record_index,
    }


def read_jsonl_records_with_errors(
    path: str | Path,
    *,
    strict: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    target = _coerce_path(path)
    if not target.exists():
        raise FileNotFoundError(f"File not found: {target}")
    if target.is_dir():
        raise ValueError(f"Expected file path but got directory: {target}")
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for line_number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            if strict:
                raise ValueError(f"Invalid JSONL at {target}:{line_number}: {exc}") from exc
            errors.append(
                build_runner_error(
                    error_type="invalid_input",
                    message=f"Invalid JSONL at {target}:{line_number}: {exc}",
                    line_number=line_number,
                )
            )
            continue
        if not isinstance(payload, dict):
            if strict:
                raise ValueError(f"Expected JSON object row at {target}:{line_number}")
            errors.append(
                build_runner_error(
                    error_type="invalid_input",
                    message=f"Expected JSON object row at {target}:{line_number}",
                    line_number=line_number,
                )
            )
            continue
        payload["__line_number__"] = line_number
        rows.append(payload)
    return rows, errors


def ensure_writable_output(path: str | Path, *, overwrite: bool) -> Path:
    target = _coerce_path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def atomic_write_json(path: str | Path, payload: Any, *, overwrite: bool = False) -> None:
    target = ensure_writable_output(path, overwrite=overwrite)
    _atomic_write_text(target, _json_dumps(payload, pretty=True))


def atomic_write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]], *, overwrite: bool = False) -> None:
    target = ensure_writable_output(path, overwrite=overwrite)
    text = "".join(_json_dumps(row, pretty=False) + "\n" for row in rows)
    _atomic_write_text(target, text)


def load_sample_indexed_rows(path: str | Path) -> dict[str, dict[str, Any]]:
    source = str(path)
    if source.endswith(".jsonl"):
        rows = read_jsonl(path)
    else:
        payload = read_json(path)
        if isinstance(payload, dict) and "samples" in payload:
            rows = payload["samples"]
        elif isinstance(payload, dict) and "rows" in payload:
            rows = payload["rows"]
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = []
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sample_id = row.get("sample_id")
        if sample_id is None:
            continue
        index[str(sample_id)] = row
    return index


def _atomic_write_text(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temp_name = handle.name
    os.replace(temp_name, path)


def _json_dumps(payload: Any, *, pretty: bool) -> str:
    if pretty:
        return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    return json.dumps(payload, ensure_ascii=False, allow_nan=False)
