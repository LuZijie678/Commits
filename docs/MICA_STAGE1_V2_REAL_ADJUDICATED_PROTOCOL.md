# MICA Stage1-v2 Real-Adjudicated Protocol

状态：`protocol_frozen` + `candidate_materialized` + `annotation_campaign_prepared` + `human_execution_pending` + `not_formal_ready`

本文档记录 Stage1-v2 的重建原则。它是 Stage1-v1 独立审计后的协议重置说明。

当前代码状态：

- 机器可读协议已冻结：
  - `configs/mica/stage1_v2_protocol_spec.json`
- Stage1-v2 asset registry 已建立，且部分 candidate / pilot 资产已经真实物化：
  - `configs/mica/stage1_v2_asset_registry.json`
- 当前只实现了协议、split、标注 queue、baseline / anti-shortcut / multi-seed readiness 基础设施：
  - `code/mica/stage1_v2/`
  - `code/mica/runners/run_stage1_v2_family_split.py`
  - `code/mica/runners/run_stage1_v2_real_count_queue.py`
  - `code/mica/runners/run_stage1_v2_real_adjudicated_queue.py`
  - `code/mica/runners/run_stage1_v2_readiness.py`
- 当前没有 Stage1-v2 训练结果、正式测试结果或正式 Stage 2 入口。
- 当前新增了人工标注 campaign、qualification、calibration round、critical source review 与 immutable audit log 的执行基础设施，但没有任何人工标注结果。
- 当前只允许把 Stage1-v2 视为：
  - `synthetic_assets_materialized`
  - `synthetic_scale_candidate_planned`
  - `annotation_campaign_prepared`
  - `human_execution_pending`
  - `annotation_pending`
  - `not_formal_ready`
  - `stage1_v2_training_blocked`
  - `stage2_entry_blocked`

## 0. 当前冻结内容

Stage1-v2 当前已经被冻结的是“协议配置”，不是“实验资产”。

冻结内容包括：

- primary endpoint：
  - `B-cubed F1 on real k>=2 commits`
- secondary endpoints：
  - `count exact accuracy`
  - `count MAE`
  - `count ECE`
  - `pairwise F1 on real k>=2`
  - `hard-single over-split rate`
  - `background F1`
  - `foreground swallowing rate`
- `tau=0.95`
- synthetic split unit：
  - `atomic_family_id`
- required leakage keys
- annotation agreement gates
- target sample sizes
- repository concentration limits
- seed list
- required baselines
- required ablations
- statistical tests
- Stage 2 Go/No-Go gates

当前仍为 pending 的内容包括：

- RealCount / Real-Adjudicated 的真实人工标注结果
- RealCount-TrainDev exact-count asset
- Real-Adjudicated-Test 双标 / 裁决 / 盲审资产
- null/background 可训练资产
- baseline 实际运行资产
- anti-shortcut 实际 probe 结果
- multi-seed 真实训练结果
- Stage 1-v2 checkpoint / validation / final test

## 0.1 当前真实物化快照

以下内容已经真实落盘，但都不是正式论文证据：

- atomic source audit：
  - accepted：`3754`
  - manual review：`1345`
  - report：
    - `datasets/mica/stage1_v2/atomic_source_pool/atomic_source_quality_report.json`
- family-safe synthetic manifests：
  - train：`140`
  - dev：`109`
  - synthetic_control_test：`143`
  - leakage report：
    - `datasets/mica/stage1_v2/synthetic/cross_split_leakage_report.json`
  - 当前 `leakage_clean=true`
- RealCount candidate / pilot：
  - candidate pool：`5856`
  - pilot queue：`200`
- Real-Adjudicated candidate / pilot：
  - candidate pool：`1800`
  - pilot queue：`100`
  - annotator packages 已盲化导出
- background pilot queue：
  - `120`
- synthetic scale audit：
  - current train/dev/control：`140 / 109 / 143`
  - formal scale status：`scale_insufficient_for_formal_training`
  - candidate target：
    - train minimum `3000`
    - dev minimum `400`
    - control minimum `400`
  - blocked by：
    - `k3_k4_construction_not_implemented`
    - `required_atomic_sources_need_human_verification`
- critical atomic-source review queue：
  - critical：`4679`
  - deferred：`420`
- unified annotation campaign：
  - batch count：`10`
  - scheduled sample assignments：`365`
  - completed samples：`0`
  - deduplicated real annotation count：`199`
