from __future__ import annotations

from code.mica.reporting import (
    format_diagnostic_table,
    format_key_value_section,
    write_json_report,
    write_markdown_report,
)


def test_json_report_writer_writes_to_explicit_path(tmp_path) -> None:
    path = tmp_path / "report.json"
    write_json_report(path, {"status": "candidate", "advisor_pending": True})

    assert path.exists()
    assert "candidate" in path.read_text(encoding="utf-8")


def test_markdown_report_writer_supports_candidate_and_pending_sections(tmp_path) -> None:
    path = tmp_path / "report.md"
    write_markdown_report(
        path,
        "Test Report",
        {
            "Scope": {"status": "candidate", "advisor_pending": True},
            "Counts": {"rows": 3},
        },
    )

    text = path.read_text(encoding="utf-8")
    assert "# Test Report" in text
    assert "advisor_pending" in text
    assert "rows" in text


def test_diagnostic_table_and_key_value_section_are_formatted() -> None:
    table = format_diagnostic_table({"missing_sample_id": 2, "missing_edit_units": 1})
    section = format_key_value_section({"status": "candidate", "rows": 4})

    assert "| code | count |" in table
    assert "missing_sample_id" in table
    assert "- `status`: candidate" in section

