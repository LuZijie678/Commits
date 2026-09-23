from __future__ import annotations

from dataclasses import dataclass, field
from statistics import pstdev
from typing import Any


@dataclass(slots=True)
class MetricCell:
    value: float | int | str | None
    std: float | None = None
    n: int | None = None
    higher_is_better: bool = True
    is_primary_metric: bool = False
    is_proxy_metric: bool = False
    requires_human_eval: bool = False
    advisor_pending: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "std": self.std,
            "n": self.n,
            "higher_is_better": self.higher_is_better,
            "is_primary_metric": self.is_primary_metric,
            "is_proxy_metric": self.is_proxy_metric,
            "requires_human_eval": self.requires_human_eval,
            "advisor_pending": self.advisor_pending,
            "notes": self.notes,
        }


@dataclass(slots=True)
class PaperTableRow:
    row_name: str
    comparison_group: str
    metrics: dict[str, MetricCell] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "measured"

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "row_name": self.row_name,
            "comparison_group": self.comparison_group,
            "metrics": {key: cell.to_dict() for key, cell in self.metrics.items()},
            "metadata": dict(self.metadata),
            "status": self.status,
        }
        payload.update(self.metadata)
        return payload


@dataclass(slots=True)
class ComparisonGroup:
    name: str
    rows: list[PaperTableRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "rows": [row.to_dict() for row in self.rows]}


@dataclass(slots=True)
class PaperTable:
    table_name: str
    rows: list[PaperTableRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_name": self.table_name,
            "rows": [row.to_dict() for row in self.rows],
            "notes": list(self.notes),
        }


def aggregate_metric_cells(
    rows: list[dict[str, Any]],
    metric_specs: dict[str, dict[str, Any]],
) -> dict[str, MetricCell]:
    cells: dict[str, MetricCell] = {}
    for metric_name, spec in metric_specs.items():
        values = [float(row[metric_name]) for row in rows if row.get(metric_name) is not None]
        if values:
            value = round(sum(values) / len(values), 6)
            std = round(pstdev(values), 6) if len(values) > 1 else 0.0
            n = len(values)
        else:
            value = None
            std = None
            n = 0
        cells[metric_name] = MetricCell(
            value=value,
            std=std,
            n=n,
            higher_is_better=bool(spec.get("higher_is_better", True)),
            is_primary_metric=bool(spec.get("is_primary_metric", False)),
            is_proxy_metric=bool(spec.get("is_proxy_metric", False)),
            requires_human_eval=bool(spec.get("requires_human_eval", False)),
            advisor_pending=bool(spec.get("advisor_pending", False)),
            notes=str(spec.get("notes", "")),
        )
    return cells
