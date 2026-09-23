# 2026-05-27 覆盖接受样本二次复核说明

## 1. 说明范围

本说明针对 `datasets/step2/review/m_only_review_sheet.csv` 中 9 条 `manual_override_accepts` 样本做单独复核。

这里的“覆盖接受”指：

- 它们不是靠默认的批量准入口径自动放行；
- 而是在 `docs+test`、`fix+perf`、`perf+refactor` 这三类稀缺签名覆盖不足时，被额外纳入复核并保留；
- 本次复核仍由代理完成，不应表述为人工终审。

本次复核同时核对了以下产物：

- `datasets/step2/review/m_only_review_sheet.csv`
- `datasets/step2/notes/2026-05-27-agent-review-fill-summary.json`
- `datasets/step2/delivery/current/fewshot_pool.db`
- `datasets/step2/delivery/current/fewshot_audit.json`

## 2. 总体结论

二次复核后，9 条覆盖接受样本全部暂时保留，原因如下：

- 9/9 均满足严格 `repo+sha` 去泄露；
- 9/9 均已进入最终 `130` 条 formal-ready few-shot 池；
- 9/9 都能从提交消息和差异中识别出多意图结构；
- 其中 6 条证据较稳，3 条属于边界保留样本。

边界样本不是“错标”，但它们更依赖“主签名清晰、允许伴随次级修复”的解释口径，因此后续如果要再收紧协议，应优先替换这 3 条：

1. `antlr/antlr4@95fd266931b8eafa5fddf513f9852b32dd82b845`
2. `servo/servo@0d36eee456dd822e8493cd651784b1debf78fc32`
3. `vercel/next.js@7429f7ce86accf790414553d4b8c066fbf41e6e6`

## 3. 这 9 条对最终池的实际作用

这 9 条不是“可有可无”的补充样本，而是当前 formal-ready 稀缺签名覆盖的关键支撑：

| 签名 | 最终池总数 | 覆盖接受样本数 | 说明 |
|---|---:|---:|---|
| `docs+test` | 4 | 3 | 大部分覆盖依赖覆盖接受样本 |
| `fix+perf` | 4 | 3 | 大部分覆盖依赖覆盖接受样本 |
| `perf+refactor` | 3 | 3 | 全部覆盖都依赖覆盖接受样本 |

这意味着：

- 当前 formal-ready 池之所以满足 `perf+refactor >= 3`，完全依赖这 3 条覆盖接受样本；
- 如果直接移除任意一条 `perf+refactor` 覆盖样本，当前 formal-ready 审计阈值会立刻失守；
- 因此这份二次复核说明的作用不是“可写可不写”，而是为当前稀缺签名覆盖提供透明解释。

## 4. 复核口径

逐条复核时采用以下标准：

1. 是否确实存在两个及以上可分辨意图。
2. 当前 `type_signature_canonical` 是否能代表主导的意图对。
3. 是否存在明显更合理的替代签名，导致当前签名失真。
4. 是否满足正式 few-shot 使用的基本条件：
   - 严格去泄露；
   - 主题可规范化；
   - 可进入最终 few-shot 池。
5. 如果存在第三意图或隐含修复，是否仍可按“主签名 + 次级附带修改”保留。

## 5. 逐条复核结论

