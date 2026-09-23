# Stage1-v2 Count Guideline Pilot v2

状态：`pilot` + `not_final_frozen`
版本串：`stage1-v2-count-guideline-pilot-v2`
取代：`stage1-v2-count-guideline-pilot-v1`
修订依据：calibration round 1 分歧裁决与 `STAGE1_V2_GUIDELINE_PILOT_V2_REVISION_DRAFT.md`。新增规则以 **[R#]** 标记。

本指南用于 RealCount-TrainDev 的 exact-count 标注。目标是给出可靠的 `exact_k`，而不是完整 partition。

## 1. 目标

对每个真实 commit 给出：

- `exact_k`
- 必要备注
- 是否疑似 out-of-scope / overflow

## 2. 基本规则

- `exact_k` 统计的是独立开发意图数量，不是文件数、hunk 数或函数数。
- supporting test / supporting docs / required config 默认不额外计数。
- formatting、lockfile、generated、vendor、snapshot 默认不计入独立 intent。
- 若一个 commit 本质上是 release aggregation、mass refactor 或超大复杂提交，应保留 exact count 判断，同时可加 `overflow_candidate=true` 备注。

### 2.1 计数判定检验链 [R3-R8]

对每个候选 intent 依次应用（与 alignment guideline pilot_v2 完全一致）：

1. **反伞形规则 [R3]**：以"action + object"划界，不以最终目标划界；"为 X 所需的一切"必须拆分计数。
2. **行为保持检验 [R4]**："重构"若内嵌行为改变则并入对应 fix，不另计数；行为保持且可独立交付才 `k+1`。
3. **Enabler 双问 [R5]**：(a) 不做 X 新功能是否仍可工作？(b) X 单独提交是否有独立价值？皆"是"才 `k+1`。
4. **机制级拆分 [R6]**：同一 issue 下多个独立机制修复分别计数；issue 编号不作为合并依据。
5. **可见证据合并 [R7]**：仅主题相近不合并；按 diff 内可见依据（依赖、注释、共享 helper、门控作用域）合并。
6. **反事实 config 检验 [R8]**：没有该 feature 时 config 改动是否仍会发生？是 → `k+1`，否 → 不计数。

## 3. 典型边界

- source + supporting test：
  - 通常 `k` 不增加；test 依附于它所**验证**的组件（target object），而非它调用的 API [R10]。
- bug fix + independent refactor：
  - 先过行为保持检验 [R4]；可独立交付的行为保持重构 `k + 1`。
- code + synchronized local docs：
  - 通常不额外计数。
- code + independent documentation work：
  - 通常额外计数。
- 依赖清单改动（使用点不在 diff 内）：
  - 不独立计数、也不并入猜测的 intent；备注 `uncertain_dependency` [R11]。

## 4. Kmax 临时操作规则 [R13]

正式 Kmax 依赖本 RealCount 资产产出，当前未冻结数值。
冻结前：`exact_k` 照实标注，不设上限截断；`k > 6` 时附加 `overflow_candidate=true` 备注。
该临时规则不构成 Kmax 预设。

## 5. 禁止来源

以下内容不得作为 exact-count gold：

- synthetic 样本
- censored `k>=2`
- pseudo exact count
- commit-message-derived count
- 未双标且未裁决的冲突记录
