# MICA Data Asset Registry

## 1. Current Registry Layout

- checked-in logical registry:
  - `configs/mica/data_asset_registry.json`
  - 保存 logical asset identity、schema、status、hash、用途与协议依赖
- ignored local materialization registry:
  - `configs/mica/data_asset_materializations.local.json`
  - 保存 `artifact_id -> local path`
  - 不提交到 Git

checked-in registry 不直接把本机 `outputs/**` 路径当作 canonical checkpoint 路径；正式 runner 需要通过 logical registry + local materialization 双层解析。

## 2. Per-asset Fields

每个 asset record 至少包含：

- `path`
- `status`
- `schema_version`
- `source_pool`
- `split`
- `record_count`
- `checksum`
- `created_by`
- `leakage_group_key`
- `required_for`
- `allowed_stages`
- `forbidden_stages`
- `eval_only`

可选字段：

- `artifact_id`
- `sha256`
- `storage_uri`
- `local_materialization_required`
- `alias_of`

## 3. Status Semantics

- `frozen`
  - logical asset identity 已冻结
  - 若 `local_materialization_required=true`，还必须存在本机 materialization，且 hash / 内容校验通过
- `candidate_validated`
  - 逻辑资产已登记，但 checked-in registry 不保证本机物化文件一定存在
- `pending_generation`
  - 当前没有正式产物，但可由代码在未来生成
- `pending_annotation`
  - 需要人工标注或人工审定，当前不得伪造
- `missing`
  - 当前明确缺失，且未进入自动生成链

## 4. Current Materialized Assets

已填实并可验证的 formal manifests：

- `strict_synthetic_train`
- `strict_synthetic_dev`
- `strict_synthetic_test`
- `step1_high_conf_single_train`
- `step1_high_conf_single_dev`
- `step1_high_conf_single_test`
- `stage1_official_validation_dev`
- `stage1_official_final_test`
- `strict_replay`
- `hard_b_train`
- `hard_b_dev`
- `hard_b_test`
- `m_weak_train`
- `m_weak_dev`
- `m_weak_test`
- `m_final_test`

Stage 1 checkpoint 当前是 checked-in logical frozen asset：

- asset:
  - `stage1_checkpoint_input`
- artifact id:
  - `stage1_candidate_22bcd358766e_f280eebdf24a_9320b20f609e_seed42`
- sha256:
  - `4c292e0b4f6d7e2b0a291fd9ab1117552922076f3ffb6b28eff06484c33f8c11`
- training git sha:
  - `22bcd358766e1a678ee721c994830bdcf544213c`
- dirty worktree:
  - `false`
- local materialization required:
  - `true`
- supersedes dirty candidate:
  - `stage1_candidate_dirty_2ed7f711afcc_20260723t073100z`

当前本机 materialization 路径：

- `outputs/mica_stage1_clean_candidate_20260723T081816Z/training/stage1_full_model_checkpoint.pt`

Runner 会重新计算 SHA-256；文件缺失、hash 不匹配或 checkpoint 不可加载时都会 fail closed。

## 5. Current Missing Assets

当前仍缺失或待人工补齐的资产：

- `m_align_calib`
- `real_alignment_dev`
- `real_alignment_test`
- `real_alignment_final_test`
- `real_domain_split_test`
- `real_domain_selective_test`
- `renderer_dataset`
- `predicted_plans`
- `oracle_plans`
- `message_utility_manifest`
- `human_pilot_annotations`

这些资产继续保持 missing / pending 状态是刻意的协议行为，不代表代码会自动补齐，也不能被文档表述替代。

## 6. Formal-ready Semantics

registry validation 现在区分：

- schema valid
- assets materialized
- assets content valid
- required assets ready
- readiness by requirement
- formal ready

注意：

- registry JSON 能解析，不等于 formal-ready
- 即使已存在若干 frozen assets，只要 `required_for` 中仍有缺失资产，整体 registry `formal_ready=false`
- 当前 registry 的全局 `formal_ready=false`

`readiness_by_requirement` 用于按用途查看局部 readiness。例如当前分支：

- `stage1_train`
  - ready
- `stage1_threshold_selection`
  - ready
- `stage1_candidate_validation`
  - ready
- `stage1_validation_execute`
  - ready
- `stage3_calibration`
  - not ready
- `stage4_eval_predicted`
  - not ready
- `stage4_eval_oracle`
  - not ready

也就是说：

- Stage 1 official path 所需资产已经 ready
- Stage 3 / Stage 4 所需资产仍未 ready

## 7. Content-level Constraints

当前 registry 校验已经代码化以下约束：

- `mica-formal-asset-manifest-v1`
  - 必须通过 manifest schema / summary / rows / `formal_ready` 校验
- `mica-checkpoint-v2`
  - 必须是 full-model checkpoint
  - metadata-only checkpoint 不能让 `stage1_checkpoint_input` 进入 execute-ready
  - dirty-worktree candidate 不能作为 active frozen Stage 1 checkpoint
  - official execute 前还需要额外通过 clean checkpoint provenance gate

## 8. Current Stage 1 Notes

- `stage1_official_validation_dev`
  - dev-only threshold selection / candidate validation split
- `stage1_official_final_test`
  - official Stage 1 final-test split
  - 已冻结并用于 canonical official validation
- checked-in approval decisions：
  - `configs/mica/protocol_decisions/stage1_threshold_approval.json`
  - `configs/mica/protocol_decisions/stage1_kmax_decision.json`
- checked-in official result record：
  - `configs/mica/official_results/stage1_official_validation_20260723T091921Z.json`
- runtime official output root：
  - `outputs/mica_stage1_official_validation_20260723T091744Z/official_run`
- official execution 状态：
  - `official_validation_executed=true`
  - `formal_ready=true`
  - `paper_ready=false`
  - 当前失败的 frozen acceptance criterion：
    - `unit_accuracy_gain_over_all_one_min`
      - `observed=null`

## 9. Legacy Compatibility

为兼容现有 Stage 2 / Stage 3 runner 与 config validation，registry 仍保留若干 legacy-style key：

- `m_final_test`
  - 当前指向 `m_weak_test`
- `real_alignment_final_test`
  - 当前作为 `real_alignment_test` 的 compatibility alias

这些兼容 key 不改变协议语义，只是避免 runner / config 继续依赖旧命名时出现歧义。
