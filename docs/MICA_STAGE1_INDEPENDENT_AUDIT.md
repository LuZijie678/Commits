# MICA-v3 Stage 1 独立复核审计

> 历史审计快照：下文分支、HEAD、Git SHA 和工作树状态均指 2026-07-23 的旧仓库环境；新仓库 `main` 未继承这些提交。科研结论仍应保留，但当前入口请看 [当前项目状态](CURRENT_STATUS.md)。

审计日期：`2026-07-23`

本文件记录一次只读、独立、端到端的 Stage 1 审计结论。它不修改 checkpoint、阈值、Kmax、split、official predictions 或 official result，只基于当前仓库中的冻结代码、配置、资产和运行产物给出结论。

## A. Executive Verdict

- 结论：`NO_GO_STAGE2`
- 一句话核心理由：
  - Stage 1 已经 `implemented`、`tested`、`formally executed`，但还没有通过独立有效性审计。
  - 当前存在 P0 级别问题：
    - strict synthetic 原子来源跨 split 暴露；
    - Kmax freeze 证据链被 synthetic / 重复行污染；
    - official final test 不是人工 adjudicated 的真实多意图 benchmark；
    - final-test 标注质量没有独立可核验证据。

## B. Reproducibility

- 审计时的旧分支：`experiment/llm-generation-pilot-clean`
- 审计时的旧 HEAD：`8834f557b9bc42c056c1aeef688e1710506e3b16`
- 当前工作树无关脏文件：
  - `m_existing_diff_package/data/continuous_m_crawl.launchd.log`
- clean training Git SHA：
  - `22bcd358766e1a678ee721c994830bdcf544213c`
- official execution Git SHA：
  - `f85b5260057a213a04bb4ea0a3c8cb720caa5dff`
- checkpoint artifact：
  - `stage1_candidate_22bcd358766e_f280eebdf24a_9320b20f609e_seed42`
- checkpoint SHA-256：
  - `4c292e0b4f6d7e2b0a291fd9ab1117552922076f3ffb6b28eff06484c33f8c11`
- threshold version：
  - `frozen_dev_thresholds_v1`
- Kmax decision version：
  - `stage1-kmax-v1`
- official final-test manifest hash：
  - `0c0ca7acdbce65f9533b0119193b480db0f9304abe29367349c7c51c2e3ee3d8`
- official run ID：
  - `stage1_official_validation_20260723T091921Z`
- official result record：
  - `configs/mica/official_results/stage1_official_validation_20260723T091921Z.json`
- supplemental metric record：
  - `configs/mica/official_results/stage1_official_validation_20260723T091921Z_supplement_v1.json`
- latest status revision：
  - `configs/mica/official_results/stage1_official_validation_20260723T091921Z_status_revision_v1.json`

复核结论：

- checkpoint、threshold、Kmax、final-test manifest 和 official predictions 的绑定关系是明确且可复算的。
- 原始 official result、supplement 和 status revision 均保留，未被覆盖。
- checkpoint 可加载，round-trip 与 fixed-input consistency 已通过。
- 这一层可以判定为 `reproducible`，但不能因此推出 `scientifically valid`。

## C. Data Validity

### C.1 官方 Stage 1 final test 的真实组成

证据文件：

- `datasets/mica/formal_assets/stage1/stage1_official_final_test.json`

审计结果：

- `record_count=500`
- `repo_count=49`
- `source_type_distribution`：
  - `step1_high_conf_single=250`
  - `strict_synthetic=250`
- `label_distribution`：
  - `exact_k1_gold=250`
  - `exact_k2_gold=250`

这意味着当前 official final test 不是“真实多意图 commit final benchmark”，而是：

1. 250 条高置信 atomic 单意图真实 commit；
2. 250 条 strict synthetic 双意图组合样本。

该 final test 不包含：

- `k>=3`
- `hard_b`
- 大量 background-heavy 场景
- 明显 same-file multi-intent 场景

### C.2 synthetic split 原子来源泄漏

代码证据：

- `code/mica/data/formal_assets.py`
- `code/mica/stages/stage1_split_exposure.py`
- `code/mica/stage0/leakage_report.py`

关键实现事实：

- `formal_assets.py` 以 pair-level `leakage_group` 切分 synthetic rows。
- `stage1_split_exposure.py` 只检查 `sample_id` 和 `leakage_group`。
- `leakage_report.py` 只检查 `sample_id`、`sha`、`synthetic_id` 交叉，不检查 `source_atomic_commit_ids`。

只读复核统计：

