from __future__ import annotations

from typing import Any


STAGE1_V2_PROTOCOL_SCHEMA_VERSION = "mica-stage1-v2-protocol-spec-v1"
DEFAULT_MICA_SEEDS = [13, 42, 2026, 2607, 7240]
DEFAULT_LEARNED_BASELINE_SEEDS = [13, 42, 2026]
DEFAULT_DETERMINISTIC_BASELINE_REPEATS = 1
DEFAULT_REQUIRED_BASELINES = [
    "all_one",
    "file_hunk_heuristic",
    "tfidf_clustering_predicted_k",
    "tfidf_clustering_oracle_k",
    "frozen_code_embedding_clustering_predicted_k",
    "frozen_code_embedding_clustering_oracle_k",
    "supervised_pairwise_baseline",
    "mica_oracle_k",
]
DEFAULT_REQUIRED_ABLATIONS = [
    "no_relation_aware_encoding",
    "no_evidence_aware_existence",
    "no_null_slot",
]
DEFAULT_REQUIRED_LEAKAGE_KEYS = [
    "sample_id",
    "sha",
    "normalized_diff_hash",
    "edit_unit_fingerprint",
    "source_atomic_commit_ids",
    "atomic_family_id",
    "construction_group",
    "pr_id",
    "repository_mirror_id",
    "cherry_pick_fingerprint",
    "backport_fingerprint",
    "revert_fingerprint",
]
DEFAULT_SECONDARY_ENDPOINTS = [
    "count_exact_accuracy",
    "count_mae",
    "count_ece",
    "pairwise_f1_real_k_ge_2",
    "hard_single_over_split_rate",
    "background_f1",
    "foreground_swallowing_rate",
]
DEFAULT_STATISTICAL_TESTS = {
    "sample_bootstrap_ci": {"enabled": True, "confidence_level": 0.95, "bootstrap_samples": 1000},
    "repository_cluster_bootstrap_ci": {"enabled": True, "confidence_level": 0.95, "bootstrap_samples": 1000},
    "paired_bootstrap_against_strongest_baseline": {"enabled": True, "confidence_level": 0.95, "bootstrap_samples": 2000},
    "paired_permutation_test": {"enabled": True, "permutations": 2000},
    "multiple_comparison_correction": {"enabled": True, "method": "holm_bonferroni"},
}
DEFAULT_GO_NO_GO_GATES = [
    "atomic_source_overlap_zero",
    "atomic_family_overlap_zero",
    "construction_group_overlap_zero",
    "normalized_diff_overlap_zero",
    "official_real_test_unexposed",
    "double_annotation_complete",
    "adjudication_complete",
    "exact_k_weighted_kappa_gte_0_80",
    "split_no_split_kappa_gte_0_80",
    "foreground_background_agreement_gte_0_85",
    "bcubed_annotator_agreement_gte_0_80",
    "pairwise_unit_agreement_gte_0_80",
    "blind_review_no_high_major_error_rate",
    "benchmark_strata_ready",
    "repository_concentration_passed",
    "null_slot_enabled_and_evaluable",
    "baseline_matrix_ready",
    "anti_shortcut_ready",
    "seed_matrix_frozen",
    "statistical_protocol_frozen",
]


def build_default_stage1_v2_protocol_spec() -> dict[str, Any]:
    return {
        "schema_version": STAGE1_V2_PROTOCOL_SCHEMA_VERSION,
        "protocol_version": "stage1-v2-protocol",
        "protocol_status": "protocol_frozen",
        "asset_status": "assets_pending",
        "primary_endpoint": "bcubed_f1_real_k_ge_2",
        "secondary_endpoints": list(DEFAULT_SECONDARY_ENDPOINTS),
        "kmax_rule": {
            "tau": 0.95,
            "selection_rule": "minimum_K_with_repository_cluster_bootstrap_95_lcb_gte_tau",
            "coverage_split_scope": ["train", "dev"],
            "forbidden_sources": [
                "strict_synthetic",
                "strict_replay",
                "censored_k_ge_2",
                "pseudo_exact_count",
                "commit_message_derived_count",
            ],
        },
        "split_policy": {
            "synthetic_split_unit": "atomic_family_id",
            "real_test_repository_policy": "project_disjoint_preferred",
            "required_leakage_keys": list(DEFAULT_REQUIRED_LEAKAGE_KEYS),
            "control_test_name": "synthetic_control_test",
        },
        "annotation_gates": {
            "exact_k_weighted_kappa_min": 0.80,
            "split_no_split_kappa_min": 0.80,
            "foreground_background_agreement_min": 0.85,
            "bcubed_agreement_min": 0.80,
            "pairwise_unit_agreement_min": 0.80,
            "blind_review_fraction_min": 0.10,
        },
        "target_sample_sizes": {
            "real_count_train_dev_min": 1000,
            "real_count_train_dev_target": 2000,
            "real_count_repository_min": 50,
            "real_adjudicated_test_min": 600,
            "real_adjudicated_test_target": 800,
            "real_adjudicated_repository_min": 50,
        },
        "real_adjudicated_target_distribution": {
            "k1_regular": 120,
            "k1_hard_single": 120,
            "k2": 320,
            "k3": 160,
            "k4": 80,
        },
        "benchmark_strata_targets": {
            "same_file_multi_intent": 100,
            "background_heavy": 100,
            "source_test": 150,
            "source_docs_config": 80,
            "cross_module": 100,
            "large_commit": 80,
            "ambiguous_boundary": 50,
        },
        "repository_concentration_limits": {
            "single_repository_max_fraction": 0.05,
            "top5_repository_max_fraction": 0.25,
        },
        "model_requirements": {
            "use_null_slot": True,
            "seeds": list(DEFAULT_MICA_SEEDS),
        },
        "baseline_matrix": {
            "required_baselines": list(DEFAULT_REQUIRED_BASELINES),
            "required_ablations": list(DEFAULT_REQUIRED_ABLATIONS),
            "learned_baseline_seeds": list(DEFAULT_LEARNED_BASELINE_SEEDS),
            "deterministic_baseline_repeats": DEFAULT_DETERMINISTIC_BASELINE_REPEATS,
        },
        "anti_shortcut": {
            "required_probes": [
                "metadata_only_count_probe",
                "real_vs_synthetic_probe",
                "path_anonymization",
                "identifier_anonymization",
                "unit_order_shuffle",
                "file_order_shuffle",
                "file_role_removal",
                "repository_disjoint_evaluation",
            ]
        },
        "statistical_tests": dict(DEFAULT_STATISTICAL_TESTS),
        "go_no_go_gates": list(DEFAULT_GO_NO_GO_GATES),
        "notes": {
            "stage1_v1_results_are_historical_only": True,
            "stage1_v1_formal_evidence_reuse_for_v2": False,
        },
    }