- qualification execution package 已生成，但真实结果为空。
- calibration round 1 package 已生成，规模 `30`，但尚未执行。
- annotation audit log 已初始化为空 append-only log。
- 当前 annotation readiness：
  - `annotation_assets_formal_ready=false`
  - `stage1_v2_training_allowed=false`
  - `stage2_entry_allowed=false`
  - `annotation_staffing_complete=false`
  - `annotators_qualified=false`
  - `calibration_round_complete=false`
  - `required_atomic_sources_human_verified=false`

这些物化结果只说明：

- protocol 已经转成 executable infrastructure；
- candidate / pilot assets 已经 materialize；
- 真实人工标注、裁决、blind review 仍未发生；
- current synthetic manifests 仅为 pipeline-validation scale，不是 formal train/dev/control asset；
- Stage1-v2 还不能作为正式训练或论文主结果入口。

## 1. Stage1-v1 的历史地位

Stage1-v1 的原始 official result 保留，不删除、不覆盖。

新增的审计状态记录：

- `configs/mica/official_results/stage1_v1_audit_status.json`

当前重新定性为：

```text
Stage1-v1:
  execution_status = formally_executed
  internal_acceptance = passed
  scientific_validity_audit = failed
  external_paper_evidence = pilot_only
  superseded_by = stage1-v2-protocol
```

Stage1-v1 仍可用于：

- 验证工程链路；
- 调试 metric、manifest、checkpoint、consumer；
- 展示受控 synthetic benchmark 上的可行性；
- 为 Stage1-v2 估算资源和难度。

Stage1-v1 不再可用于：

- 真实 tangled commit 泛化主张；
- `Kmax=4` 的真实数据依据；
- null/background 能力主张；
- 强基线优越性主张；
- Stage 2 正式论文实验的输入依据。

## 2. Stage1-v2 的数据资产分层

Stage1-v2 必须把数据资产严格拆成三类。

### 2.1 Synthetic-Train

用途：

- 学习 slot attribution；
- 提供确定 provenance alignment；
- 提供大规模监督。

限制：

- 不得作为真实效果的主要 test evidence。

### 2.2 Synthetic-Control-Test

用途：

- 验证模型是否恢复构造时的已知 intent；
- 做机制分析、消融和数据规模实验；
- 与旧 Stage1-v1 保持 controlled synthetic 可比性。

输出要求：

- 结果必须明确标注为 `controlled synthetic evaluation`。

### 2.3 Real-Adjudicated-Test

用途：

- 论文主结果；
- 真实 count、partition、background、hard single 等评估；
- 与强 baseline 比较；
- 决定能否进入正式 Stage 2。

规则：

- 主论文结论只能由 `Real-Adjudicated-Test` 支撑。

## 3. P0-1：彻底解决 atomic-source 跨 split 泄漏

当前 pair-level `leakage_group` 不够，split 单位必须提升为 atomic-source family。

### 3.1 正确的 split 语义

应先构建 sample 与 `source_atomic_commit_id` 的二部图。

若两个 synthetic samples 共享任意 atomic source，它们属于同一个 connected component。

定义：

```text
atomic_family_id =
  hash(sorted(all atomic source IDs in the connected component))
```

split 时必须满足：

- `train atomic_family_id ∩ dev atomic_family_id = ∅`
- `train atomic_family_id ∩ test atomic_family_id = ∅`
- `dev atomic_family_id ∩ test atomic_family_id = ∅`

更稳妥的构建顺序：

1. 先按 repository / atomic family 划分 atomic source；
2. 再在各 split 内独立生成 synthetic compositions。

当前代码入口：

- `code/mica/stage1_v2/family_split.py`
- `code/mica/stage1_v2/leakage.py`
- `code/mica/runners/run_stage1_v2_family_split.py`

### 3.2 正式 leakage report 必须检查

- exact sample ID
- commit SHA
- normalized diff hash
- atomic source ID
- atomic family ID
- PR ID
- cherry-pick / backport fingerprint
- construction group
- repository mirror
- near-duplicate edit-unit fingerprint

正式门槛：

- `sample_overlap = 0`
- `atomic_source_overlap = 0`
- `atomic_family_overlap = 0`
- `pr_overlap = 0`
- `normalized_diff_overlap = 0`

### 3.3 repository split

CCF-A 级主结果建议采用 project-disjoint test。

至少对 `Real-Adjudicated-Test`：

- test repository 不得参与训练与阈值选择；
- 同时建议报告：
  - random family-disjoint
  - repository-disjoint
  - leave-one-repository-out 或 repository cluster bootstrap

## 4. P0-2：重做 Kmax 证据链

`stage1-kmax-v1` 对 Stage1-v2 的地位：

```text
invalidated_by_data_audit
```

它不能继续作为 Stage1-v2 的真实 Kmax 依据。

