from __future__ import annotations

from pathlib import Path

from code.mica.stage0.data_card import validate_data_card_text
from code.mica.stage0.eval_protocol import validate_eval_protocol_text


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_current_data_card_doc_matches_stage0_validator() -> None:
    text = (REPO_ROOT / "docs" / "DATA_CARD.md").read_text(encoding="utf-8")
    result = validate_data_card_text(text)
    assert result["valid"] is True, result["missing_requirements"]


def test_current_eval_protocol_doc_matches_stage0_validator() -> None:
    text = (REPO_ROOT / "docs" / "EVAL_PROTOCOL.md").read_text(encoding="utf-8")
    result = validate_eval_protocol_text(text)
    assert result["valid"] is True, result["missing_requirements"]


def test_current_state_index_points_to_current_source_of_truth() -> None:
    index_text = (REPO_ROOT / "docs" / "MICA_IMPLEMENTATION_INDEX.md").read_text(encoding="utf-8")
    state_text = (REPO_ROOT / "docs" / "MICA_CURRENT_STATE_AND_PLAN_GAP.md").read_text(encoding="utf-8")
    assert "docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md" in index_text
    assert "current code is source of truth" in state_text


def test_v3_plan_docs_state_bounded_latent_set_attribution_boundaries() -> None:
    plan_text = (REPO_ROOT / "docs" / "plans" / "MICA_v3_trainable_algorithm_plan.md").read_text(
        encoding="utf-8"
    )
    cn_text = (REPO_ROOT / "docs" / "plans" / "MICA_v3_trainable_algorithm_plan_cn.md").read_text(
        encoding="utf-8"
    )

    for text in (plan_text, cn_text):
        assert "bounded latent" in text
        assert "overflow" in text
        assert "abst" in text
        assert "Why not clustering?" in text
        assert "diagnostic baseline" in text
        assert "Kmax is a task-scope constant" in text
        assert "not a tuned model hyperparameter" in text
        assert "Kmax selection protocol" in text
        assert "coverage@Kmax" in text
        assert "Input-side fields" in text
        assert "Label-side fields" in text
        assert "atomic-source leakage is prohibited" in text
        assert "synthetic variants" in text
        assert "L_bg" in text
        assert "foreground-to-background error" in text
        assert "coverage-risk curve" in text
        assert "MVP-Core" in text
        assert "Target paper system" in text
        assert "message_keyword_overlap" in text
        assert "offline auditing / shortcut diagnosis only" in text
        assert "not used by encoder input" in text
        assert "not used by relation construction" in text
        assert "not used by attribution checkpoint selection" in text
        assert "thresholds, templates, prompts, or verifier settings" in text
        assert "Claims and Validation Protocol" in text or "Claims and Validation Protocol" in plan_text
        assert "Non-negotiable Protocol Constraints" in text or "Non-negotiable Protocol Constraints" in plan_text
        assert "RealDomainSelective" in text
        assert "RealDomainSplit" in text
        assert "MaskedBCE" in text
        assert "synthetic cardinality distribution alone cannot justify Kmax" in text
        assert "Kmax=4 is acceptable only if DATA_CARD shows" in text
        assert "Shared-support units are marked and reported separately" in text
        assert "these diagnostics are validity checks, not method-selection ablations" in text


def test_v3_plan_docs_do_not_keep_old_type_cost_pseudocode_or_stage2_stage3_confusion() -> None:
    plan_text = (REPO_ROOT / "docs" / "plans" / "MICA_v3_trainable_algorithm_plan.md").read_text(
        encoding="utf-8"
    )
    cn_text = (REPO_ROOT / "docs" / "plans" / "MICA_v3_trainable_algorithm_plan_cn.md").read_text(
        encoding="utf-8"
    )

    for text in (plan_text, cn_text):
        assert "type_cost" not in text
        assert "Stage 2 does not use real alignment calibration data" in text or "Stage 2 不使用 real alignment calibration" in text
        assert "M-align-calib is excluded from Stage 2" in text or "M-align-calib 不属于 Stage 2" in text
        assert "Only top calibration heads and adapters are trainable in the default Stage 3 protocol" in text


