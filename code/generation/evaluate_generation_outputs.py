from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from common import read_jsonl, repo_path, safe_text, tokenize, write_json


ARTIFACT_MARKERS = ["change 1", "intent 1", "\n-", "\n*", "; ;"]


def evaluate_outputs(output_root: Path, *, run_kind: str = "mock") -> dict[str, Any]:
    samples = {row["sample_id"]: row for row in read_jsonl(output_root / "dataset" / "pilot_all.jsonl")}
    generations = read_jsonl(output_root / "generations" / run_kind / "generation_outputs.jsonl")
    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in generations:
        by_strategy[safe_text(row.get("strategy"))].append(row)
    metrics = {strategy: _evaluate_strategy(rows, samples) for strategy, rows in sorted(by_strategy.items())}
    report = {
        "schema_version": "llm_generation_pilot_evaluation_v1",
        "run_kind": run_kind,
        "strategy_metrics": metrics,
        "notes": {
            "text_metrics": "BLEU/ROUGE-L/METEOR/BERTScore are not implemented in the mock-only standard-library evaluator and are marked not_applicable.",
            "m_proxy": "M_real_multi metrics are proxy-only because hunk-level gold structure is unavailable.",
        },
    }
    write_json(output_root / "evaluation" / f"{run_kind}_evaluation.json", report)
    return report


def _evaluate_strategy(rows: list[dict[str, Any]], samples: dict[str, dict[str, Any]]) -> dict[str, Any]:
    generated = [row for row in rows if row.get("status") == "generated"]
    outputs = [safe_text(row.get("generated_subject")) for row in generated]
    non_empty = [text for text in outputs if text]
    single_line = [text for text in outputs if "\n" not in text]
    duplicate_count = sum(count - 1 for count in Counter(outputs).values() if count > 1)
    format_metrics = {
        "count": len(rows),
        "generated_count": len(generated),
        "non_empty_rate": len(non_empty) / len(rows) if rows else 0.0,
        "single_line_rate": len(single_line) / len(rows) if rows else 0.0,
        "subject_length_chars_mean": sum(len(text) for text in outputs) / len(outputs) if outputs else 0.0,
        "subject_length_tokens_mean": sum(len(tokenize(text)) for text in outputs) / len(outputs) if outputs else 0.0,
        "length_violation_rate": sum(1 for text in outputs if len(text) > 120) / len(outputs) if outputs else 0.0,
        "artifact_rate": sum(1 for text in outputs if any(marker in text.lower() for marker in ARTIFACT_MARKERS)) / len(outputs) if outputs else 0.0,
        "duplicate_output_rate": duplicate_count / len(outputs) if outputs else 0.0,
    }
    traditional = {name: "not_applicable" for name in ["BLEU", "ROUGE-L", "METEOR", "BERTScore"]}
    structural = {
        "synthetic_multi": _synthetic_metrics(generated, samples),
        "hard_b": _hard_b_metrics(generated, samples),
        "M_real_multi": _m_metrics(generated, samples),
    }
    return {"format": format_metrics, "traditional_text": traditional, "structured": structural}


def _synthetic_metrics(rows: list[dict[str, Any]], samples: dict[str, dict[str, Any]]) -> dict[str, Any]:
    eligible = [(row, samples.get(row["sample_id"], {})) for row in rows if samples.get(row["sample_id"], {}).get("data_category") == "synthetic_multi"]
    if not eligible:
        return {"status": "not_applicable"}
    coverages: list[float] = []
    for row, sample in eligible:
        output = safe_text(row.get("generated_subject")).lower()
        intents = [safe_text(item).lower() for item in sample.get("intent_subjects") or [] if safe_text(item)]
        if not intents:
            continue
        covered = sum(1 for intent in intents if any(tok in output for tok in tokenize(intent)[:4]))
        coverages.append(covered / len(intents))
    avg = sum(coverages) / len(coverages) if coverages else 0.0
    return {"intent_coverage": avg, "intent_omission_rate": 1.0 - avg, "unsupported_intent_rate": "not_applicable_without_judge"}


def _hard_b_metrics(rows: list[dict[str, Any]], samples: dict[str, dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in rows if samples.get(row["sample_id"], {}).get("data_category") == "hard_b"]
    if not eligible:
        return {"status": "not_applicable"}
    multi_markers = [" and also ", ";", " as well as ", "intent", "change 1"]
    false_multi = sum(1 for row in eligible if any(marker in safe_text(row.get("generated_subject")).lower() for marker in multi_markers))
    return {
        "supporting_edit_oversegmentation_rate": false_multi / len(eligible),
        "false_multi_expression_rate": false_multi / len(eligible),
        "metric_type": "proxy",
    }


def _m_metrics(rows: list[dict[str, Any]], samples: dict[str, dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in rows if samples.get(row["sample_id"], {}).get("data_category") == "M_real_multi"]
    if not eligible:
        return {"status": "not_applicable"}
    multiish = sum(1 for row in eligible if " and " in safe_text(row.get("generated_subject")).lower())
    return {
        "multi_intent_coverage_proxy": multiish / len(eligible),
        "missing_major_intent_proxy": 1.0 - (multiish / len(eligible)),
        "metric_type": "proxy_not_gold",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-kind", default="mock")
    args = parser.parse_args()
    report = evaluate_outputs(repo_path(args.output_root), run_kind=args.run_kind)
    print(f"evaluated {len(report['strategy_metrics'])} strategies")


if __name__ == "__main__":
    main()

