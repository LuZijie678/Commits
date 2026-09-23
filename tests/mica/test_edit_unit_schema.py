from __future__ import annotations

from code.mica.data.edit_unit import parse_unified_diff_to_edit_units


def test_parse_unified_diff_to_edit_units_extracts_hunks_and_features() -> None:
    diff_text = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,3 @@
 def run():
+    validate()
     return 1
diff --git a/tests/test_app.py b/tests/test_app.py
index 3333333..4444444 100644
--- a/tests/test_app.py
+++ b/tests/test_app.py
@@ -4,0 +5,3 @@
+def test_run():
+    assert run() == 1
+"""

    units = parse_unified_diff_to_edit_units(
        diff_text,
        repo="example/project",
        sample_id="synthetic_001",
        gold_intent_ids=[0, 1],
    )

    assert [unit.unit_id for unit in units] == ["synthetic_001::u0000", "synthetic_001::u0001"]
    assert [unit.gold_intent_id for unit in units] == [0, 1]
    assert units[0].file_path == "src/app.py"
    assert units[0].hunk_id == "src/app.py::hunk_0000"
    assert units[0].language == "python"
    assert "validate" in units[0].identifiers
    assert units[0].file_role == "source"
    assert units[0].added_lines == ["    validate()"]
    assert units[0].deleted_lines == []
    assert units[0].context_lines == ["def run():", "    return 1"]
    assert units[1].file_role == "test"
    assert units[1].added_lines[0].startswith("def test_run")
