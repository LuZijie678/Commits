from __future__ import annotations

from pathlib import Path
from typing import Any


REQUIRED_DATA_CARD_SNIPPETS = (
    "Step1 high-confidence k=1",
    "Step2 strict synthetic k1/k2",
    "Step2 Step3-ready synthetic",
    "hard_b train/dev/test",
    "M weak train/dev/final-test",
    "M-align-calib",
    "RealDomainSplit split:",
    "RealDomainSelective split:",
    "RealDomainSelective labels:",
    "RealDomainBinary is deprecated and must not be used in final tables",
    "renderer data, optional",
    "high",
    "medium-high",
    "medium",
    "medium-low",
    "eval-only",
    "M-final-test = eval-only",
    "hard_b-test = eval-only",
    "RealDomainSplit-test = eval-only",
    "RealDomainSelective-test = eval-only",
    "M weak = censored k>=2 only",
    "M-align-calib = small real alignment calibration/eval only",
    "intent_subjects/messages = renderer only, not attribution matching",
    "Kmax is a task-scope constant, not a tuned model hyperparameter",
    "Kmax coverage statistics must be recorded before training",
    "k > Kmax commits are treated as complex/overflow cases",
    "overflow/abstention is required for out-of-scope decomposition",
    "Kmax selection protocol uses train/dev annotation assets only",
    "coverage@Kmax must be reported on every evaluation split",
    "never tune Kmax according to final-test attribution or message utility scores",
    "synthetic cardinality distribution alone cannot justify Kmax",
    "Kmax=4 is acceptable only if DATA_CARD shows target-domain coverage",
    "Kmax freeze protocol",
    "status: protocol_defined_but_value_not_populated",
    "status: protocol_defined_but_stats_not_populated",
    "paper_readiness: not ready until train/dev coverage stats are populated and frozen",
    "current_workspace_state: implementation_default_not_final_paper_task_boundary",
    "atomic-source leakage is prohibited",
    "synthetic variants from the same atomic source cannot cross train/dev/test",
    "no commits from the same PR/tangled construction group may cross splits",
    "commit messages / PR titles / issue texts / gold intent ids / synthetic construction metadata are forbidden as attribution inputs",
    "real_alignment_benchmark",
    "heldout_policy: to_be_frozen_before_final_evaluation",
    "pseudo_alignment_allowed_as_gold: false",
    "synthetic_labels_allowed_as_real_gold: false",
)


def read_data_card(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def validate_data_card_text(text: str) -> dict[str, Any]:
    missing = [snippet for snippet in REQUIRED_DATA_CARD_SNIPPETS if snippet not in text]
    return {
        "valid": not missing,
        "missing_requirements": missing,
        "requirement_count": len(REQUIRED_DATA_CARD_SNIPPETS),
    }
