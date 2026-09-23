from __future__ import annotations

from collections import defaultdict
from typing import Any

from code.mica.paper_tables.table_schema import PaperTable, PaperTableRow, aggregate_metric_cells


MESSAGE_UTILITY_METRICS = {
    "intent_coverage": {"higher_is_better": True, "is_primary_metric": True, "is_proxy_metric": True},
    "missing_intent_rate": {"higher_is_better": False, "is_proxy_metric": True},
    "extra_intent_rate": {"higher_is_better": False, "is_proxy_metric": True},
    "hallucination_proxy": {"higher_is_better": False, "is_proxy_metric": True},
    "faithfulness_proxy": {"higher_is_better": True, "is_proxy_metric": True},
    "specificity_proxy": {"higher_is_better": True, "is_proxy_metric": True},
    "human_usefulness": {"higher_is_better": True, "requires_human_eval": True, "advisor_pending": True},
}


def build_message_utility_paper_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        normalized = dict(row)
        if "specificity_proxy" not in normalized and "specificity" in normalized:
            normalized["specificity_proxy"] = normalized["specificity"]
        grouped[(str(normalized.get("model_name", "unknown")), str(normalized.get("rendering_mode", "message_utility")))].append(normalized)
    table = PaperTable(table_name="message_utility_main", notes=["proxy_not_human_eval=true unless human labels are provided"])
    for (model_name, rendering_mode), group_rows in sorted(grouped.items()):
        metrics = aggregate_metric_cells(group_rows, MESSAGE_UTILITY_METRICS)
        table.rows.append(
            PaperTableRow(
                row_name=model_name,
                comparison_group=rendering_mode,
                metrics=metrics,
                metadata={"model_name": model_name, "rendering_mode": rendering_mode, "proxy_not_human_eval": True},
            )
        )
    return table.to_dict()
