from __future__ import annotations

from pathlib import Path
from typing import Any

from code.mica.io_utils import write_json
from code.mica.paper_tables.ablation_table import build_ablation_paper_table
from code.mica.paper_tables.alignment_table import build_alignment_paper_table
from code.mica.paper_tables.message_utility_table import build_message_utility_paper_table
from code.mica.paper_tables.real_domain_table import build_real_domain_paper_table
from code.mica.paper_tables.real_domain_table import build_real_domain_selective_paper_table
from code.mica.paper_tables.real_domain_table import build_real_domain_split_paper_table
from code.mica.paper_tables.shortcut_ood_table import build_shortcut_ood_paper_table


def write_json_report(path: str | Path, payload: dict[str, Any]) -> None:
    write_json(path, payload)


def write_markdown_report(path: str | Path, title: str, sections: dict[str, Any]) -> None:
    lines = [f"# {title}", ""]
    for section_name, payload in sections.items():
        lines.append(f"## {section_name}")
        if isinstance(payload, dict):
            lines.append(format_key_value_section(payload).rstrip())
        else:
            lines.append(str(payload))
        lines.append("")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def format_diagnostic_table(diagnostics: dict[str, Any]) -> str:
    lines = ["| code | count |", "| --- | ---: |"]
    for code, count in diagnostics.items():
        lines.append(f"| {code} | {count} |")
    return "\n".join(lines) + "\n"


def format_key_value_section(mapping: dict[str, Any]) -> str:
    return "".join(f"- `{key}`: {value}\n" for key, value in mapping.items())


def build_real_domain_main_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return build_real_domain_paper_table(rows)


def build_real_domain_split_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return build_real_domain_split_paper_table(rows)


def build_real_domain_selective_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return build_real_domain_selective_paper_table(rows)


def build_alignment_main_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return build_alignment_paper_table(rows)


def build_message_utility_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return build_message_utility_paper_table(rows)


def build_ablation_main_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return build_ablation_paper_table(rows)


def build_shortcut_ood_main_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return build_shortcut_ood_paper_table(rows)


def build_stage2_tradeoff_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "table_name": "stage2_tradeoff",
        "rows": rows,
        "required_columns": [
            "hard_b_fpr",
            "hard_b_top1_retained_foreground_mass",
            "hard_b_residual_foreground_mass",
            "hard_b_background_swallowing_rate",
            "m_recall",
            "strict_replay_forgetting",
            "active_slot_count_distribution",
        ],
        "status": "protocol_defined",
        "values_status": "values_to_be_populated_by_dev_calibration_script",
        "paper_readiness": "not_final_paper_ready_until_populated",
    }


def build_stage2_calibration_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "table_name": "stage2_calibration",
        "rows": rows,
        "required_columns": ["mean_abs_gap", "count_ece", "p_count_pb_gap", "active_slot_count_distribution"],
        "status": "protocol_defined",
        "values_status": "values_to_be_populated_by_dev_calibration_script",
        "paper_readiness": "not_final_paper_ready_until_populated",
    }


def build_stage3_alignment_calibration_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "table_name": "stage3_alignment_calibration",
        "rows": rows,
        "required_columns": ["pairwise_f1", "ari", "nmi", "bcubed_f1", "hunk_micro_f1", "hard_b_fpr_rebound", "m_recall_drop"],
        "status": "protocol_defined",
        "values_status": "values_to_be_populated_by_real_alignment_eval",
        "paper_readiness": "not_final_paper_ready_until_populated",
    }
