# Stage1-v2 Alignment Guideline Pilot v1

状态：`pilot` + `not_final_frozen`

本指南用于 Stage1-v2 Real-Adjudicated pilot 的双标与裁决。它不是最终 frozen guideline，在 pilot agreement 复盘前仍可修订。

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

- 一个 intent 的核心标准不是“文本相似”，而是“是否服务于同一个开发动作与目标对象”。
- supporting test、必要 config、同步文档，只有在它们明显依附某个 semantic source change 时，才和该 semantic intent 合并。
- formatting、lockfile、generated、vendor、snapshot 等机械性修改默认不是 foreground intent。
- 如果一个 unit 同时支撑多个 intent 且无法唯一主分配，标为 `shared_support`。
- 如果一个 unit 同时混合多个独立语义且无法合理拆开，标为 `mixed`。
- 如果证据不足以稳定决定，标为 `uncertain`。

## 4. 典型边界案例

### 4.1 source change + supporting test

- merge example：
  - 修改 `src/auth.py` 的 token 校验逻辑，同时更新对应 `tests/test_auth.py` 断言。
  - 标为同一个 foreground intent。
- split example：
  - 修改 `src/auth.py` 的 token 逻辑，同时在 `tests/infra/fixture_loader.py` 做独立测试基础设施维护。
  - 若测试基础设施改动可独立存在，拆成两个 intent。

### 4.2 feature + required config

- merge example：
  - 新增 feature flag，同时修改对应配置键启用该功能。
  - 配置改动直接依附 feature，合并。
- split example：
  - 同一 commit 同时做功能开发和独立的 config cleanup / rename。
  - 若 config 维护不依附该 feature，拆开。

### 4.3 bug fix + refactor

- merge example：
  - 为修复 bug 重排几行局部结构、提取局部 helper，但仍服务于同一个 bug fix。
  - 合并。
- split example：
  - 一部分是修复 bug，另一部分是对无关模块做独立重构或命名清理。
  - 拆开。

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

### 4.6 same-file multiple intents

- split example：
  - 同一文件里一处修 bug，另一处改配置键命名或加日志辅助。
  - 若 action/object 明显不同，拆开。
- uncertain example：
  - 同一函数内多处改动，但边界严重交织，无法稳定拆分。
  - 可标 `uncertain` 或 `mixed`，并在备注说明原因。

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
  - 同一 edit unit 内同时包含多个独立语义，拆不开。
- `uncertain`
  - 信息不足、语义边界高度模糊，不能强行定案。

## 6. out-of-scope 与 overflow 候选

以下情况可建议 `out_of_scope` 或 `overflow` 候选：

- `k > Kmax`
- release aggregation
- mass refactor
- generated/vendor sync 主导
- 纯机械大提交

这类样本仍保留在候选池中，但不应硬塞入普通 foreground intent gold。

## 7. 裁决要求

若 A/B 结果冲突，裁决人必须记录：

- 采用的 guideline version
- 冲突点
- 裁决后的 `exact_k`
- unit 级主要调整
- 裁决理由

裁决结果不得覆盖 raw A/B。