def test_v3_plan_docs_distinguish_target_vs_current_branch_code_states() -> None:
    plan_text = (REPO_ROOT / "docs" / "plans" / "MICA_v3_trainable_algorithm_plan.md").read_text(
        encoding="utf-8"
    )
    cn_text = (REPO_ROOT / "docs" / "plans" / "MICA_v3_trainable_algorithm_plan_cn.md").read_text(
        encoding="utf-8"
    )

    assert "This section is code-derived from the current branch audit." in plan_text
    assert "Current branch already implemented and test-covered" in plan_text
    assert "function-level infrastructure without real experiment evidence" in plan_text
    assert "placeholder interfaces / not implemented" in plan_text
    assert "Claims prohibited on the current branch" in plan_text
    assert "Implemented and test-covered code does not automatically imply final-paper evidence." in plan_text
    assert "FrozenLLMRenderer" in plan_text
    assert "run_message_baseline_generation.py" in plan_text
    assert "pretrained_generation_baseline.py" in plan_text
    assert "trainable_reranker.py" in plan_text
    assert "proxy_not_human_eval" in plan_text
    assert "values_to_be_populated_by_dev_calibration_script" in plan_text
    assert "optional externally configured FrozenLLMRenderer path" in plan_text
    assert "guarded executable trainable reranker path" in plan_text
    assert "message-level external reference baseline infrastructure" in plan_text
    assert "FrozenLLMRenderer raises `NotConfiguredError`; no external LLM renderer is configured in this repository." not in plan_text
    assert "pretrained_classifier_placeholder.py`: explicit placeholder with `implemented=False`" not in plan_text

    assert "本节结论来自当前分支代码审计" in cn_text
    assert "当前分支已经实现并有测试覆盖的内容" in cn_text
    assert "当前只有函数级基础设施但没有真实实验结果的内容" in cn_text
    assert "当前只有占位接口、尚未实现的内容" in cn_text
    assert "当前禁止宣称已经完成的论文证据" in cn_text
    assert "不等于“已经具备论文最终证据”" in cn_text
    assert "FrozenLLMRenderer" in cn_text
    assert "run_message_baseline_generation.py" in cn_text
    assert "pretrained_generation_baseline.py" in cn_text
    assert "trainable_reranker.py" in cn_text
    assert "proxy_not_human_eval" in cn_text
    assert "values_to_be_populated_by_dev_calibration_script" in cn_text
    assert "可选外部配置的 FrozenLLMRenderer 路径" in cn_text
    assert "guarded 可执行的 trainable reranker 路径" in cn_text
    assert "message-level external reference baseline 基础设施" in cn_text
    assert "FrozenLLMRenderer` 直接抛出 `NotConfiguredError`" not in cn_text
    assert "pretrained_classifier_placeholder.py`：显式 placeholder，`implemented=False`" not in cn_text


def test_report_doc_is_non_authoritative_and_points_to_v3_plans() -> None:
    text = (REPO_ROOT / "docs" / "plans" / "report.md").read_text(encoding="utf-8")

    assert "supporting note / non-authoritative" in text
    assert "MICA_v3_trainable_algorithm_plan.md" in text
    assert "MICA_v3_trainable_algorithm_plan_cn.md" in text
    assert "message_keyword_overlap" in text
    assert "offline auditing / shortcut diagnosis only" in text


