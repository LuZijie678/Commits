# Hard-B Dataset

这是当前仓库中的 `hard-B` 正式数据资产目录。

## 正式层

- `canonical/usable_hard_b_with_real_diff.csv`
- `canonical/usable_hard_b_with_real_diff.jsonl`
- `manifest/usable_hard_b_with_real_diff_manifest.json`

## 本机状态

当前工作区中的 `canonical/usable_hard_b_with_real_diff.csv` 仍是 Git LFS 指针，尚未在本机物化为可直接统计的正式 CSV。

这意味着：

- 不能把当前本机直接 `wc -l` 得到的结果当作正式规模
- 如果要做本机行数、repo 数或内容检查，必须先完成 LFS 实体化
- 本文不把历史统计数字写成本机现状，避免误导

## 角色

`hard-B` 的当前协议角色是：

- 边界样本
- 难负例
- 再复核资产

它不直接进入 Step2 few-shot 正例池。

## 工作区状态

- 历史 `workspace/` 已迁到 `../../archive/datasets/hard_b/workspace/`
- 当前 live 目录只保留 canonical / manifest / review / tooling

## 使用口径

- 用于边界分析、再复核和负例控制
- 不要把它当作 verified multi-intent few-shot 正例来源
- 需要追溯时优先读取 `manifest/usable_hard_b_with_real_diff_manifest.json`
- 需要在本机实际使用前，先确认 canonical 文件已完成 LFS 物化
