# Stage1-v2 Background Annotation Guideline

状态：`pilot` + `not_final_frozen`（2026-07-26 随 pilot_v2 修订补充第 6 节）

本指南只定义 background 标注，不自动生成任何 gold。

## 1. Background 的定义

`background` 指对当前 commit 的主要开发意图不构成独立 semantic goal 的 edit unit，常见于：

- formatting
- import sorting
- lockfile
- generated artifacts
- vendor sync
- mechanical snapshot

## 2. 不允许的捷径

- 不得仅凭文件扩展名就判定为 background。
- 不得仅凭 file role 就判定为 background。
- 不得把“模型不确定”视为 background。

## 3. 标注原则

- 若 config 改动是某个 feature / fix 的必要组成部分，则优先归到该 foreground intent，而不是 background。
- 若 test 改动直接验证某个 source change，则优先归到该 foreground intent。
- 若 lockfile、generated、snapshot 只是随其他语义改动机械变化，标为 background。
- 若一个 unit 既有 semantic change 又有 formatting，应按 semantic 主导处理；不要因为混入空格或 import 顺序就改成 background。

## 4. 需要特别记录的类型

每条 background 记录至少注明一种 `background_reason` 候选：

- `formatting`
- `import_sorting`
- `lockfile`
- `generated`
- `vendor`
- `mechanical_snapshot`
- `other_mechanical`

## 5. 与 foreground 的边界

- foreground/background 不得重叠。
- `shared_support`、`mixed`、`uncertain` 默认不是 background。
- 若无法确定是否为 background，应优先标 `uncertain` 并备注。

## 6. Unit 级判定、禁止文件级继承 [pilot_v2 R9]

- background/foreground 的判断只看 unit 自身内容。
- formatting-only、空白-only unit 即使位于某 foreground intent 的"主战场"文件内，也默认 `background`。
- 禁止因"该文件属于 intent X"而把机械 unit 吸入 X（文件级主题继承）。
- 上游 unitization 应尽量避免切出纯空白 unit；已存在的纯空白 unit 一律 `background(formatting)`。
