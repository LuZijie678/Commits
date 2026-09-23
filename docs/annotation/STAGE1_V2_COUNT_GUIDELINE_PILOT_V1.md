# Stage1-v2 Count Guideline Pilot v1

状态：`pilot` + `not_final_frozen`

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
- 若一个 commit 本质上是 release aggregation、mass refactor 或 `k > Kmax` 的复杂提交，应保留 exact count 判断，同时可加 `overflow_candidate=true` 备注。

## 3. 典型边界

- source + supporting test：
  - 通常 `k` 不增加。
- bug fix + independent refactor：
  - 若 refactor 可独立交付，则 `k + 1`。
- code + synchronized local docs：
  - 通常不额外计数。
- code + independent documentation work：
  - 通常额外计数。

## 4. 禁止来源

以下内容不得作为 exact-count gold：

- synthetic 样本
- censored `k>=2`
- pseudo exact count
- commit-message-derived count
- 未双标且未裁决的冲突记录