def test_consumer_docs_describe_stage1_export_flags_and_output_artifacts() -> None:
    architecture = (REPO_ROOT / "docs" / "MICA_CONSUMER_ARCHITECTURE.md").read_text(encoding="utf-8")
    eval_infra = (REPO_ROOT / "docs" / "MICA_MESSAGE_UTILITY_EVAL_INFRASTRUCTURE.md").read_text(encoding="utf-8")

    for text in (architecture, eval_infra):
        assert "--export-consumer-plans" in text
        assert "--consumer-plan-review-ready" in text
        assert "metadata.consumer_plan_export" in text
        assert "output_jsonl" in text
        assert "error_jsonl" in text
        assert "summary_json" in text
        assert "stage1_official_validation_consumer_plans.jsonl" in text
        assert "stage1_official_validation_consumer_plan_export_summary.json" in text
        assert "stage1_official_validation_dryrun_consumer_plans.jsonl" in text
        assert "stage1_official_validation_dryrun_consumer_plan_export_summary.json" in text
        assert "run_message_baseline_generation.py" in text
        assert "FrozenLLMRenderer" in text
        assert "trainable_reranker.py" in text
        assert "frozen_llm_renderer_openai_compatible.example.json" in text
        assert "message_baseline_generation_spec.example.json" in text
        assert "--validate-only" in text
        assert "error_jsonl" in text


def test_consumer_docs_capture_reranker_replay_and_report_side_status_contracts() -> None:
    architecture = (REPO_ROOT / "docs" / "MICA_CONSUMER_ARCHITECTURE.md").read_text(encoding="utf-8")
    eval_infra = (REPO_ROOT / "docs" / "MICA_MESSAGE_UTILITY_EVAL_INFRASTRUCTURE.md").read_text(encoding="utf-8")
    current_state = (REPO_ROOT / "docs" / "MICA_CURRENT_STATE_AND_PLAN_GAP.md").read_text(encoding="utf-8")

    for text in (architecture, eval_infra, current_state):
        assert "load_candidate_reranker_checkpoint" in text
        assert "score_candidates_with_checkpoint" in text
        assert "not_run_in_this_stage" in text
        assert "missing_grad_conflict" in text
        assert "build_backend_snapshot_rows_from_samples" in text


def test_protocol_docs_capture_selection_and_selective_eval_constraints() -> None:
    data_card = (REPO_ROOT / "docs" / "DATA_CARD.md").read_text(encoding="utf-8")
    eval_protocol = (REPO_ROOT / "docs" / "EVAL_PROTOCOL.md").read_text(encoding="utf-8")

    assert "Kmax selection protocol uses train/dev annotation assets only" in data_card
    assert "coverage@Kmax must be reported on every evaluation split" in data_card
    assert "atomic-source leakage is prohibited" in data_card
    assert "synthetic variants from the same atomic source cannot cross train/dev/test" in data_card
    assert "synthetic cardinality distribution alone cannot justify Kmax" in data_card
    assert "no commits from the same PR/tangled construction group may cross splits" in data_card
    assert "forbidden as attribution inputs" in data_card
    assert "Kmax freeze protocol" in data_card
    assert "protocol_defined_but_stats_not_populated" in data_card
    assert "paper_readiness: not ready until train/dev coverage stats are populated and frozen" in data_card
    assert "RealDomainBinary is deprecated and must not be used in final tables" in data_card
    assert "heldout_policy: to_be_frozen_before_final_evaluation" in data_card

    assert "alignment benchmark construction must be documented" in eval_protocol
    assert "coverage-risk curve must be reported for abstaining models" in eval_protocol
    assert "selective attribution metrics must be reported at fixed coverage levels" in eval_protocol
    assert "forced-decomposition error on out-of-scope commits must be reported" in eval_protocol
    assert "RealDomainSelective = in-scope decomposable vs overflow / abstain evaluation" in eval_protocol
    assert "pseudo alignment cannot be used as final real-alignment gold" in eval_protocol
    assert "Abstention thresholds:" in eval_protocol
    assert "values_to_be_populated_by_dev_calibration_script" in eval_protocol
    assert "protocol_requires_freeze_before_final_evaluation" in eval_protocol
    assert "Background slot audit metrics" in eval_protocol
    assert "foreground-to-background error" in eval_protocol
    assert "background precision on rule-verified background units" in eval_protocol