| 样本 | 当前签名 | 最终 130 条中 | 二次结论 | 风险级别 | 主要依据 |
|---|---|---|---|---|---|
| `DapperLib/Dapper@522d150e25639453496043df71f2ee42512604cc` | `perf+refactor` | 是 | 保留 | 低 | 更换 `MySqlConnector`，同时简化构建与测试初始化 |
| `PaddlePaddle/Paddle@3d2583434816172863243cea777b243b208a49bb` | `fix+perf` | 是 | 保留 | 低 | 优化 `AdamW` 内核，同时修正学习率类型与相关正确性问题 |
| `affaan-m/everything-claude-code@e4f4c2c36d7bd6d30cfce0d3a81935271a29bb43` | `docs+test` | 是 | 保留 | 中 | 一处是集成测试修改，一处是文档/技能说明增强 |
| `antlr/antlr4@95fd266931b8eafa5fddf513f9852b32dd82b845` | `docs+test` | 是 | 边界保留 | 高 | 文档清理和测试修复明显，但伴随额外代码修复，实为 3 意图 |
| `ollama/ollama@8968740836d30dc2e96671d829c370b1d6fcd6b6` | `fix+perf` | 是 | 保留 | 低 | 为 M5/NAX 提升性能，同时修复跨编译生成失败 |
| `openzipkin/zipkin@524b74e26e07f39a6a8a819fc281b5b247ccccb7` | `fix+perf` | 是 | 保留 | 低 | 避免 Docker 拉取限流导致构建故障，同时去掉冗余 JDK 安装提速 |
| `servo/servo@0d36eee456dd822e8493cd651784b1debf78fc32` | `perf+refactor` | 是 | 边界保留 | 高 | 提交消息体现性能提升与内部机制调整，但本地差异主要表现为上游版本引入，证据链较弱 |
| `taosdata/TDengine@63e4a309bbf324f4c3c825aa9d5b636d70b38464` | `docs+test` | 是 | 保留 | 低 | 删除错误文档，同时新增测试用例 |
| `vercel/next.js@7429f7ce86accf790414553d4b8c066fbf41e6e6` | `perf+refactor` | 是 | 边界保留 | 高 | 主体是路由发现逻辑抽取与并行化，但提交正文明确包含独立 bug fix |

### 5.1 DapperLib/Dapper

- `sha`: `522d150e25639453496043df71f2ee42512604cc`
- 当前签名：`perf+refactor`
- 提交消息证据：
  - `use MySqlConnector`
  - `Also speeds up the builds with 1 restore and 1 build`
- 差异证据：
  - 测试项目从 `MySql.Data` 切到 `MySqlConnector`
  - `build.ps1` 和测试初始化逻辑被简化
- 复核判断：
  - 这里的“双意图”较清楚，一部分是构建/测试基础设施替换与整理，另一部分是明确的构建提速；
  - 作为 `perf+refactor` 保留是稳妥的。

### 5.2 PaddlePaddle/Paddle

- `sha`: `3d2583434816172863243cea777b243b208a49bb`
- 当前签名：`fix+perf`
- 提交消息证据：
  - `Optimize AdamW GPU kernel`
  - `Change the learning rate type to float64`
- 差异证据：
  - `AdamW` CPU/GPU/XPU 多处内核优化；
  - 多处把学习率输入显式约束到 `FLOAT64`，同时补充相关修正。
- 复核判断：
  - 性能目标与正确性修复同时存在，且彼此可区分；
  - 作为 `fix+perf` 保留没有明显问题。

### 5.3 affaan-m/everything-claude-code

- `sha`: `e4f4c2c36d7bd6d30cfce0d3a81935271a29bb43`
- 当前签名：`docs+test`
- 提交消息证据：
  - `pass transcript_path via stdin JSON in integration tests`
  - `improves strategic-compact skill with decision guide and survival table`
- 差异证据：
  - 修改 `tests/integration/hooks.test.js`
  - 修改 `skills/strategic-compact/SKILL.md`
- 复核判断：
  - 一个意图是测试链路调整，另一个意图是文档/说明增强；
  - 风险点在于测试改动带有“修 bug”色彩，但它仍然发生在测试对象本身，不影响 `docs+test` 作为主签名；
  - 结论为保留，但风险高于常规 `docs+test`。

### 5.4 antlr/antlr4

- `sha`: `95fd266931b8eafa5fddf513f9852b32dd82b845`
- 当前签名：`docs+test`
- 提交消息证据：
  - `Greatly improve the godoc comments`
  - `fixes the failing go runtime test suite`
  - `Prevent use of labels ... that clashes with builtin funcs`
- 差异证据：
  - 大量 Go runtime 文档注释更新；
  - 包含测试文件修改；
  - 同时伴随独立代码修复。
- 复核判断：
  - 这不是纯粹的 `docs+test` 二意图，而是“文档 + 测试 + 修复”的三意图提交；
  - 当前保留依赖的不是“严格 exact-2”，而是“主导对为 `docs+test`，允许伴随次级 fix”；
  - 因此只能判为边界保留。

### 5.5 ollama/ollama

