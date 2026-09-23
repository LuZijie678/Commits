from __future__ import annotations

from typing import Any

from code.mica.paper_tables.table_schema import PaperTable, PaperTableRow, MetricCell


def build_ablation_paper_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    table = PaperTable(table_name="ablation_main", notes=["pending_experiment rows are structural placeholders, not results"])
    for row in rows:
        status = str(row.get("status", "measured"))
        metrics = {}
        if status != "pending_experiment":
            for key, value in row.items():
                if key in {"variant_name", "status"}:
                    continue
                if isinstance(value, (int, float)):
                    metrics[key] = MetricCell(value=value, higher_is_better=not key.endswith("rate")).to_dict()
        table.rows.append(
            PaperTableRow(
                row_name=str(row.get("variant_name", "unknown")),
                comparison_group="ablation",
                metrics={key: MetricCell(**payload) for key, payload in metrics.items()},
                metadata={"variant_name": str(row.get("variant_name", "unknown"))},
                status=status,
            )
        )
    return table.to_dict()