### 4.1 独立建立 RealCount-TrainDev

Kmax 数据应来自独立的真实 exact-count 数据集。

建议规模：

- 最低可用：`1,000–1,500` 个真实 commits
- 目标规模：`2,000–3,000`
- repositories：至少 `50`

每条记录至少包含：

- `commit_id`
- `repository`
- `split`
- `exact_k`
- `annotation_source`
- `annotator_ids`
- `annotation_round`
- `adjudication_status`
- `annotation_version`
- `leakage_group`
- `diff_hash`

禁止进入 Kmax 统计：

- strict synthetic
- strict replay
- censored `k>=2`
- pseudo exact count
- commit-message-derived count
- 缺少人工 provenance 的行
- 重复 commit
- 未 adjudicate 的冲突标签

当前代码入口：

- `code/mica/stage1_v2/real_count.py`
- `code/mica/runners/run_stage1_v2_real_count_queue.py`

### 4.2 更严格的 Kmax 规则

不只看点估计 `coverage(K)`，而应使用 repository-cluster bootstrap 的 95% 置信下界。

建议：

- `tau = 0.95`

但它必须在查看 Stage1-v2 count 结果前冻结。

必须报告完整曲线：

- `coverage@1`
- `coverage@2`
- `coverage@3`
- `coverage@4`
- `coverage@5+`

若统计显示 `K=3` 已满足 95%，但模型容量保留 `Kmax=4`，必须区分：

- 任务边界；
- 模型容量上限；
- 工程兼容选择。

## 5. P0-3：建立真正的 Real-Adjudicated-Test

### 5.1 推荐规模

正式主测试集建议：

- 最低：`600` 个真实 commits
- 目标：`800–1,000`
- repositories：至少 `50`，建议 `60–100`

建议的 exact-k 分层：

- `k=1` 普通：约 `15%`
- `hard single k=1`：约 `15%`
- `k=2`：约 `40%`
- `k=3`：约 `20%`
- `k=4`：约 `10%`

这些是分层评估的 benchmark 配额，不是自然分布估计。

### 5.2 交叉标签覆盖

建议至少保证：

- `same-file multi-intent >= 100`
- `background-heavy >= 100`
- `source + test >= 150`
- `source + docs/config >= 80`
- `cross-module >= 100`
- `large commit >= 80`
- `ambiguous-boundary >= 50`

另建独立 stress set：

- `k > Kmax`
- pure mechanical/background-heavy
- mass refactor
- generated/vendor sync
- release aggregation

stress set 不计入主 attribution 分数，仅用于 overflow / abstention。

### 5.3 repository concentration 约束

建议：

- 单 repository 不超过 test 的 `5%`
- top-5 repositories 不超过 `25%`

当前代码入口：

- `code/mica/stage1_v2/real_adjudicated.py`
- `code/mica/runners/run_stage1_v2_real_adjudicated_queue.py`
- `code/mica/runners/run_stage1_v2_readiness.py`

### 5.4 synthetic 禁止进入主 real test

`Real-Adjudicated-Test` 必须全部是真实开发者 commit。

synthetic 只能放在 `Synthetic-Control-Test`。

## 6. 人工标注协议必须真正执行

### 6.1 标注前 pilot

先选 `80–100` 条不进入最终 test 的样本：

1. 双人独立标注；
2. 统计分歧；
3. 修订 guideline；
4. 冻结 guideline v1。

### 6.2 正式标注

每条 final-test commit：

- 两位标注者独立标注；
- 不显示模型预测；
- 不显示 split 名称；
- 不显示原始 commit message、PR title、issue text；
- 分歧由第三位 adjudicator 裁决。

记录要求：

- `annotator_id`
- `annotation_timestamp`
- `guideline_version`
- `raw_annotation_A`
- `raw_annotation_B`
- `agreement_status`
- `adjudicator_id`
- `adjudicated_annotation`
- `adjudication_reason`

### 6.3 标注内容

每个 edit unit 标注为：

- `foreground(intent_id)`
- `background`
- `shared_support`
- `uncertain`
- `mixed`

每个 intent 还需：

- `action`
- `object`
- optional `scope`

### 6.4 标注质量 gate

正式冻结前至少要求：

- `exact-k weighted kappa >= 0.80`
- `split/no-split kappa >= 0.80`
- `foreground/background agreement >= 0.85`
- `B-cubed annotator agreement >= 0.80`
- `pairwise unit agreement >= 0.80`

若达不到，不降低标准，应：

1. 分析分歧；
2. 修订指南；
3. 重新 pilot；
4. 再冻结。

