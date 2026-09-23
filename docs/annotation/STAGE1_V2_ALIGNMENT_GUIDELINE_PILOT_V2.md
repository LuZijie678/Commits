# Stage1-v2 Alignment Guideline Pilot v2

状态：`pilot` + `not_final_frozen`
版本串：`stage1-v2-alignment-guideline-pilot-v2`
取代：`stage1-v2-alignment-guideline-pilot-v1`
修订依据：calibration round 1 分歧裁决（`datasets/mica/stage1_v2/real_alignment/calibration_round_1_adjudicated.jsonl`）与修订草案（`STAGE1_V2_GUIDELINE_PILOT_V2_REVISION_DRAFT.md`）。新增规则以 **[R#]** 标记草案条目编号。

本指南用于 Stage1-v2 Real-Adjudicated pilot 的双标与裁决。它不是最终 frozen guideline，在 pilot agreement 复盘前仍可修订。

2026-07-26 R2 status：Calibration Round 2 integrity audit 返回 `r2_annotation_incomplete`。因此 pilot v2 未被批准为 final frozen guideline；当前 guideline decision 为 `blocked_by_incomplete_annotation`。R2 必须重新导出 / 重新导入具备独立 actor/context/audit provenance 的 A/B 结果后，才能重新计算 pre-adjudication agreement。

## 1. 标注目标

对每个真实 commit 的 edit units 做三层判断：

1. `exact_k`
   - 该 commit 中有多少个开发意图。
2. unit-level assignment
   - 每个 edit unit 属于：
     - `foreground(intent_id)`
     - `background`
     - `shared_support`
     - `uncertain`
     - `mixed`
3. intent fields
   - 每个 foreground intent 至少填写：
     - `action`
     - `object`
     - `optional scope`

### 1.1 Intent 文本规范 [R1]

- `action` 必须取自受控动词表：
  `add | fix | rewrite | refactor | remove | harden | optimize | document | configure | test`
- 动词选用以 **diff 内可见证据** 为准：
  - 改动改变了可观察行为 → `fix`（修正缺陷）或 `rewrite`（重写行为）；
  - 改动保持行为、只调整结构 → `refactor`；
  - 不得凭主观推断动机选择动词。
- `object` 用组件/符号级描述（如 `TokenValidator.check_expiry`、`gauge example demo loop`），
  不得用文件路径或"the code"这类泛化描述。
- Intent 文本仅用于可读性与裁决沟通；agreement 只按 unit partition 计算，
  语义等价的不同表述不构成分歧。

### 1.2 mixed 必须枚举成分 [R2]

`mixed` 标签必须携带成分列表：

```json
{"label": "mixed", "component_intent_ids": ["intent_1", "intent_2"]}
```

禁止裸 `mixed`。若成分中含背景性内容，用 `"component_intent_ids": ["intent_1", "__background__"]`。

## 2. 不允许看到的信息

标注时不得查看：

- 模型预测
- 原始 commit message
- PR title
- issue text
- split 名称
- 另一位标注者结果

允许查看：

- normalized diff
- edit-unit 切分
- hunk ID
- file path
- enclosing symbol
- 必要且受限的代码上下文

## 3. 基本判定原则

- 一个 intent 的核心标准不是"文本相似"，而是"是否服务于同一个开发动作与目标对象"。
- supporting test、必要 config、同步文档，只有在它们明显依附某个 semantic source change 时，才和该 semantic intent 合并。
- formatting、lockfile、generated、vendor、snapshot 等机械性修改默认不是 foreground intent。
- 如果一个 unit 同时支撑多个 intent 且无法唯一主分配，标为 `shared_support`。
- 如果一个 unit 同时混合多个独立语义且无法合理拆开，标为 `mixed`（按 1.2 枚举成分）。
- 如果证据不足以稳定决定，标为 `uncertain`。

### 3.1 反伞形 intent 规则 [R3]

Intent 以"开发动作 + 目标对象"划界，**禁止以最终目标划界**。
"为了让 wasm CI 通过所做的一切"不是一个 intent；其中每个可独立交付的语义改动
（加依赖、改接口、修测试基建）各自成 intent。
判据：把候选 intent 表述成"action + object"；若表述必须借助最终目标才能成立
（"为 X 所需的改动"），则它是伞形描述，必须继续拆分。

### 3.2 行为保持检验 [R4]

判定"bug fix + refactor"是否拆分前，先做行为保持检验：

- 所谓"重构"若内嵌了 fix 所需的行为改变（如条件、状态更新时机变化），**必须与该 fix 合并**；
- 行为保持、且可独立交付的结构调整，才允许拆成独立 `refactor` intent。

### 3.3 Enabler 双问检验 [R5]

改动 X 既改善既有行为、又便利同 commit 的新功能 F 时：

1. 不做 X，F 是否仍可工作？
2. X 单独提交是否有独立价值？

两问皆"是" → 拆分；任一为"否" → 合并入 F。

### 3.4 机制级拆分原则 [R6]

多个可独立交付的**机制**修复，即使服务同一 issue/症状，也应分列为多个 intent。
diff 中出现的 issue 编号只写入备注，不得作为合并依据。

### 3.5 可见证据合并原则 [R7]

Intent 归并必须基于 diff 内可见依据：注释、代码依赖、共享 helper、条件门控作用域。
仅"主题相近"（同一类 sweep、同类硬化散布多处）不足以合并；
动机在 diff 内不可见时，按可见证据保守归类（按对象拆分），不做主题推断。

### 3.6 条件门控证据 [R12]

Feature flag / 条件编译（`#[cfg]`、`ifeq` 等）的作用域是 unit 归属的有效证据：
被同一门控包裹的改动优先归入该门控对应的 intent；
门控之外的"顺带清理"不得因文件相邻被吸入。

## 4. 典型边界案例

### 4.1 source change + supporting test

- merge example：
  - 修改 `src/auth.py` 的 token 校验逻辑，同时更新对应 `tests/test_auth.py` 断言。
  - 标为同一个 foreground intent。
- split example：
  - 修改 `src/auth.py` 的 token 逻辑，同时在 `tests/infra/fixture_loader.py` 做独立测试基础设施维护。
  - 若测试基础设施改动可独立存在，拆成两个 intent。
- **test target object 规则 [R10]**：
  新测试依附于它**所验证的组件**（target object），而非它调用的 API。
  测试使用了本 commit 新增的工具函数、但验证的是另一个组件的行为时，
  归属以被验证组件的 source change 为准；若该组件未在本 commit 修改，则测试自成 intent。

### 4.2 feature + required config

- merge example：
  - 新增 feature flag，同时修改对应配置键启用该功能。
  - 配置改动直接依附 feature，合并。
- split example：
  - 同一 commit 同时做功能开发和独立的 config cleanup / rename。
  - 若 config 维护不依附该 feature，拆开。
- **反事实 config 检验 [R8]**：
  问"若没有该 feature，此 config 改动是否仍会发生/仍有意义？"
  答"是" → 独立 intent；答"否" → 并入 feature。
  CI 集成中超出功能最小必需的顺带优化（如改既有 job 触发条件）按同一检验判定。
- **riding-along 微清理 [R8]**：
  typo/glob 修正等微清理默认并入其所在编辑动作所属的 intent，并在备注注明。

### 4.3 bug fix + refactor

- merge example：
  - 为修复 bug 重排几行局部结构、提取局部 helper，但仍服务于同一个 bug fix。
  - 合并。
- split example：
  - 一部分是修复 bug，另一部分是对无关模块做独立重构或命名清理。
  - 拆开。
- 拆分与否先过 3.2 行为保持检验。

### 4.4 code + docs

- merge example：
  - 修改 API 行为，同时同步本地 API docs 中对应参数说明。
  - docs 作为 supporting change，合并。
- split example：
  - 同时进行独立文档重写、教程补充或多页面说明整理。
  - 若 docs 可独立交付，拆开。

### 4.5 dependency update + lockfile

- background example：
  - 仅 lockfile 变化或 lockfile 跟随依赖版本 bump 的机械更新。
  - lockfile 默认 `background`。
- split example：
  - commit 中既有独立依赖升级，又有另一个无关语义改动。
  - 依赖升级 intent 与其他语义 intent 拆开；lockfile 仍不是独立 foreground。
- **依赖清单 unit 规则 [R11]**：
  Cargo.toml / package.json 新增依赖、而其使用点不在本 diff 内时，
  该 unit 标 `uncertain` 并在备注列出候选 intent；不得凭共现猜测归属。
  使用点在 diff 内时，归入使用它的 intent。

### 4.6 same-file multiple intents

- split example：
  - 同一文件里一处修 bug，另一处改配置键命名或加日志辅助。
  - 若 action/object 明显不同，拆开。
- uncertain example：
  - 同一函数内多处改动，但边界严重交织，无法稳定拆分。
  - 可标 `uncertain` 或 `mixed`（枚举成分），并在备注说明原因。

### 4.7 大型 restructure 中的机械后果 vs 独立语义 [R18-gap]

纯搬移/重命名（内容不变、位置变）是 restructure intent 的机械后果，不另立 intent；
搬移过程中发生的**行为改变**（如移除 feature-gate、改默认值）是独立语义，
必须从 restructure 中拆出。判据仍是 3.2 行为保持检验，逐 unit 应用。

## 5. background / shared / mixed / uncertain

- `background`
  - 纯 formatting
  - import sorting
  - lockfile
  - generated artifacts
  - vendor sync
  - mechanical snapshot
- `shared_support`
  - 同一 test 或 docs 单元同时支撑两个 intent，且无法唯一主分配。
- `mixed`
  - 同一 edit unit 内同时包含多个独立语义，拆不开；必须枚举 `component_intent_ids`（1.2）。
- `uncertain`
  - 信息不足、语义边界高度模糊，不能强行定案。

### 5.1 Unit 级判定、禁止文件级继承 [R9]

归属判断只看 unit 自身内容。
formatting-only / 空白-only unit 即使位于某 intent 的"主战场"文件内，也默认 `background`；
**禁止**因"该文件属于 intent X"而把机械 unit 吸入 X。
`shared_support` 与 `mixed` 的区分：unit **支撑**多个 intent（自身无独立语义）→ `shared_support`；
unit **包含**多个 intent 的实质改动 → `mixed`。

## 6. out-of-scope 与 overflow 候选

以下情况可建议 `out_of_scope` 或 `overflow` 候选：

- `k > Kmax`
- release aggregation
- mass refactor
- generated/vendor sync 主导
- 纯机械大提交

这类样本仍保留在候选池中，但不应硬塞入普通 foreground intent gold。

### 6.1 Kmax 临时操作规则 [R13]

Stage1-v2 的正式 Kmax 依赖 RealCount 标注产出，当前**尚未冻结数值**。
在 Kmax 冻结前的临时规则：`exact_k` 照实标注；当 `k > 6` 时附加
`overflow_candidate=true` 备注，不强行合并意图去压低 k。
该临时规则不构成 Kmax 预设，仅为标注操作一致性。

## 7. 裁决要求

若 A/B 结果冲突，裁决人必须记录：

- 采用的 guideline version
- 冲突点
- 裁决后的 `exact_k`
- unit 级主要调整
- 裁决理由

裁决结果不得覆盖 raw A/B。
