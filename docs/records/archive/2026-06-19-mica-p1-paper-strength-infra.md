> 状态：已归档 / 过时
> 本文档是历史实现说明，可能不反映当前代码状态。
> 当前事实来源：docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md

# 2026-06-19 MICA P1 论文级基础设施

## 范围

本轮把 MICA-v3 代码库从 staged skeleton 扩展到更接近论文配套基础设施的层面，主要支持：

- real alignment benchmark preparation
- paper main-table builders
- anti-shortcut rerun planning
- OOD stress slice aggregation
- stronger lightweight baseline coverage
- experiment provenance and manifest versioning
- renderer evidence-lock diagnostics

## 本轮新增

### 真实 Alignment Benchmark 基础设施

- annotation schema normalization and validation
- annotator agreement metrics
- adjudication item builder
- split readiness / requirement gate
- benchmark guideline document

### 论文主表构建器

- real-domain table writer
- alignment table writer
- message-utility table writer
- ablation table writer
- shortcut/OOD table writer

### Anti-shortcut / OOD

- experiment-plan builder
- masked dataset builder
- rerun request manifest builder
- shortcut sensitivity delta summary
- OOD slice manifest / aggregation / report builder

### Baseline 扩展

- metadata TF-IDF style classifier
- graph clustering baseline
- oracle-k clustering baseline
- deterministic direct-generation baseline contract
- LLM prompting contract
- pretrained classifier placeholder contract

### 可复现性 / Provenance

- experiment manifest versioning
- manifest hashing
- git provenance capture
- asset provenance capture
- seed control
- unified experiment report schema

### Renderer 证据锁定

- evidence term extraction
- entity copy rate
- unsupported claim flags
- message grounding check

## 非执行确认

本轮仍然没有运行：

- Stage 1 validation
- Stage 2 / Stage 3 / Stage 4 training
- final evaluation
- anti-shortcut model rerun
- OOD model rerun

本轮没有有意创建或修改仓库中的 `outputs/**` 产物。