另外需由未参与原标注的高级审阅者盲审 final test 的 `10%`，并报告 label-error CI。

## 7. P0-4：正式验证 null/background

当前 `use_null_slot=false` 的 Stage1-v1 checkpoint 不能支撑 background 主张。

Stage1-v2 必须重新训练，不建议沿用旧 checkpoint。

新模型要求：

- `use_null_slot = true`

训练数据必须覆盖：

- 明确 mechanical/background units
- semantic foreground 与 formatting/import/lockfile 混合
- source + support test
- background-heavy commits
- 不同语言的机械修改

正式指标至少包括：

- `background precision`
- `background recall`
- `background F1`
- `foreground swallowing rate`
- `background leakage into foreground rate`
- `ResidualForegroundMass`

若不打算训练 null-enabled 模型，就必须删去论文主方法中的正式 background routing 主张。

## 8. 必要 baseline

Stage1-v2 至少需要：

- `B0`: all-one
- `B1`: file/hunk heuristic
- `B2`: TF-IDF clustering
  - predicted-k
  - oracle-k
- `B3`: frozen code-embedding clustering
  - predicted-k
  - oracle-k
- `B4`: supervised pairwise baseline
- `B5`: MICA oracle-k

核心消融控制在 `3–4` 个：

- no relation-aware encoding
- no evidence-aware existence
- no null slot
- no global count head 或 no count consistency

所有可训练 baseline 和消融至少使用 `3` 个 seed；主模型建议 `5` 个 seed。

## 9. anti-shortcut 审计

需要独立证明模型不是仅靠 metadata 或 synthetic construction 模式取胜。

至少包括：

- metadata-only probes
- 文件路径匿名化
- identifier 匿名化
- unit / file 顺序扰动
- file-role 移除
- repository-disjoint 子集
- real vs synthetic 区分难度分析

## 10. seeds、统计检验与不确定性

建议：

- 主模型：`5 seeds`
- 学习型 baseline：`3–5 seeds`
- 确定性 baseline：`1`

必须报告：

- `mean ± std`
- repository-cluster bootstrap 95% CI
- per-seed result
- worst-seed result
- paired bootstrap against strongest baseline
- 必要的多重比较校正

## 11. Stage1-v2 主指标

当前 Stage1-v1 的 unit accuracy 容易被 `k=1` 抬高，因此不能作为唯一核心指标。

建议冻结 primary endpoint 为：

- `B-cubed F1 on real k>=2 commits`

关键 secondary endpoints：

- `count exact accuracy`
- `pairwise F1 on k>=2`
- `hard-single over-split rate`
- `background F1`

所有指标都必须报告：

- 总体
- per-k
- per-repository
- same-file
- background-heavy
- source+docs/config
- hard single
- repository-disjoint

## 12. Stage1-v2 正式实验矩阵

主实验：

- `MICA-v3, null enabled, 5 seeds`
- `Real-Adjudicated-Test`
- `predicted-k attribution`

对照：

- all-one
- file/hunk heuristic
- TF-IDF clustering
- frozen code-embedding clustering
- supervised pairwise baseline
- MICA oracle-k

消融：

- no relation
- no evidence-aware existence
- no null

补充评估：

- Synthetic-Control-Test
- repository-disjoint
- anti-shortcut
- OOD / `k>Kmax` stress
- error analysis

## 13. Stage 2 正式 Go / No-Go gates

只有以下条件全部通过，才能正式进入 Stage 2。

### 数据 gate

- `atomic_source_overlap = 0`
- `atomic_family_overlap = 0`
- repository overlap 符合预声明协议
- `normalized_diff_overlap = 0`
- official real test 未参与任何选择

### 标注 gate

- 双标完成率 `100%`
- adjudication 完成率 `100%`
- `exact-k kappa >= 0.80`
- `B-cubed agreement >= 0.80`
- 独立盲审无高比例重大错误

### 代表性 gate

- 包含 `k=1,2,3,4`
- 包含 hard single
- 包含 background-heavy
- 包含 same-file multi-intent
- 包含 docs/config
- repository concentration 达标

### 模型 gate

- null slot enabled and evaluated
- checkpoint reproducible
- `>=3` seeds，建议 `5`
- 无 checkpoint cherry-picking

### 结果 gate

- 主指标显著优于最强 baseline
- 95% CI 不跨越预声明最小效果
- per-k 无灾难性退化
- repository-disjoint 结果可接受
- anti-shortcut 无 P0 风险

### 协议 gate

- Kmax 由 clean real count asset 冻结
- threshold 仅使用 dev
- primary endpoint 预声明
- official test 只执行冻结实验矩阵

## 14. 推荐推进顺序