- `strict_synthetic_train` vs `strict_synthetic_dev`
  - `sample_overlap=0`
  - `leakage_overlap=0`
  - `atomic_overlap=205`
  - `rows_hit_left=599`
  - `rows_hit_right=226`
- `strict_synthetic_train` vs `strict_synthetic_test`
  - `sample_overlap=0`
  - `leakage_overlap=0`
  - `atomic_overlap=214`
  - `rows_hit_left=566`
  - `rows_hit_right=225`
- `strict_synthetic_dev` vs `strict_synthetic_test`
  - `sample_overlap=0`
  - `leakage_overlap=0`
  - `atomic_overlap=96`
  - `rows_hit_left=145`
  - `rows_hit_right=155`
- `stage1_official_validation_dev` vs `stage1_official_final_test`
  - `sample_overlap=0`
  - `leakage_overlap=0`
  - `atomic_overlap=96`
  - `rows_hit_left=145`
  - `rows_hit_right=155`

结论：

- 当前仓库里 `dev_only_unexposed_final_test` 只在 pair-level `leakage_group` 语义上成立。
- 在 atomic-source family 语义上不成立。
- 因此 `official_final_test_unexposed=true` 不能作为独立有效性审计下的通过依据。

### C.3 代表性与样本覆盖

只读统计：

- `sample_count=500`
- `repo_count=49`
- `top-5 repo`：
  - `camunda/zeebe=56`
  - `crimx/ext-saladict=45`
  - `ionic-team/ionic-framework=38`
  - `influxdata/influxdb=38`
  - `openreplay/openreplay=26`
- `top-5 share=0.406`
- `gold_k`：
  - `k=1: 250`
  - `k=2: 250`
- `same_file_multi_intent_samples=0`

分层覆盖稀薄：

- `source+test=47`
- `source+config=19`
- `source+doc=1`
- `background_like=4`

结论：

- 该 official final test 只能支持狭义的 Stage 1 attribution acceptance 验证。
- 它不能支持：
  - `Kmax=4` 的真实边界主张；
  - `k>=3` 泛化主张；
  - 广义 real tangled commit 分解主张；
  - 背景/复杂边界场景的强结论。

## D. Annotation Quality

### D.1 已存在的协议与指南

证据文件：

- `docs/annotation/REAL_ALIGNMENT_GUIDELINES.md`
- `configs/mica/real_alignment_annotation_spec.json`

这些文件定义了：

- 双标推荐；
- disagreement 进入 adjudication；
- agreement 指标应报告。

### D.2 official final test 缺失的可核验标注证据

对 `datasets/mica/formal_assets/stage1/stage1_official_final_test.json` 的只读检查结果：

- `annotator_id=0`
- `annotation_round=0`
- `annotation_version=0`
- `adjudicator_id=0`
- `adjudication_status=0`
- `annotation_source=0`
- `annotation_confidence=0`
- `double_annotated=0`

对 `outputs/mica_stage1_official_validation_20260723T091744Z/` 的检查结果：

- 未发现与当前 official Stage 1 final test 绑定的 `agreement` / `adjudication` / `annotation` 产物。

结论：

- `exact-k agreement`：`unknown`
- `split/no-split agreement`：`unknown`
- `foreground/background agreement`：`unknown`
- `pairwise unit agreement`：`unknown`
- `B-cubed agreement`：`unknown`
- `ARI agreement`：`unknown`
- `kappa`：`unknown`
- `adjudication rate`：`unknown`

整体结论：

- `annotation-quality-not-verified`

### D.3 blind sample review

本轮使用固定随机种子对 official final test 做了不看模型预测、不看 commit message 的 diff-only 抽样复核。

抽样规模：

- `50 commits`

可覆盖 strata：

- `k=1`
- `k=2`
- `source+test`
- `source+config`
- `source+doc`
- `background_like`

官方 final test 中缺失或近乎缺失的 strata：

- `k>=3`
- `hard single-intent`
- `same_file_multi_intent`

复核结论：

- atomic `k=1` 与少量 background-like 样本中，未直接观察到明显自相矛盾的 gold 结构。
- 但大部分 `k=2` 样本是 synthetic-by-construction，它们只能验证构造标签一致性，不能证明真实多意图人工标注质量。
- 因缺失双标/裁决原始记录，无法给出可信的标签错误率和置信区间。

## E. Experimental Design

### E.1 已实现并与目标一致的部分

- assignment / existence / count / Hungarian 链路存在真实实现；
- clean full-model checkpoint 已产出并被 official run 消费；
- canonical official runner、supplemental metric 和 revision chain 都已闭合。

