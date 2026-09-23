from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]


def _coerce_path(path: str | Path) -> Path:
    target = Path(path)
    if target.is_absolute():
        return target
    return REPO_ROOT / target


def _validate_readable_file(path: str | Path) -> Path:
    target = _coerce_path(path)
    if target.is_dir():
        raise ValueError(f"Expected file path but got directory: {target}")
    if not target.exists():
        raise FileNotFoundError(f"File not found: {target}")
    return target


def read_json(path: str | Path) -> Any:
    target = _validate_readable_file(path)
    return json.loads(target.read_text(encoding="utf-8"))


def write_json(path: str | Path, obj: Any) -> None:
    target = _coerce_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    target = _validate_readable_file(path)
    rows: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {target}:{line_number}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"Expected JSON object row at {target}:{line_number}")
            rows.append(payload)
    return rows


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    target = _coerce_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def ensure_output_dir(path: str | Path) -> Path:
    target = _coerce_path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def safe_relpath_for_report(path: str | Path) -> str:
    target = _coerce_path(path).resolve()
    try:
        return target.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return target.as_posix()
