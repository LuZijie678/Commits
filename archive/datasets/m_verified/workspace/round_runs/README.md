# Round Runs Workspace

这里保留未来尚未被正式吸收到 canonical `M` 层的数据轮次文件。

## 当前状态

- 当前历史 `round_runs` 已完成有效数据吸收检查
- 当前这批历史轮次已完成“正式吸收 -> 归档”闭环
- 现在这个目录主要保留流程说明，等待新的未吸收轮次进入

## 规则

- 未确认吸收前，轮次文件保留在 `workspace/`
- 只有确认有效数据已吸收到正式层后，才迁入 `archive/crawl_rounds/`
- 若严格证明为空轮次或无有效产出，可直接归档，但不删除结论证据

## 追溯

具体吸收证据以 `datasets/m_verified/manifest/*.json` 为准。
