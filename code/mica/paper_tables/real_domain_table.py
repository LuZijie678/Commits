from __future__ import annotations

from collections import defaultdict
from typing import Any

from code.mica.paper_tables.table_schema import PaperTable, PaperTableRow, aggregate_metric_cells


REAL_DOMAIN_METRICS = {
    "auroc": {"higher_is_better": True, "is_primary_metric": True},
    "auprc": {"higher_is_better": True, "is_primary_metric": True},
    "balanced_accuracy": {"higher_is_better": True},
    "hard_b_fpr": {"higher_is_better": False},
    "m_recall": {"higher_is_better": True},
    "ece": {"higher_is_better": False},
}

REAL_DOMAIN_SPLIT_METRICS = {
    "auroc": {"higher_is_better": True, "is_primary_metric": True},
    "auprc": {"higher_is_better": True, "is_primary_metric": True},
    "balanced_accuracy": {"higher_is_better": True},
    "ece": {"higher_is_better": False},
    "hard_b_fpr": {"higher_is_better": False},
}

REAL_DOMAIN_SELECTIVE_METRICS = {
    "coverage": {"higher_is_better": True, "is_primary_metric": True},
    "risk_at_coverage": {"higher_is_better": False, "is_primary_metric": True},
    "aurc": {"higher_is_better": False, "is_primary_metric": True},
    "abstention_precision": {"higher_is_better": True},
    "false_abstention_on_in_scope": {"higher_is_better": False},
    "missed_overflow_rate": {"higher_is_better": False},
    "forced_decomposition_error": {"higher_is_better": False},
}


def build_real_domain_paper_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return _build_real_domain_table(
        rows,
        table_name="real_domain_main",
        metric_specs=REAL_DOMAIN_METRICS,
        notes=["final-test must remain eval-only"],
    )


def build_real_domain_split_paper_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return _build_real_domain_table(
        rows,
        table_name="real_domain_split",
        metric_specs=REAL_DOMAIN_SPLIT_METRICS,
        notes=["RealDomainSplit evaluates k=1 vs k at least 2; final-test remains eval-only"],
    )


def build_real_domain_selective_paper_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return _build_real_domain_table(
        rows,
        table_name="real_domain_selective",
        metric_specs=REAL_DOMAIN_SELECTIVE_METRICS,
        notes=["RealDomainSelective evaluates release/abstain decisions; thresholds are dev-frozen only"],
    )


def _build_real_domain_table(
    rows: list[dict[str, Any]],
    *,
    table_name: str,
    metric_specs: dict[str, dict[str, Any]],
    notes: list[str],
) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("model_name", "unknown")), str(row.get("split", "unspecified")))].append(row)
    table = PaperTable(table_name=table_name, notes=notes)
    for (model_name, split), group_rows in sorted(grouped.items()):
        metrics = aggregate_metric_cells(group_rows, metric_specs)
        table.rows.append(
            PaperTableRow(
                row_name=model_name,
                comparison_group=split,
                metrics=metrics,
                metadata={"model_name": model_name, "split": split},
            )
        )
    return table.to_dict()
