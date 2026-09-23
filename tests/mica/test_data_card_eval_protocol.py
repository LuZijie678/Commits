from __future__ import annotations

from code.mica.stage0.data_card import validate_data_card_text
from code.mica.stage0.eval_protocol import validate_eval_protocol_text


def test_data_card_validation_requires_core_assets_and_boundaries() -> None:
    text = """
# DATA_CARD
Step1 high-confidence k=1
Step2 strict synthetic k1/k2
Step2 Step3-ready synthetic
hard_b train/dev/test
M weak train/dev/final-test
M-align-calib
RealDomainSplit split:
RealDomainSelective split:
RealDomainSelective labels:
RealDomainBinary is deprecated and must not be used in final tables
renderer data, optional
high
medium-high
medium
medium-low
eval-only
M-final-test = eval-only
hard_b-test = eval-only
RealDomainSplit-test = eval-only
RealDomainSelective-test = eval-only
M weak = censored k>=2 only
M-align-calib = small real alignment calibration/eval only
intent_subjects/messages = renderer only, not attribution matching
Kmax is a task-scope constant, not a tuned model hyperparameter
Kmax coverage statistics must be recorded before training
k > Kmax commits are treated as complex/overflow cases
overflow/abstention is required for out-of-scope decomposition
Kmax selection protocol uses train/dev annotation assets only
coverage@Kmax must be reported on every evaluation split
never tune Kmax according to final-test attribution or message utility scores
synthetic cardinality distribution alone cannot justify Kmax
Kmax=4 is acceptable only if DATA_CARD shows target-domain coverage
Kmax freeze protocol
status: protocol_defined_but_value_not_populated
status: protocol_defined_but_stats_not_populated
paper_readiness: not ready until train/dev coverage stats are populated and frozen
current_workspace_state: implementation_default_not_final_paper_task_boundary
atomic-source leakage is prohibited
synthetic variants from the same atomic source cannot cross train/dev/test
no commits from the same PR/tangled construction group may cross splits
commit messages / PR titles / issue texts / gold intent ids / synthetic construction metadata are forbidden as attribution inputs
real_alignment_benchmark
heldout_policy: to_be_frozen_before_final_evaluation
pseudo_alignment_allowed_as_gold: false
synthetic_labels_allowed_as_real_gold: false
"""
    result = validate_data_card_text(text)

    assert result["valid"] is True
    assert not result["missing_requirements"]


def test_eval_protocol_validation_requires_stage_sections_and_frozen_protocol_states() -> None:
    text = """
# EVAL_PROTOCOL
Stage 1 synthetic attribution validation
Stage 2 hard_b / M calibration
Stage 3 real alignment calibration/eval
Stage 4 deterministic evidence-locked rendering
RealDomainSplit / hard_b main table
alignment benchmark table
message utility table
anti-shortcut / OOD stress
baseline table
RealDomainSplit table
RealDomainSelective table
Abstention thresholds:
selection_split: dev only
default_rule: fixed target coverage or full coverage-risk curve
final_test_tuning: forbidden
values_to_be_populated_by_dev_calibration_script
real alignment benchmark held-out policy:
status: protocol_requires_freeze_before_final_evaluation
cross_repository_heldout_primary
time_based_heldout_secondary
unspecified repo overlap
final-test never used for training/tuning
Kmax coverage reporting is mandatory on every evaluation split
oracle-k vs predicted-k must be reported
generation is downstream utility, not main contribution
overflow / abstention rate must be reported
clustering is a baseline, not the primary formulation
renderer scores cannot select attribution checkpoints
background/null must be audited separately from semantic uncertainty
oracle-k / predicted-k / overflow must be jointly reported where applicable
Stage 2 uses hard_b and M weak labels only for split/no-split/abstain boundary calibration
Stage 3 real alignment calibration is parameter-light and separate from Stage 2 count calibration
renderer metrics cannot select attribution checkpoints, thresholds, templates, prompts, or verifier settings
alignment benchmark construction must be documented
coverage-risk curve must be reported for abstaining models
selective attribution metrics must be reported at fixed coverage levels
abstention precision and false-abstain rate must be reported
forced-decomposition error on out-of-scope commits must be reported
RealDomainSplit = k=1 vs k>=2 split / no-split boundary evaluation
RealDomainSelective = in-scope decomposable vs overflow / abstain evaluation
FPR_hard_b = percentage of hard_b single-intent commits predicted as multi-intent
pseudo alignment cannot be used as final real-alignment gold
synthetic construction labels cannot be mixed into the real alignment benchmark
these diagnostics are validity checks, not method-selection ablations
Primary setting:
cross-repository held-out evaluation
no repository overlap between train/dev calibration assets and final real alignment test
Secondary setting, if cross-repository sample size is insufficient:
time-based held-out evaluation within repository
repo overlap decision cannot remain pending in the final protocol
Background slot audit metrics
background assignment rate
foreground evidence swallowed by background
foreground-to-background error
missing-intent rate by file role
background precision on rule-verified background units
background recall on rule-verified background units
semantic uncertainty must not be counted as correct background assignment
"""
    result = validate_eval_protocol_text(text)

    assert result["valid"] is True
    assert not result["missing_requirements"]
