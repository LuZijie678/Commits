# Derived Datasets

这里放跨阶段正式交付层，而不是临时试跑输出。

## 当前目录

- `step1_runs/`: 保留关键 Step1 正式运行快照
- `step1_source_pool/current/`: 当前稳定单意图交付层
- `step2_bridge/current/`: Step1 -> Step2 当前桥接层

## 当前推荐主路径

```text
Step1 formal run
  -> step1_source_pool/current/conservative_atomic_sources.csv
  -> step2_bridge/current/step2_source_candidates_from_step1.csv
  -> Step2 main pipeline
```

## 当前事实

- `conservative_atomic_sources.csv = 2712` 条
- `step2_source_candidates_from_step1.csv = 2712` 条

JSON 和 manifest 是这里的权威说明文件；自动生成的 Markdown 摘要已尽量清理，避免和主文档重复。
