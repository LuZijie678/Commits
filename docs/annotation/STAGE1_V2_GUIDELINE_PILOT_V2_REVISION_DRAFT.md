# Stage1-v2 Guideline pilot_v2 修订草案（DRAFT，待负责人批准）

状态：`draft_pending_owner_approval`
来源：calibration round 1（LLM 轨道，stage1-v2-llm-annotation-amendment-v1）的 15 条分歧裁决
证据：`datasets/mica/stage1_v2/real_alignment/calibration_round_1_adjudicated.jsonl`（逐条 guideline_gap_note）
触发原因：agreement gates 未通过（split_no_split_kappa=0.664 < 0.80；pairwise_unit_agreement=0.750 < 0.80）→ `guideline_status=revision_required`

按协议，本草案批准并冻结为 pilot_v2 后，需执行 calibration round 2；round 2 通过 gates 才能进入 pilot 批次标注。

## A. 过程性修订（消除伪分歧，不改变标注语义）

1. **Intent 文本规范化规则**（源：0003/0007/0012/0025）
   - 增加受控 action 动词表（add / fix / rewrite / refactor / remove / harden / optimize / document / configure / test）及选用判据：以 diff 内可见证据为准（行为改变→fix/rewrite，行为保持→refactor）。
   - object 具体度标准：组件/符号级，不用文件路径级或泛化描述。
   - agreement 计算按 partition 比较（已是事实），intent 文本差异不构成分歧；文本仅用于下游可读性。

2. **mixed 标签必须枚举成分 intents**（源：0013/0018）
   - `{"label":"mixed","component_intent_ids":["intent_1","intent_2"]}`，禁止裸 mixed。

## B. 实质性规则修订（针对 split/no-split 与 merge/split 分歧）

3. **反伞形 intent 规则**（源：0011）：intent 以"开发动作+对象"划界，禁止以最终目标（如"让 CI 通过"）吞并可独立交付的语义改动。
4. **行为保持检验**（源：0006）：所谓"重构"若内嵌了 fix 所需的行为改变，必须与该 fix 合并；行为保持且可独立交付才允许拆分。
5. **Enabler 双问检验**（源：0013）：改动 X 既改善既有行为又便利新功能 F 时——(a) 不做 X，F 是否仍可工作？(b) X 单独提交是否有独立价值？两者皆"是"→拆分，否则合并。
6. **机制级拆分原则**（源：0021）：多个可独立交付的机制修复即使服务同一 issue/症状也应分列；issue 关联写备注，不作为合并依据。
7. **可见证据合并原则**（源：0016）：intent 归并必须基于 diff 内可见依据（注释、代码依赖、共享 helper）；仅主题相近（同类 sweep）不足以合并；动机不可见时按可见证据保守归类。
8. **反事实 config 检验**（源：0028）：CI/config 改动若在"没有该 feature 时仍会发生/仍有意义"则独立成 intent，否则并入该 feature；riding-along 微清理默认并入所在编辑动作所属 intent 并备注。

## C. Unit 归属规则修订

9. **Unit 级判定、禁止文件级继承**（源：0005/0029）：formatting-only unit 即使位于某 intent 的主战场文件内也默认 background；归属判断只看 unit 自身内容。
10. **Supporting test 的目标对象规则**（源：0020）：测试依附于它所验证的 source change（target object），而非它调用的 API/工具函数。
11. **依赖清单 unit 规则**（源：0011）：Cargo.toml/package.json 加依赖而使用点不在 diff 内时，标 `uncertain` 并备注候选 intent，不猜测归属。
12. **条件门控证据**（源：0005）：feature flag/条件编译作用域是 unit 归属的有效证据，应显式列入证据类型。

## D. 协议参数缺口

13. **Kmax 数值未定义**（源：0011）：两份 guideline 引用 Kmax 但从未给出数值（Stage1-v1 的 Kmax=4 已被审计作废，Stage1-v2 的 Kmax 依赖 RealCount 标注产出）。calibration round 2 前需给出临时操作规则：k>6 时标 `overflow_candidate` 并备注，不强行合并。

## 预期影响

- A/B 分歧集中于 split/no-split（5 条）与高 k 粒度（3 条）；规则 3-8 直接针对这些根因。
- 过程性规则 1-2 预计消除 4 条伪分歧（pairwise 误报）。
- 修订后需 calibration round 2（新抽 30 条）验证 gates；round 1 样本不复用、不入 benchmark。
