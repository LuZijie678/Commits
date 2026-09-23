# Formal Preflight 最后检查清单

更新时间：2026-05-27

## 1. 当前状态

当前默认 Step2 入口已经满足 few-shot formal-ready 的基础条件：

- 默认 source：`../../datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv`
- 默认 few-shot DB：`../../datasets/step2/delivery/current/fewshot_pool.db`
- 默认 few-shot manifest：`../../datasets/step2/delivery/current/build_manifest.json`
- 当前 few-shot 规模：`130`
- 当前 few-shot 状态：`audit_pass=true`、`retrieval_probe_ok=true`

但当前仓库里还要区分“资产状态”和“预检证据状态”：

- 资产状态：few-shot 审计和 retrieval probe 已通过
- 预检证据状态：必须看“针对当前 source 的最新 preflight 报告”，不能只看旧的 `../../datasets/step2/delivery/current/preflight_report.json` 或 `build_manifest.json.validation.preflight_passed`

因此，这份清单现在的作用是：在未来资产或配置变动后，重新生成下一次可引用的最新 preflight 证据。

## 2. 最小复验命令

### 2.1 few-shot 审计

```bash
python3 code/audit_fewshot_pool.py \
  --db ../../datasets/step2/delivery/current/fewshot_pool.db \
  --json
```

### 2.2 Step2 默认 preflight

```bash
make step2-preflight
```

如需把真实接口连通性也纳入通过条件：

```bash
make step2-preflight STEP2_PREFLIGHT_ARGS="--preflight-api-ping"
```

### 2.3 直接 formal 配置 preflight

```bash
cd code/step2
python3 code/construct_simple_two_intent.py \
  --preflight \
  --preflight-api-ping \
  --output-dir ../../datasets/step2/delivery/current \
  --config configs/step2_runtime_config.local.json
```

## 3. 通过条件

### 3.1 few-shot 资产

- `train` 可检索样本总数 `>= 80`
- 默认 common signatures 每类 `>= 3`
- `bad_style_count = 0`
- `audit_pass = true`
- `retrieval_probe_ok = true`

### 3.2 preflight

- `passed = true`
- `checks.fewshot.passed = true`
- `checks.fewshot.fewshot_pool_formal_ready = true`
- `checks.formal_assets.passed = true`
- `checks.formal_assets.formal_assets_ready = true`
- `checks.input_data.passed = true`
- `checks.input_data.a_tier_count` 与当前 bridge manifest 一致
- 如启用真实接口检查，`checks.generator.api_ping.ok = true`

## 4. 需要重新跑这份清单的情况

- 更换 Step2 默认 source
- 更换 few-shot DB 或 build manifest
- 更新 few-shot 审核口径
- 冻结新的 Step3 eval/test，需要补最终泄露审计
- 调整 formal gate 或默认 common signatures

## 5. 不要做的事

- 不要把 `examples/synthetic_index_harder.csv` 当作默认 formal few-shot
- 不要在未完成 few-shot 审计时宣称 formal-ready
- 不要把旧 source 的 preflight 结果直接拿来给新的 current source 背书
- 不要把 few-shot 资产通过，等同于整条 Step2 论文实验已经完成