### Phase 0

- 保留并降级旧结果；
- 不删除历史证据；
- Stage1-v1 标记为 `pilot_only`。

### Phase 1

冻结 Stage1-v2 协议：

- primary endpoint
- `tau`
- Kmax 规则
- split 规则
- 标注指南
- 样本规模
- baselines
- seeds
- statistical tests
- Go/No-Go gates

### Phase 2

- 先做 `RealCount-TrainDev`
- 重新确定 Kmax

### Phase 3

- 构建真实 full-alignment benchmark
- 先 pilot，再双标、裁决、盲审

### Phase 4

- 重建无泄漏 synthetic train/dev/control-test

### Phase 5

- 训练 Stage1-v2
- 启用 null
- 运行预声明 seeds 与 baselines

### Phase 6

- 只执行一次正式 test matrix
- 不再修改模型、阈值、Kmax、标注、评估脚本、primary metric

### Phase 7

- 先做独立审计
- 只有 Stage1-v2 所有 gate 通过，才进入 Stage 2

## 15. 当前总判断

当前最重要的不是继续优化 Stage1-v1 的 unit accuracy，而是完成以下四件事：

```text
无泄漏的 family/repository split
+ 真实双标 adjudicated benchmark
+ 强 baseline 与 anti-shortcut
+ 多 seed、分层指标和统计检验
```

在 `Stage1-v2 Real-Adjudicated Protocol` 完成前：

- Stage1-v1 仅保留为工程 pilot；
- 正式 Stage 2 继续暂停。

## 16. R2 LLM Diagnostic Amendment Status

2026-07-26 的 Calibration Round 2 属于 `llm_annotation_track`，不是 human calibration。

冻结状态：

- `calibration_round_2_annotation_integrity_report.json`：`r2_annotation_incomplete`
- `calibration_round_2_pre_adjudication_agreement.json`：`not_computed_due_to_integrity_failure`
- `calibration_round_2_gate_report.json`：`blocked_by_incomplete_annotation`
- `calibration_round_2_adjudication_report.json`：`adjudication_not_started_due_to_integrity_failure`
- `calibration_round_2_guideline_decision.json`：`guideline_status=blocked_by_incomplete_annotation`

原因：

- A/B labels 存在于 combined file；
- 缺少独立 A/B actor/context provenance；
- campaign audit log 没有 R2 hash-chain events；
- 因此不能进入 pre-adjudication agreement 或 adjudication。

Stage1-v2 正式 gate 不变：

- LLM track 不能满足 human gate；
- R2 不能解锁剩余 pilot；
- guideline final 仍未冻结；
- Stage1-v2 training 和 Stage 2 仍阻塞。

2026-07-27 补充记录：

- Codex 已完成 R2 `30` 条 diagnostic marking sidecar；
- 用户已复审该 sidecar，并生成 human-reviewed diagnostic sidecar；
- 复审证据类型为 `chat_confirmation`；
- reviewed rows 标记 `human_verified=true` 仅表示用户已复审 Codex 诊断结果；
- reviewed rows 仍保持 `formal_human_evidence=false`；
- formal blocker 固定为 `not_independent_double_annotation_or_adjudication`；
- campaign audit log 已追加 `60` 条 `reviewed` events，覆盖 reviewed diagnostic marking 与 P0/P1/P2/P3 sidecars，hash-chain 校验通过。

因此，R2 diagnostic sidecar 可以辅助 guideline/debug 讨论，但不能替代独立 A/B 标注、pre-adjudication agreement 或第三方裁决。

2026-07-27 diagnostic triage：

- diagnostic analysis：`calibration_round_2_reviewed_diagnostic_analysis.json`
- follow-up queue：`calibration_round_2_review_followup_queue.jsonl`
- guideline v3 draft：`STAGE1_V2_GUIDELINE_PILOT_V3_REVISION_DRAFT.md`
- follow-up queue count：`23`
- P0/P1/P2/P3：`4 / 5 / 14 / 7`
- P0 samples：`calibration_round_2_0004`, `calibration_round_2_0008`, `calibration_round_2_0009`, `calibration_round_2_0016`
- guideline v3 status：`revision_draft_only`

该 triage 不改变正式 gate：R2 仍为 `blocked_by_incomplete_annotation`，human calibration 仍未完成。

Synthetic candidate v2 仅是 LLM screen 后的非正式候选资产：

- original candidates 被标记为 `candidate_quarantined_by_llm_source_review`
- quarantined samples：`45`
- candidate v2 counts：train/dev/control `128 / 100 / 119`
- `human_verified_sources=false`
- `formal_frozen=false`
