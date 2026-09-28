# Commits

这是当前唯一主仓，用来统一管理 Step1 单意图原料挖掘与 Step2 多意图合成。

项目当前状态与历史证据边界请先看 `docs/CURRENT_STATUS.md`；
MICA Stage1-v2 的执行细节见 `docs/MICA_STAGE1_V2_DATA_AND_ANNOTATION_EXECUTION.md`；
本次补充的历史实验文件及其局限见 `docs/EXPERIMENT_ARTIFACT_RECOVERY.md`。
大文件的本机补回、哈希及公开归档条件见 `docs/LOCAL_EXPERIMENT_ARTIFACT_RECOVERY.md`。
`docs/current-experiment-checkpoint.md` 已标记为过时，仅供查阅历史。

## 当前结论

- Step1 当前推荐交付物是 `datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv`。
  - 当前规模：`5099` 条
  - 来源策略：`model_rule_refilter`
  - 当前正式人工审计：`288/300 = 0.9600`
- Step2 当前默认 few-shot 资产是 `datasets/step2/delivery/current/fewshot_pool.db`。
  - 当前规模：`130` 条 train few-shot
  - 当前状态：`audit_pass=true`、`retrieval_probe_ok=true`
- 当前推荐主路径是：

```text
Step1 conservative_atomic_sources.csv
  -> Step2 bridge
  -> step2_source_candidates_from_step1.csv
  -> Step2 preflight / generation
```

## 三种读法

- 只想快速了解 MICA 当前口径：先看 `docs/MICA_IMPLEMENTATION_INDEX.md` 和 `docs/MICA_STAGE1_V2_DATA_AND_ANNOTATION_EXECUTION.md`
- 只想知道正式输入、输出与本地资产如何登记：看 `docs/MICA_DATA_ASSET_REGISTRY.md` 和 `docs/EXPERIMENT_ARTIFACT_RECOVERY.md`
- 只想直接运行：看 `code/step1/README.md` 和 `code/step2/README.md`

如果要引用“真实事实”而不是摘要表述，优先读这些文件本身：

- Step1 当前交付层：`datasets/derived/step1_source_pool/current/*.json`、`*.csv`
- Step2 当前 few-shot 交付层：`datasets/step2/delivery/current/*.json`
- 当前桥接层：`datasets/derived/step2_bridge/current/*`

## 仓库结构

- `code/step1/`: Step1 代码与局部运行脚本
- `code/step2/`: Step2 代码、配置与生成脚本
- `datasets/step1/`: Step1 正式数据根
- `datasets/step2/`: Step2 正式 few-shot 数据根
- `datasets/m_verified/`: Step2 few-shot 的正式 `M` 类来源资产
- `datasets/hard_b/`: 边界样本 / 难负例资产
- `datasets/derived/`: 跨阶段正式交付层
- `docs/`: 当前有效的项目说明与实验记录
- `archive/`: 历史运行产物、旧布局和归档数据

补充：

- `datasets/m_verified/` 当前在本机已物化，可直接读取正式 `M` 数据
- `datasets/hard_b/` 是否可直接读取，以该目录 README 的“本机状态”说明为准

## 推荐运行顺序

1. Step1

```bash
make step1-run
```

2. Step1 -> Step2 桥接

```bash
make step2-bridge
```

3. 准备 Step2 本地配置

```bash
cp code/step2/configs/step2_runtime_config.json \
   code/step2/configs/step2_runtime_config.local.json
```

然后在 `code/step2/configs/step2_runtime_config.local.json` 中填写 `deepseek_api_key`。

4. Step2 预检

```bash
make step2-preflight
# 如需真实接口连通性检查：
make step2-preflight STEP2_PREFLIGHT_ARGS="--preflight-api-ping"
```

`make step2-preflight` 会在本地覆盖配置存在时自动优先使用 `configs/step2_runtime_config.local.json`。

5. Step2 本地调试或真实生成

```bash
make step2-mock
# 或按 Step2 配置跑真实 API 路径
```

## 常用入口

### Step1

```bash
cd code/step1
python3 -m src.pipeline.run_step1 --help
```

### Step2

```bash
cd code/step2
python3 code/construct_simple_two_intent.py \
  --preflight \
  --output-dir ../../datasets/step2/delivery/current \
  --config configs/step2_runtime_config.local.json
```

### Step2 few-shot 资产更新

```bash
make step2-fewshot-prepare
make step2-fewshot-report
make step2-fewshot-materialize
```

## 文档入口（含历史记录）

- `docs/CURRENT_STATUS.md`: 当前状态入口与历史证据边界
- `docs/MICA_IMPLEMENTATION_INDEX.md`: MICA 实现与文档索引
- `docs/MICA_STAGE1_V2_DATA_AND_ANNOTATION_EXECUTION.md`: Stage1-v2 当前执行状态
- `docs/MICA_STAGE1_INDEPENDENT_AUDIT.md`: Stage1-v1 独立审计结论
- `docs/EXPERIMENT_ARTIFACT_RECOVERY.md`: 本次补充的历史实验文件、校验与未上传项
- `docs/LOCAL_EXPERIMENT_ARTIFACT_RECOVERY.md`: 六份大型实验文件的本机补回与未找回原件
- `docs/STAGE1_OFFICIAL_MANIFEST_HASH_AUDIT.md`: 官方 manifest 哈希差异的只读核查
- `docs/records/2026-05-27-current-project-state.md`: 2026 年 5 月的历史状态记录
- `code/step1/docs/2026-05-26-step1-正式结果记录.md`: Step1 正式结果记录
- `code/step1/README.md`: Step1 当前入口说明
- `code/step2/README.md`: Step2 当前入口说明

## 重要约束

- Step1 的目标是高精度单意图原料挖掘，不是证明模型一定全面优于规则。
- `message-only proxy` 只作召回前置粗筛，不作最终高置信过滤器。
- Step2 默认优先消费 Step1 新格式 `conservative_atomic_sources.csv`，旧格式只保留兼容路径。
- 历史预览源和旧目录布局都已归档，不再作为默认实验入口。
