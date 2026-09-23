from __future__ import annotations

from typing import Any

from code.mica.paper_tables.table_schema import MetricCell, PaperTable, PaperTableRow


def build_shortcut_ood_paper_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    table = PaperTable(table_name="shortcut_ood_main", notes=["slice-level metrics only; no tuning on final-test slices"])
    for row in rows:
        metrics = {
            key: MetricCell(value=value, higher_is_better=_higher_is_better(key)).to_dict()
            for key, value in row.items()
            if key != "slice" and isinstance(value, (int, float))
        }
        table.rows.append(
            PaperTableRow(
                row_name=str(row.get("slice", "unknown_slice")),
                comparison_group="shortcut_ood",
                metrics={key: MetricCell(**payload) for key, payload in metrics.items()},
                metadata={"slice": str(row.get("slice", "unknown_slice"))},
            )
        )
    return table.to_dict()


def _higher_is_better(metric_name: str) -> bool:
    lowered = metric_name.lower()
    if any(token in lowered for token in ("fpr", "mae", "missing", "extra", "hallucination")):
        return False
    return True
