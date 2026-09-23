# M Verified Dataset

这是 Step2 few-shot 正式 `M` 类来源资产目录。

## 正式层

- `canonical/usable_m_with_real_diff.csv`
- `canonical/usable_m_with_real_diff.jsonl`
- `manifest/usable_m_with_real_diff_manifest.json`

## 当前事实

- 行数：`773`
- repo 数：`341`
- 标签：全部 `M`
- 用途：Step2 few-shot verified multi-intent 正式来源

## 使用口径

- 可以作为 Step2 few-shot 候选来源
- 不能跳过 `repo/SHA` 泄露审计
- 不能跳过 subject 风格审计
- 不能跳过 common signature 覆盖审计
- 不能跳过 few-shot formal gate

## 当前状态

- 当前 canonical 数据已在本地实体化
- 本轮历史 `round_runs` 有效数据已完成正式吸收与归档
- 旧 `workspace/` 已整体迁到 `../../archive/datasets/m_verified/workspace/`

## 需要追溯时看哪里

- 正式数据定义：`manifest/usable_m_with_real_diff_manifest.json`
- 历史吸收过程：`manifest/*.json`
- 工作区历史归档：`../../archive/datasets/m_verified/workspace/`
