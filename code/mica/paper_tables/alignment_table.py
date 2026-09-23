from __future__ import annotations

from collections import defaultdict
from typing import Any

from code.mica.paper_tables.table_schema import PaperTable, PaperTableRow, aggregate_metric_cells


ALIGNMENT_METRICS = {
    "count_exact": {"higher_is_better": True, "is_primary_metric": True},
    "count_mae": {"higher_is_better": False},
    "pairwise_f1": {"higher_is_better": True, "is_primary_metric": True},
    "ari": {"higher_is_better": True},
    "nmi": {"higher_is_better": True},
    "bcubed_f1": {"higher_is_better": True},
    "hunk_micro_f1": {"higher_is_better": True},
    "over_segmentation_rate": {"higher_is_better": False},
    "under_segmentation_rate": {"higher_is_better": False},
}


def build_alignment_paper_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("model_name", "unknown")), str(row.get("alignment_mode", "predicted_k")))].append(row)
    table = PaperTable(table_name="alignment_main", notes=["oracle-k and predicted-k must be reported separately"])
    for (model_name, alignment_mode), group_rows in sorted(grouped.items()):
        metrics = aggregate_metric_cells(group_rows, ALIGNMENT_METRICS)
        table.rows.append(
            PaperTableRow(
                row_name=model_name,
                comparison_group=alignment_mode,
                metrics=metrics,
                metadata={"model_name": model_name, "alignment_mode": alignment_mode},
            )
        )
    return table.to_dict()
