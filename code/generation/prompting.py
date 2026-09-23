from __future__ import annotations

from pathlib import Path
from typing import Any

from common import repo_path, safe_text


STRATEGY_TO_TEMPLATE = {
    "G0": "g0_diff_only_zero_shot.txt",
    "G1": "g1_context_zero_shot.txt",
    "G2": "g2_random_fewshot_icl.txt",
    "G3": "g3_type_matched_fewshot_icl.txt",
    "G4": "g4_retrieval_icl.txt",
    "G5": "g5_oracle_structure_guided_icl.txt",
}


def load_template(strategy: str, prompt_dir: str | Path = "code/generation/prompts") -> str:
    if strategy not in STRATEGY_TO_TEMPLATE:
        raise KeyError(f"unknown generation strategy: {strategy}")
    return repo_path(prompt_dir) .joinpath(STRATEGY_TO_TEMPLATE[strategy]).read_text(encoding="utf-8")


def exemplar_block(exemplars: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, ex in enumerate(exemplars, 1):
        blocks.append(
            "\n".join(
                [
                    f"Example {index}:",
                    f"Diff excerpt:\n{safe_text(ex.get('diff_summary'))}",
                    f"Subject: {safe_text(ex.get('subject'))}",
                ]
            )
        )
    return "\n\n".join(blocks)


def oracle_structure_block(sample: dict[str, Any]) -> str:
    if safe_text(sample.get("data_category")) != "synthetic_multi":
        return "Oracle structure: not available for this sample."
    return "\n".join(
        [
            f"Oracle intent count: {sample.get('intent_count')}",
            "Oracle intent subjects:",
            "\n".join(f"- {item}" for item in (sample.get("intent_subjects") or [])) or "- not provided",
            f"Oracle edit-to-intent summary: {sample.get('edit_to_intent') or {}}",
            "Supporting edits: tests/config/docs may support an intent and should not be forced into separate goals.",
        ]
    )


def render_prompt(strategy: str, sample: dict[str, Any], exemplars: list[dict[str, Any]] | None = None) -> str:
    if strategy == "G5" and safe_text(sample.get("data_category")) != "synthetic_multi":
        raise ValueError("G5 oracle_structure_guided_icl is only enabled for synthetic_multi samples")
    template = load_template(strategy)
    exemplars = exemplars or []
    values = {
        "repo": safe_text(sample.get("repo")),
        "diff_text": safe_text(sample.get("diff_text")),
        "file_paths": "\n".join(_file_paths(sample)),
        "reference_subject": safe_text(sample.get("subject_reference")),
        "exemplars": exemplar_block(exemplars),
        "oracle_structure": oracle_structure_block(sample),
    }
    return template.format(**values)


def _file_paths(sample: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for line in safe_text(sample.get("diff_text")).splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                paths.append(parts[2][2:] if parts[2].startswith("a/") else parts[2])
    return paths[:50]

