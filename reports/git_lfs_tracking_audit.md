# Git LFS Tracking Audit

- Tracked files: `2936`
- Tracked output files: `0`
- Tracked output bytes: `0`
- LFS files: `1609`
- LFS local bytes: `7209081666`
- outputs/** LFS rule present: `False`
- global *.jsonl LFS rule present: `False`

## Interpretation

Runtime `outputs/**` directories are timestamped experiment artifacts and should not be versioned. Existing LFS objects under `datasets/**` and `archive/**` are historical/formal data assets and are not rewritten by this audit.

## Largest Tracked Files

- `datasets/m_verified/canonical/usable_m_with_real_diff.jsonl`: `581432499` bytes
- `datasets/m_verified/canonical/usable_m_with_real_diff.csv`: `564795549` bytes
- `archive/datasets/m_verified/workspace/recovery_batches/ingest_workspace_backlog_20260603_label_input.csv`: `300572716` bytes
- `datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p3000_20260527T071833Z/strategy_compare_20260527T071833Z/model_rule_refilter/candidate_scores.csv`: `284596956` bytes
- `datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p3000_20260527T071833Z/strategy_compare_20260527T071833Z/model_only/candidate_scores.csv`: `284091868` bytes
- `datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p3000_20260527T071833Z/strategy_compare_20260527T071833Z/rule_only/candidate_scores.csv`: `284015800` bytes
- `datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p3000_20260527T071833Z/enriched/resolved_candidates.csv`: `282697296` bytes
- `datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p3000_20260527T071833Z/enriched/resolved_commit_texts.jsonl`: `256741458` bytes
- `datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p3000_20260527T071833Z/validation/tier_c_candidates.csv`: `212675229` bytes
- `datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p1600_20260526T024945Z/strategy_compare_20260526T024945Z/model_rule_refilter/candidate_scores.csv`: `144561699` bytes
- `datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p1600_20260526T024945Z/strategy_compare_20260526T024945Z/model_only/candidate_scores.csv`: `144293315` bytes
- `datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p1600_20260526T024945Z/strategy_compare_20260526T024945Z/rule_only/candidate_scores.csv`: `144252643` bytes
- `datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p1600_20260526T024945Z/enriched/resolved_candidates.csv`: `143548875` bytes
- `datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p1600_20260526T024945Z/enriched/resolved_commit_texts.jsonl`: `134000486` bytes
- `archive/datasets/m_verified/workspace/recovery_batches/20260529_deepseek_experiment_full_ingest_label_input.csv`: `111245364` bytes
- `datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p1600_20260526T024945Z/validation/tier_c_candidates.csv`: `107393064` bytes
- `datasets/hard_b/canonical/usable_hard_b_with_real_diff.jsonl`: `102428237` bytes
- `datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv`: `98458359` bytes
- `datasets/step2/review/m_only_review_sheet.csv`: `90806676` bytes
- `datasets/step2/candidate_sources/m_only_disjoint_candidates.csv`: `90611874` bytes
