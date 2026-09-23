from __future__ import annotations

from pathlib import Path
from typing import Any


REQUIRED_EVAL_PROTOCOL_SNIPPETS = (
    "Stage 1 synthetic attribution validation",
    "Stage 2 hard_b / M calibration",
    "Stage 3 real alignment calibration/eval",
    "Stage 4 deterministic evidence-locked rendering",
    "RealDomainSplit / hard_b main table",
    "alignment benchmark table",
    "message utility table",
    "anti-shortcut / OOD stress",
    "baseline table",
    "RealDomainSplit table",
    "RealDomainSelective table",
    "Abstention thresholds:",
    "selection_split: dev only",
    "default_rule: fixed target coverage or full coverage-risk curve",
    "final_test_tuning: forbidden",
    "values_to_be_populated_by_dev_calibration_script",
    "real alignment benchmark held-out policy:",
    "status: protocol_requires_freeze_before_final_evaluation",
    "cross_repository_heldout_primary",
    "time_based_heldout_secondary",
    "unspecified repo overlap",
    "final-test never used for training/tuning",
    "Kmax coverage reporting is mandatory on every evaluation split",
    "oracle-k vs predicted-k must be reported",
    "generation is downstream utility, not main contribution",
    "overflow / abstention rate must be reported",
    "clustering is a baseline, not the primary formulation",
    "renderer scores cannot select attribution checkpoints",
    "background/null must be audited separately from semantic uncertainty",
    "oracle-k / predicted-k / overflow must be jointly reported where applicable",
    "Stage 2 uses hard_b and M weak labels only for split/no-split/abstain boundary calibration",
    "Stage 3 real alignment calibration is parameter-light and separate from Stage 2 count calibration",
    "renderer metrics cannot select attribution checkpoints, thresholds, templates, prompts, or verifier settings",
    "alignment benchmark construction must be documented",
    "coverage-risk curve must be reported for abstaining models",
    "selective attribution metrics must be reported at fixed coverage levels",
    "abstention precision and false-abstain rate must be reported",
    "forced-decomposition error on out-of-scope commits must be reported",
    "RealDomainSplit = k=1 vs k>=2 split / no-split boundary evaluation",
    "RealDomainSelective = in-scope decomposable vs overflow / abstain evaluation",
    "FPR_hard_b = percentage of hard_b single-intent commits predicted as multi-intent",
    "pseudo alignment cannot be used as final real-alignment gold",
    "synthetic construction labels cannot be mixed into the real alignment benchmark",
    "these diagnostics are validity checks, not method-selection ablations",
    "Primary setting:",
    "cross-repository held-out evaluation",
    "no repository overlap between train/dev calibration assets and final real alignment test",
    "Secondary setting, if cross-repository sample size is insufficient:",
    "time-based held-out evaluation within repository",
    "repo overlap decision cannot remain pending in the final protocol",
    "Background slot audit metrics",
    "background assignment rate",
    "foreground evidence swallowed by background",
    "foreground-to-background error",
    "missing-intent rate by file role",
    "background precision on rule-verified background units",
    "background recall on rule-verified background units",
    "semantic uncertainty must not be counted as correct background assignment",
)


def read_eval_protocol(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def validate_eval_protocol_text(text: str) -> dict[str, Any]:
    missing = [snippet for snippet in REQUIRED_EVAL_PROTOCOL_SNIPPETS if snippet not in text]
    return {
        "valid": not missing,
        "missing_requirements": missing,
        "requirement_count": len(REQUIRED_EVAL_PROTOCOL_SNIPPETS),
    }
