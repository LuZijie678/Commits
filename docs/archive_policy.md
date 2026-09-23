> 状态：过时
> 本文档是历史实现说明，可能不反映当前代码状态。
> 当前事实来源：docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md

# 归档策略

## 原则

- 当前主入口只保留仍在使用的代码、数据和文档。
- 历史试跑、旧布局和旧预览源统一进入 `archive/`。
- 只有在确认有效内容已经被当前主链路吸收后，历史轮次才进入归档。
- 对空轮次可以直接归档，但不要删除判断依据。

## 当前约定

- `archive/runs/`：历史 Step1 / Step2 运行产物
- `archive/legacy_layout/`：旧目录布局和旧入口
- `archive/crawl_rounds/`：已吸收完成的 crawl 历史轮次
- `archive/datasets/*/workspace/`：已退出当前主链路的历史工作区数据
- `datasets/step1/runtime_support/`：当前 Step1 正式运行支撑件，不再视为工作区

## 解释优先级

如果历史说明和当前主文档冲突，以以下内容为准：

1. 根目录 `README.md`
2. `docs/MICA_IMPLEMENTATION_INDEX.md`
3. `docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md`
4. 当前代码与配置