- `sha`: `8968740836d30dc2e96671d829c370b1d6fcd6b6`
- 当前签名：`fix+perf`
- 提交消息证据：
  - `Improve M5 performance with NAX`
  - `prevent generate on cross-compiles`
- 差异证据：
  - 增加双 MLX 构建与运行时检测；
  - 在跨编译场景跳过会失败的 generate 阶段。
- 复核判断：
  - 性能增强与构建正确性修复都很清楚；
  - 作为 `fix+perf` 保留是合理的。

### 5.6 openzipkin/zipkin

- `sha`: `524b74e26e07f39a6a8a819fc281b5b247ccccb7`
- 当前签名：`fix+perf`
- 提交消息证据：
  - `avoid build outages due to pull limits`
  - `removes a redundant JDK 11 install step, to speed up Travis`
- 差异证据：
  - 调整 testcontainers 与 Docker mirror 配置，避免隐式 `docker.io` 拉取；
  - 删除冗余 JDK 安装步骤。
- 复核判断：
  - 一部分是 CI 稳定性修复，一部分是构建提速；
  - 双意图清晰，保留无明显争议。

### 5.7 servo/servo

- `sha`: `0d36eee456dd822e8493cd651784b1debf78fc32`
- 当前签名：`perf+refactor`
- 提交消息证据：
  - `Make animation faster`
  - `direction-aware and compute initial keyframe correctly`
  - `Eliminate Stylo static preference hashing`
- 差异证据：
  - 本地可见差异主要表现为 `stylo` 版本更新和测试元数据变化；
  - 关键内部实现更多依赖上游引入，而不是在当前 diff 中直接展开。
- 复核判断：
  - 提交消息明确包含性能提升，但同时也包含 correctness 修复表述；
  - “eliminate static preference hashing” 可以解释为内部重构/机制调整，但本地证据链弱于其他样本；
  - 因此只能作为边界保留；
  - 如果后续能找到更干净的 `perf+refactor` 样本，这条应优先替换。

### 5.8 taosdata/TDengine

- `sha`: `63e4a309bbf324f4c3c825aa9d5b636d70b38464`
- 当前签名：`docs+test`
- 提交消息证据：
  - `remove wrong committed docs`
  - `add test test_auto_create_output_table.py`
- 差异证据：
  - 删除错误文档 `docs/stream_create_deploy_sequence.md`
  - 新增测试 `test_auto_create_output_table.py`
- 复核判断：
  - 这是一条很干净的 `docs+test`；
  - 保留没有争议。

### 5.9 vercel/next.js

- `sha`: `7429f7ce86accf790414553d4b8c066fbf41e6e6`
- 当前签名：`perf+refactor`
- 提交消息证据：
  - `extract route discovery into unified discoverRoutes() API`
  - `eliminates a duplicate directory traversal`
  - `parallelizes app file mapping`
  - `Fixes a bug in the dev bundler`
- 差异证据：
  - 多处调用点统一改为 `discoverRoutes()`；
  - 引入新的 `route-discovery.ts` / `file-classifier.ts`；
  - 同时正文明确记录一个独立 dev bundler bug fix。
- 复核判断：
  - 主体确实是重构 + 性能优化；
  - 但其提交正文明确自带第三意图 `bug fix`，因此不是严格二意图样本；
  - 当前保留属于“主导对清晰，允许伴随次级修复”的边界保留。

## 6. 最终建议

当前这 9 条样本可以继续保留在 formal-ready few-shot 池中，但需要明确它们的学术表述边界：

1. 不应把它们描述成“纯自动筛选即可稳定得到”的样本。
2. 不应把它们描述成“人工终审确认无争议”的样本。
3. 应表述为：
   - 在严格去泄露前提下，
   - 为补足稀缺多意图签名覆盖，
   - 经过单独覆盖接受与二次复核后保留的样本。

如果后续继续补充 `M` 数据，建议优先替换方向如下：

1. 先补 `perf+refactor`，因为当前 `3/3` 都依赖覆盖接受样本。
2. 再补更干净的 `docs+test` exact-2 样本，以替换 `antlr/antlr4` 这类三意图边界样本。
3. 再补更干净的 `fix+perf` 样本，降低当前对覆盖接受样本的依赖。