这些内容可判定为：

- `implemented`
- `tested`
- `formally executed`

### E.2 关键设计与证据链风险

1. `null/background` 在官方 Stage 1 checkpoint 中没有被正式验证为主贡献。
   - checkpoint metadata 显示 `use_null_slot=false`。
2. Kmax freeze 的“exact-real only”证据链不成立。
3. Stage 1 final test 大量依赖 synthetic `k=2`，使 Stage 1 对真实 tangled commit 的解释力不足。
4. 当前 Stage 1 结果更接近“synthetic + atomic acceptance”而不是“real multi-intent benchmark”。

总体判断：

- 方法实现：`合理`
- 证据支持范围：`存在重大风险`

## F. Metrics Recalculation

只读重算输入：

- frozen official predictions
- frozen official final-test manifest
- frozen aggregate metrics
- frozen supplement record

未重新运行模型推理。

### F.1 与 official record 一致的指标

- `count_accuracy=0.916`
- `count_mae=0.084`
- `pairwise_f1=0.6542900627274749`
- `ARI=0.3000589697982615`
- `NMI=0.4107364591971202`
- `B-cubed F1=0.9672794467483549`
- `unit_accuracy=0.9623698380051321`
- `hunk_micro_f1=0.9623698380051321`

差值：

- 全部 `0.0`

### F.2 supplemental acceptance metric

- `all_one_baseline_accuracy=0.8301833026082103`
- `MICA unit_accuracy=0.9623698380051325`
- `unit_accuracy_gain_over_all_one=0.13218653539692227`
- acceptance threshold：
  - `0.03`
- `passed=true`

状态：

- `metric_recovered_from_frozen_artifacts`

### F.3 分母与 exclusions

- `eligible_samples=500`
- `eligible_units=2526`
- `excluded_samples=0`
- `excluded_units=0`

### F.4 95% bootstrap CI

- overall bootstrap：
  - `count_accuracy: [0.89, 0.938]`
  - `pairwise_f1: [0.6159233823855038, 0.6914817094472736]`
  - `unit_accuracy: [0.9518091362885481, 0.9717284741402389]`
  - `B-cubed F1: [0.958797334979578, 0.975106063538114]`
- repository cluster bootstrap：
  - `count_accuracy: [0.8838475499092558, 0.9448476052249637]`
  - `pairwise_f1: [0.5994313895371415, 0.6956716355595761]`
  - `unit_accuracy: [0.9518833585921899, 0.9727111434750684]`
  - `B-cubed F1: [0.9583126908251827, 0.975948320547661]`

### F.5 per-k

- `gold k=1`：
  - `count_accuracy=0.912`
  - `pairwise_f1_mean=0.5904712066159085`
  - `unit_accuracy_mean=0.9771937657114128`
  - `B-cubed F1_mean=0.9822318240673524`
- `gold k=2`：
  - `count_accuracy=0.92`
  - `pairwise_f1_mean=0.7181089188390414`
  - `unit_accuracy_mean=0.9475459102988515`
  - `B-cubed F1_mean=0.9523270694293573`

## G. Result Quality

### G.1 对当前冻结 benchmark 的结果判断

- 标签：`strong`
- 理由：
  - 计数和 unit-level attribution 指标都高于 acceptance threshold；
  - 对 `all-one` baseline 的 unit accuracy 绝对提升为 `0.1322`；
  - bootstrap CI 没有贴近内部阈值边界。

### G.2 对论文级主张的结果判断

- 标签：`inconclusive`
- 理由：
  - official final test 半数是 synthetic；
  - 只覆盖 `k=1` 与 `k=2`；
  - 没有 real adjudicated multi-intent benchmark 证据；
  - 没有强 baseline；
  - annotation quality 不可核验；
  - split isolation 在 atomic-source 语义下失败。

因此不能从当前结果推出：

- “真实低基数 tangled commit attribution 已被严格验证”
- “Kmax=4 边界已被真实评测支持”
- “可以无保留推进正式 Stage 2”

## H. Baseline Adequacy

代码与配置事实：

- `configs/mica/stage1_baseline_spec.json`
  - `baseline_status=dryrun_diagnostic_only`
- `code/mica/runners/run_stage1_baselines.py`
  - execute 路径仍直接 `RuntimeError`

official runtime 事实：

- `outputs/mica_stage1_official_validation_20260723T091744Z/official_run/stage1_official_validation_summary.json`
  - `baseline_count=0`
  - `baselines={}`

结论：

