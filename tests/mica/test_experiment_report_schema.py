from __future__ import annotations

from code.mica.experiment.report_schema import build_experiment_report_schema


def test_build_experiment_report_schema_marks_dirty_worktree_warning() -> None:
    report = build_experiment_report_schema(
        stage="stage1",
        metrics={"pairwise_f1": 0.8},
        provenance={"git": {"dirty": True}},
    )

    assert report["warnings"] == ["dirty_worktree_not_fully_reproducible"]
