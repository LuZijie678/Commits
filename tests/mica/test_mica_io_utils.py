from __future__ import annotations

import pytest

from code.mica.io_utils import ensure_output_dir, read_json, read_jsonl, safe_relpath_for_report, write_json, write_jsonl


def test_json_and_jsonl_roundtrip(tmp_path) -> None:
    json_path = tmp_path / "payload.json"
    jsonl_path = tmp_path / "rows.jsonl"

    write_json(json_path, {"sample_id": "s1", "value": 1})
    write_jsonl(jsonl_path, [{"sample_id": "s1"}, {"sample_id": "s2"}])

    assert read_json(json_path)["sample_id"] == "s1"
    assert [row["sample_id"] for row in read_jsonl(jsonl_path)] == ["s1", "s2"]


def test_jsonl_reader_does_not_split_on_unicode_nel_inside_string(tmp_path) -> None:
    jsonl_path = tmp_path / "unicode_nel.jsonl"
    write_jsonl(jsonl_path, [{"sample_id": "s1", "text": "line1\u0085line2"}])

    rows = read_jsonl(jsonl_path)

    assert rows == [{"sample_id": "s1", "text": "line1\u0085line2"}]


def test_empty_jsonl_is_readable(tmp_path) -> None:
    jsonl_path = tmp_path / "empty.jsonl"
    jsonl_path.write_text("", encoding="utf-8")
    assert read_jsonl(jsonl_path) == []


def test_missing_file_reports_clear_error(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError, match="missing.json"):
        read_json(missing)


def test_output_root_is_created_if_missing(tmp_path) -> None:
    output_root = tmp_path / "nested" / "outputs"
    ensure_output_dir(output_root)
    assert output_root.exists()
    assert output_root.is_dir()


def test_directory_input_is_rejected_for_json_and_jsonl(tmp_path) -> None:
    with pytest.raises(ValueError, match="Expected file path"):
        read_json(tmp_path)
    with pytest.raises(ValueError, match="Expected file path"):
        read_jsonl(tmp_path)


def test_safe_relpath_for_report_returns_string(tmp_path) -> None:
    path = tmp_path / "artifact.json"
    path.write_text("{}", encoding="utf-8")
    assert isinstance(safe_relpath_for_report(path), str)
