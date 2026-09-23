#!/usr/bin/env bash
set -euo pipefail

# Relative-path defaults (no absolute path hardcoding)
RUN_NAME="${RUN_NAME:-step1_strategy_compare}"
BASE_OUTPUT_DIR="${BASE_OUTPUT_DIR:-outputs}"
ALLCOMMITS_PATH="${ALLCOMMITS_PATH:-../../datasets/step1/canonical/prefilter_allcommits_step2_sha_and_expanded_annotated_disjoint.csv}"
ANNOTATED_PATH="${ANNOTATED_PATH:-../../datasets/step1/canonical/annotated_dataset.csv}"
REPO_LIST_PATH="${REPO_LIST_PATH:-../../datasets/step1/runtime_support/resolved_metadata.csv}"
SEED="${SEED:-31}"
PER_TYPE="${PER_TYPE:-0}"
MAX_CANDIDATES="${MAX_CANDIDATES:-0}"
TARGET_COUNT="${TARGET_COUNT:-0}"
SELECTION_STRATEGIES="${SELECTION_STRATEGIES:-rule_only,model_only,model_rule_refilter}"
RUN_PROXY_GAP_ANALYSIS="${RUN_PROXY_GAP_ANALYSIS:-true}"
RUN_AUDIT_SAMPLE_EXPORT="${RUN_AUDIT_SAMPLE_EXPORT:-true}"
FETCH_DIFF="${FETCH_DIFF:-true}"
STRICT_GATES="${STRICT_GATES:-true}"
REQUIRE_ENRICH_COMPLETE="${REQUIRE_ENRICH_COMPLETE:-true}"
REQUIRE_AUDIT_COMPLETION="${REQUIRE_AUDIT_COMPLETION:-false}"
AUDIT_LABELED_CSV="${AUDIT_LABELED_CSV:-}"

cmd=(
  python3 -m src.pipeline.run_step1
  --run-name "$RUN_NAME"
  --base-output-dir "$BASE_OUTPUT_DIR"
  --allcommits "$ALLCOMMITS_PATH"
  --annotated "$ANNOTATED_PATH"
  --repo-list "$REPO_LIST_PATH"
  --seed "$SEED"
  --per-type "$PER_TYPE"
  --max-candidates "$MAX_CANDIDATES"
  --selection-strategies "$SELECTION_STRATEGIES"
  --strategy-target-count "$TARGET_COUNT"
)

if [[ "$FETCH_DIFF" == "true" ]]; then
  cmd+=(--fetch-diff)
fi
if [[ "$STRICT_GATES" == "true" ]]; then
  cmd+=(--strict-gates)
else
  cmd+=(--no-strict-gates)
fi
if [[ "$REQUIRE_ENRICH_COMPLETE" == "true" ]]; then
  cmd+=(--require-enrich-complete)
else
  cmd+=(--no-require-enrich-complete)
fi
if [[ "$REQUIRE_AUDIT_COMPLETION" == "true" ]]; then
  cmd+=(--require-audit-completion)
else
  cmd+=(--no-require-audit-completion)
fi
if [[ "$RUN_PROXY_GAP_ANALYSIS" == "true" ]]; then
  cmd+=(--run-proxy-gap-analysis)
else
  cmd+=(--no-run-proxy-gap-analysis)
fi
if [[ "$RUN_AUDIT_SAMPLE_EXPORT" == "true" ]]; then
  cmd+=(--run-audit-sample-export)
else
  cmd+=(--no-run-audit-sample-export)
fi
if [[ -n "$AUDIT_LABELED_CSV" ]]; then
  cmd+=(--audit-labeled-csv "$AUDIT_LABELED_CSV")
fi

printf 'Running command:\n%s\n' "${cmd[*]}"
"${cmd[@]}"