def validate_stage1_v2_protocol_spec(spec: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if str(spec.get("schema_version") or "") != STAGE1_V2_PROTOCOL_SCHEMA_VERSION:
        errors.append("invalid_schema_version")
    if str(spec.get("protocol_version") or "") != "stage1-v2-protocol":
        errors.append("invalid_protocol_version")
    if str(spec.get("protocol_status") or "") != "protocol_frozen":
        errors.append("protocol_not_frozen")
    if str(spec.get("asset_status") or "") != "assets_pending":
        warnings.append("asset_status_not_assets_pending")
    if str(spec.get("primary_endpoint") or "") != "bcubed_f1_real_k_ge_2":
        errors.append("primary_endpoint_mismatch")
    secondary = list(spec.get("secondary_endpoints") or [])
    for required in DEFAULT_SECONDARY_ENDPOINTS:
        if required not in secondary:
            errors.append(f"missing_secondary_endpoint:{required}")
    kmax_rule = dict(spec.get("kmax_rule") or {})
    if float(kmax_rule.get("tau") or 0.0) != 0.95:
        errors.append("tau_must_equal_0_95")
    if str(kmax_rule.get("selection_rule") or "") != "minimum_K_with_repository_cluster_bootstrap_95_lcb_gte_tau":
        errors.append("invalid_kmax_selection_rule")
    split_policy = dict(spec.get("split_policy") or {})
    if str(split_policy.get("synthetic_split_unit") or "") != "atomic_family_id":
        errors.append("synthetic_split_unit_must_be_atomic_family_id")
    missing_leakage_keys = [key for key in DEFAULT_REQUIRED_LEAKAGE_KEYS if key not in list(split_policy.get("required_leakage_keys") or [])]
    if missing_leakage_keys:
        errors.append(f"missing_required_leakage_keys:{','.join(missing_leakage_keys)}")
    annotation_gates = dict(spec.get("annotation_gates") or {})
    expected_annotation_gates = {
        "exact_k_weighted_kappa_min": 0.80,
        "split_no_split_kappa_min": 0.80,
        "foreground_background_agreement_min": 0.85,
        "bcubed_agreement_min": 0.80,
        "pairwise_unit_agreement_min": 0.80,
    }
    for key, value in expected_annotation_gates.items():
        if float(annotation_gates.get(key) or 0.0) != value:
            errors.append(f"annotation_gate_mismatch:{key}")
    model_requirements = dict(spec.get("model_requirements") or {})
    if model_requirements.get("use_null_slot") is not True:
        errors.append("null_slot_required")
    seeds = list(model_requirements.get("seeds") or [])
    if seeds != DEFAULT_MICA_SEEDS:
        errors.append("mica_seed_list_mismatch")
    baseline_matrix = dict(spec.get("baseline_matrix") or {})
    if list(baseline_matrix.get("required_baselines") or []) != DEFAULT_REQUIRED_BASELINES:
        errors.append("required_baselines_mismatch")
    if list(baseline_matrix.get("required_ablations") or []) != DEFAULT_REQUIRED_ABLATIONS:
        errors.append("required_ablations_mismatch")
    if list(spec.get("go_no_go_gates") or []) != DEFAULT_GO_NO_GO_GATES:
        errors.append("go_no_go_gates_mismatch")
    return {"valid": not errors, "errors": errors, "warnings": warnings}