- 当前真正进入 official result 链的 baseline 只有 supplement 中的 `all-one`。
- `oracle-k baseline`：未正式执行
- `clustering baseline`：未正式执行
- `heuristic baseline`：未正式执行
- `no-relation baseline`：未正式执行
- `count-only baseline`：未正式执行

整体判断：

- baseline adequacy：`weak`

## I. Official Revision Chain

已存在并保留的记录：

- 原始 official result：
  - `configs/mica/official_results/stage1_official_validation_20260723T091921Z.json`
- supplemental metric：
  - `configs/mica/official_results/stage1_official_validation_20260723T091921Z_supplement_v1.json`
- latest status revision：
  - `configs/mica/official_results/stage1_official_validation_20260723T091921Z_status_revision_v1.json`

合法性结论：

- 原记录未被覆盖；
- supplement 只补回缺失 metric；
- 未重新推理；
- 未修改 gold；
- 未修改 threshold；
- 未修改 Kmax；
- 未修改 metric definition。

因此：

- official revision chain：`合法`

## J. Risk Register

### P0

- strict synthetic 原子来源跨 split 暴露；
- `official_final_test_unexposed` 在 atomic-source 语义下不成立；
- Kmax freeze 资产被 synthetic / replay / combined manifest 污染；
- approved Kmax packet 的 “exact-real only” 前提不成立；
- official final test 不是人工 adjudicated 的真实多意图 benchmark；
- official final test 无法支撑 `k>=3`、`Kmax=4` 和真实 tangled commit 泛化主张。

### P1

- 无正式强 baseline；
- anti-shortcut 只有基础设施，没有执行结果；
- 仅单 seed；
- official Stage 1 未正式验证 null/background 主贡献；
- repository concentration 仍然明显。

### P2

- `construction_group` 只是 recipe label，不是 family-level leakage key；
- provenance 文件保留 `intent_subjects` / `message` 元数据，虽未进入 canonical model input；
- 一些扩展指标已可只读重算，但未全部进入官方聚合记录。

## K. Stage 2 Entry Gates

- 数据 provenance 可验证：`pass`
- split leakage 为零：`fail`
- official final test 未暴露：`fail`
- 人工标签质量达到可接受水平：`unknown`
- blind audit 没有高比例重大标签错误：`unknown`
- 数据规模和分布足以支持当前主张：`fail`
- metric recomputation 与正式结果一致：`pass`
- 指标 CI 与分层表现可接受：`pass` for 当前窄 benchmark；`fail` for 广义论文主张
- acceptance criteria 全部通过：`pass`
- official result revision 合法：`pass`
- 没有严重 shortcut 风险：`unknown`
- 模型方案与协议一致：`partial`
- checkpoint 可复现：`pass`
- 没有 P0 validity issue：`fail`
- 论文主张被限制在证据支持范围内：`fail`

## L. Final Recommendation

- 最终结论：`NO_GO_STAGE2`

只允许进入的程度：

- 可以准备 Stage 2 修复计划；
- 不可以开始正式 Stage 2 calibration / training / evaluation。

必须先完成的动作：

1. 以 `source_atomic_commit_ids` 为一级 leakage key 重新冻结 strict synthetic train/dev/test 与 official final-test；
2. 用真正 `exact-real train/dev only` 的人工可审计资产重做 Kmax coverage freeze；
3. 建立可核验的 real multi-intent final benchmark，补足 `k>=3`、background-heavy、same-file multi-intent、hard single-intent 等 strata；
4. 正式执行至少一个强 baseline；
5. 补齐与 official final test 绑定的 annotation-quality / agreement / adjudication 证据；
6. 执行 anti-shortcut 审计并把结果纳入 Stage 1 validity gate。

当前不得宣称的论文结论：

- `official_final_test` 完全未暴露；
- `Kmax=4` 已被真实 exact-real train/dev 证据严格冻结；
- 当前 official result 已经证明真实低基数 tangled commit attribution 可泛化；
- 当前结果已经显著优于强 baseline；
- 可以无条件进入 Stage 2。

## Fresh Verification

- `python3 -m py_compile code/mica/**/*.py(.N)`：通过
- `pytest -q tests/mica`：`552 passed`
- `pytest -q tests/generation`：`67 passed`

## 审计边界

本次审计：

- 未执行 Stage 2；
- 未修改 Stage 1 模型、阈值、Kmax、tau、final-test split；
- 未重新生成 official predictions；
- 未覆盖 official result；
- 未提交或修改 `outputs/**` runtime 产物；
- 未触碰无关 `continuous_m_crawl.launchd.log`。
