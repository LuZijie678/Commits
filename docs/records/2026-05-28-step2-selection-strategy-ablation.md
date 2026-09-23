# 2026-05-28 Step2 选样策略对照实验记录

## 1. 实验目的

本轮实验目标不是修改生成器，而是验证：

1. 当前 Step2 的 `step3_ready` 产率瓶颈，是否可以通过“更聪明的候选选样”直接改善。
2. source-pair 预检质量更高的候选，是否会自然带来更高的最终消息通过率。

实验问题具体化为：

- 基线：现有 `legacy` 选样
- 对照：加入 source-pair 质量优先的 `pair_quality` 选样
- 观察指标：`step3_ready_count`、`pass/fallback/reject`、预检质量、样本复杂度

## 2. 共同实验设置

三轮实验共用以下设置：

- 配置文件：`code/step2/configs/step2_runtime_config.local.json`
- 输入源池：`datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv`
- 目标规模：`target_count=20`
- 审阅导出：`review_samples=0`
- 种子：`seed=42`
- 模型口径：`deepseek-v4-pro + thinking=disabled`
- 长度口径：`62 + final_strong_compress + 条件性放宽`
- 所有运行均为真实 API 运行，不是 mock

说明：

- 三轮运行都因为严格数量闸门未达到 `20/20 step3_ready` 而返回非零退出码；
- 但产物目录完整落盘，因此结果可用于真实对照分析。

## 3. 基线实验：legacy

### 3.1 命令

```bash
cd code/step2
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 MPLCONFIGDIR=/private/tmp/mplconfig \
python3 code/construct_simple_two_intent.py \
  --config configs/step2_runtime_config.local.json \
  --output-dir outputs/step2_compare20_legacy_20260528T113500Z \
  --target-count 20 \
  --review-samples 0 \
  --selection-quality-priority legacy
```

### 3.2 产物

- 输出目录：`code/step2/outputs/step2_compare20_legacy_20260528T113500Z/`

### 3.3 结果

- `step3_ready_count = 14`
- `pass / fallback / reject = 6 / 8 / 4`
- `precheck pass / warn / skip = 6 / 12 / 2`
- `avg_pair_quality_weight_non_skipped = 0.6764`
- `coverage_min_avg / p10 = 0.8938 / 0.8498`
- `Average merged changed lines = 4.45`

## 4. 实验一：pair_quality 首版

### 4.1 设计

首版思路是：

- 在候选组阶段前移 source-pair 预检；
- 在现有结构桶内，把 `precheck_status` 和 `pair_quality_weight` 提前到排序前面；
- 期望优先抽到更“相容”的候选组。

这是一个偏激进的质量优先方案。

### 4.2 命令

```bash
cd code/step2
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 MPLCONFIGDIR=/private/tmp/mplconfig \
python3 code/construct_simple_two_intent.py \
  --config configs/step2_runtime_config.local.json \
  --output-dir outputs/step2_compare20_pair_quality_20260528T114200Z \
  --target-count 20 \
  --review-samples 0 \
  --selection-quality-priority pair_quality
```

### 4.3 产物

- 输出目录：`code/step2/outputs/step2_compare20_pair_quality_20260528T114200Z/`

### 4.4 结果

- `step3_ready_count = 13`
- `pass / fallback / reject = 6 / 7 / 7`
- `precheck pass / warn / skip = 17 / 3 / 0`
- `avg_pair_quality_weight_non_skipped = 0.9340`
- `coverage_min_avg / p10 = 0.8923 / 0.8343`
- `Average merged changed lines = 11.85`

### 4.5 观察

首版有两个表面上“变好”的指标：

1. 预检通过率显著提升；
2. `avg_pair_quality_weight_non_skipped` 从 `0.6764` 提升到 `0.9340`。

但最终 `step3_ready` 反而从 `14` 降到 `13`，而且 `reject` 从 `4` 增加到 `7`。

根因不是生成器崩掉，而是选样分布发生了偏移：

1. 被选样本平均变更行数从 `4.45` 提升到 `11.85`；
2. 类型组合明显向 `fix+test` 集中：
   - `legacy`：`fix+refactor=5, fix+test=5, feat+fix=5, feat+test=3, refactor+test=2`
   - `pair_quality v1`：`fix+test=15, feat+fix=3, feat+test=2`

结论：

- source-pair 规则相容性更高，不等于消息生成更容易；
- 首版 `pair_quality` 把“更相容但更重”的候选提前了。

## 5. 实验二：pair_quality 修正版

### 5.1 修正思路

在首版失败后，做了一个更保守的排序修正：

- 不再让 `pair_quality_weight` 压过结构复杂度；
- 改成“状态优先，复杂度优先，质量仅做后置 tie-break”。

也就是：

1. 先维持现有结构桶；
2. 在桶内仍优先更简单的组；
3. 只在复杂度接近时再用质量分打破平局。

### 5.2 命令

```bash
cd code/step2
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 MPLCONFIGDIR=/private/tmp/mplconfig \
python3 code/construct_simple_two_intent.py \
  --config configs/step2_runtime_config.local.json \
  --output-dir outputs/step2_compare20_pair_quality_v2_20260528T115300Z \
  --target-count 20 \
  --review-samples 0 \
  --selection-quality-priority pair_quality
```

### 5.3 产物

- 输出目录：`code/step2/outputs/step2_compare20_pair_quality_v2_20260528T115300Z/`

### 5.4 结果

- `step3_ready_count = 12`
- `pass / fallback / reject = 6 / 6 / 8`
- `precheck pass / warn / skip = 17 / 3 / 0`
- `avg_pair_quality_weight_non_skipped = 0.9270`
- `coverage_min_avg / p10 = 0.8930 / 0.8444`
- `Average merged changed lines = 11.80`

### 5.5 观察

修正版没有修复核心问题，反而进一步下降到 `12/20`。

这说明：

1. 当前问题不只是“质量排序放得太前”；
2. 只要整体抽样分布被推向这批高预检质量候选，最终消息拒绝率就会上升；
3. `pair_quality` 当前不适合直接作为默认主排序目标。

## 6. 对照结论

三轮结果如下：

| 模式 | step3_ready | pass | fallback | reject | precheck skip | avg pair quality | avg changed lines |
|---|---:|---:|---:|---:|---:|---:|---:|
| legacy | 14 | 6 | 8 | 4 | 2 | 0.6764 | 4.45 |
| pair_quality v1 | 13 | 6 | 7 | 7 | 0 | 0.9340 | 11.85 |
| pair_quality v2 | 12 | 6 | 6 | 8 | 0 | 0.9270 | 11.80 |

可以直接得出结论：

1. 当前 Step2 的 `step3_ready` 产率，不会因为“更高的 source-pair 规则质量”自动提升。
2. 当前 `pair_quality` 选样会把样本推向更重、更难写的一侧。
3. 在当前数据和生成器状态下，`pair_quality` 不能作为默认选样策略。

## 7. 后续决策

基于上述失败尝试，本轮后续策略改为更保守的方案：

- `legacy + skip后置 + 极低质量候选过滤`

原因：

1. 保留 `legacy` 的整体分布，不主动把样本推向更复杂的一侧；
2. 只处理最明显的坏候选：
   - precheck `skip` 候选尽量不要优先抽入；
   - 极低 `pair_quality_weight` 候选直接过滤；
3. 这更符合“最小干预、只削坏样本”的思路。

## 8. 代码状态说明

本轮对照实验期间，代码中曾加入 `pair_quality` 选样模式用于真实对照验证。

当前处理原则是：

1. 保留该实验模式，方便后续复现实验；
2. 在实验三开始前，默认值曾阶段性切回 `legacy`，避免正式运行被当前失败策略误伤；
3. 下一步将继续实现并验证更保守的 `legacy + guard` 方案。

## 9. 实验三：legacy_guarded

### 9.1 设计

在前两轮 `pair_quality` 失败后，改为更保守的 guard 方案：

- 保留 `legacy` 的整体结构排序；
- 仅做两件事：
  1. `precheck_status=skip` 的候选后置；
  2. 极低质量的非 skip 候选过滤，阈值设为 `pair_quality_weight <= 0.42`；
- 目标不是重排到“最高质量”，而是避免最坏候选过早进入采样。

### 9.2 命令

```bash
cd code/step2
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 MPLCONFIGDIR=/private/tmp/mplconfig \
python3 code/construct_simple_two_intent.py \
  --config configs/step2_runtime_config.local.json \
  --output-dir outputs/step2_compare20_legacy_guarded_20260528T121100Z \
  --target-count 20 \
  --review-samples 0 \
  --selection-quality-priority legacy_guarded \
  --selection-min-pair-quality-weight 0.42
```

### 9.3 产物

- 输出目录：`code/step2/outputs/step2_compare20_legacy_guarded_20260528T121100Z/`

### 9.4 结果

- `step3_ready_count = 15`
- `pass / fallback / reject = 7 / 8 / 4`
- `precheck pass / warn / skip = 6 / 14 / 0`
- `avg_pair_quality_weight_non_skipped = 0.6566`
- `coverage_min_avg / p10 = 0.8961 / 0.8636`
- `Average merged changed lines = 4.45`
- `generation_failure_rate_attempted = 1/20 = 0.05`

### 9.5 与 legacy 的直接对照

| 模式 | step3_ready | pass | fallback | reject | precheck skip | avg pair quality | avg changed lines |
|---|---:|---:|---:|---:|---:|---:|---:|
| legacy | 14 | 6 | 8 | 4 | 2 | 0.6764 | 4.45 |
| legacy_guarded | 15 | 7 | 8 | 4 | 0 | 0.6566 | 4.45 |

可以看到：

1. `legacy_guarded` 在不增加样本复杂度的前提下，把 `step3_ready` 从 `14` 提升到 `15`；
2. `reject` 数没有恶化；
3. `precheck skip` 从 `2` 降到 `0`；
4. 平均变更行数保持不变，说明这次改动没有再把样本推向更重的一侧。

### 9.6 解释

这一结果说明：

1. 当前最有效的不是“全局质量优先重排”；
2. 而是“保留原分布，只剔除最坏候选”；
3. `legacy_guarded` 更像一个保守防呆层，而不是新的主排序模型。

## 10. 实验四：feat+fix repair 提示增强 + 超长失败样本最终强压缩增强

### 10.1 改动目的

在 `legacy_guarded` 已经成为当前默认选样策略之后，继续针对上一轮 `4 reject + 1 generation_failed` 的最短提产点做最小干预：

1. 只改 `feat+fix` 样本在 `compress / rewrite` repair 阶段的提示；
2. 只改“仍然因超长失败”的 `final_strong_compress` 提示；
3. 不改主生成 prompt；
4. 不改长度基线 `62`；
5. 不改 `legacy_guarded` 选样协议。

这轮改动的目标不是“大改生成路线”，而是验证：

- 能否把上一轮最接近可救回的 `simple2_0009` 拉回；
- 能否把上一轮 `quality_not_pass_after_repair` 的 `simple2_0006` 至少从失败边缘再往前推一步；
- 同时不伤及原本已经合格或接近合格的样本。

### 10.2 代码改动

本轮只改了三处 prompt builder：

1. `build_compress_prompt(...)`
   - 对 `feat+fix` 额外要求保留 `feat` 侧和 `fix` 侧各一个具体锚点；
   - 明确禁止把任一侧压扁成 `update / improve / handle` 这类泛化动词。
2. `build_rewrite_prompt(...)`
   - 加入同样的 `feat+fix` 双侧锚点约束。
3. `build_final_strong_compress_prompt(...)`
   - 允许在保持语义忠实前提下使用安全技术缩写；
   - 优先压缩重复上下文、长路径和长技术复合词，而不是先丢锚点名词。

### 10.3 命令

```bash
cd code/step2
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 MPLCONFIGDIR=/private/tmp/mplconfig \
python3 code/construct_simple_two_intent.py \
  --config configs/step2_runtime_config.local.json \
  --output-dir outputs/step2_compare20_legacy_guarded_featfixrepair_20260528T040945Z \
  --target-count 20 \
  --review-samples 0 \
  --selection-quality-priority legacy_guarded \
  --selection-min-pair-quality-weight 0.42
```

### 10.4 产物

- 输出目录：`code/step2/outputs/step2_compare20_legacy_guarded_featfixrepair_20260528T040945Z/`

### 10.5 结果

这轮真实运行没有环境错误，但正式门控失败：

- `step3_ready_count = 14`
- `pass / fallback / reject = 6 / 8 / 5`
- `precheck pass / warn / skip = 6 / 14 / 0`
- `avg_pair_quality_weight_non_skipped = 0.6566`
- `coverage_min_avg / p10 = 0.8976 / 0.8598`
- `generation_failure_rate_attempted = 1/20 = 0.05`

对应正式失败原因：

```text
Target gate failed: step3_ready=14, generated=20, required=20, target_count=20, min_target_ratio=1.000
```

### 10.6 与上一轮 `legacy_guarded` 的直接对照

| 模式 | step3_ready | pass | fallback | reject | generation_failed | t_reject | t_pass |
|---|---:|---:|---:|---:|---:|---:|---:|
| legacy_guarded | 15 | 7 | 8 | 4 | 1 | 0.757990 | 0.791892 |
| legacy_guarded + featfix repair | 14 | 6 | 8 | 5 | 1 | 0.762377 | 0.796252 |

可以看到：

1. 这轮改动虽然救回了部分目标样本，但整体结果没有提升，反而从 `15` 掉到 `14`；
2. `reject` 数从 `4` 升到 `5`；
3. 新一轮分布校准把 `t_reject` 和 `t_pass` 都进一步抬高了；
4. 因此有些原本处在边界上的样本，被新的消息分布挤下去了。

### 10.7 关键样本变化

#### 正向变化

1. `simple2_0009`
   - 旧：`reject`, `0.756903`
   - 新：`pass`, `0.814181`
   - 旧 subject：`feat: update build script and validate feature flag keys`
   - 新 subject：`fix(crons): validate feature flag keys in build script`
   - 说明：`feat+fix` repair 提示确实帮助这条样本保住了更强的双侧锚点。

2. `simple2_0004`
   - 旧：`fallback`, `0.781903`
   - 新：`pass`, `0.796707`
   - 旧 subject：`feat(docz): parse index components, add @emotion/core`
   - 新 subject：`feat(docz): parse index components by default, add @emotion/core`

#### 负向变化

1. `simple2_0020`
   - 旧：`pass`, `0.812762`
   - 新：`reject`, `0.742460`
   - 旧 subject：`feat: export TryMapValueParser, fix typo in value_parser.rs`
   - 新 subject：`feat(parser): export TryMapValueParser and fix typo`
   - 说明：这条在压缩后丢掉了 `value_parser.rs` 这个更强的 `fix` 侧锚点，质量明显回落。

2. `simple2_0016`
   - 旧：`fallback`, `0.761923`
   - 新：`reject`, `0.760078`
   - 旧 subject：`fix(nuxi,vite): ensure buildDir exists and unpin vite`
   - 新 subject：`fix(nuxi, vite): ensure buildDir exists and unpin vite`
   - 说明：文本本身变化极小，但由于本轮阈值上移，边界样本被挤入 `reject`。

### 10.8 对 `simple2_0006` 的判断

`simple2_0006` 仍然是 `generation_failed`，失败原因仍为 `quality_not_pass_after_repair`。

但这轮 `final_strong_compress` 的输出已经从原先的：

```text
feat(schematics): output libs to dist/lib/@scope, drop trailing ws lint
```

推进到了新的压缩形式，例如：

```text
feat(schematics): output libs to `dist/lib/@scope`, drop trailing-ws lint
```

这说明：

1. “允许安全技术缩写”是有实际作用的；
2. 但当前失败的主因已经不只是“会不会缩写”，而是：
   - 路径锚点过长；
   - 前缀和模块名过长；
   - 在 `62 / 68` 的双重长度约束下仍未压到可过线范围。

因此，这条样本还不能靠当前这版 prompt 单独救回。

### 10.9 本轮结论

这轮最小 prompt 修复的真实结论是：

1. `feat+fix` repair 定向约束是有效的，至少成功救回了 `simple2_0009`；
2. `final_strong_compress` 的安全技术缩写也确实改变了失败样本的输出；
3. 但这组改动的副作用不可忽略，已经伤到了原本通过或边界可用的样本；
4. 在当前 `legacy_guarded` 正式口径下，这版 prompt 不应直接提升为默认正式版本。

更具体地说，这轮改动属于：

- 局部样本修复成功；
- 全局产率回退；
- 不满足“更短路径、更高总产率”的上线标准。

## 11. 实验五：更窄的 feat+fix repair 触发 + final_strong 路径尾部压缩

### 11.1 改动目的

上一轮失败对照已经说明：

1. `feat+fix` 的双侧锚点约束可以救回 `simple2_0009`；
2. 但“对所有 `feat+fix` 一刀切生效”副作用太大；
3. `simple2_0006` 的失败已经集中到路径锚点太长，而不是完全写不出来。

因此，这一轮只做两处更窄修复：

1. `feat+fix` 双侧锚点约束只在草稿中出现明显塌缩信号时触发；
2. `final_strong_compress` 增加“路径尾部保留、去反引号、路径片段压缩”的单独规则；
3. 继续保持：
   - 主生成 prompt 不改；
   - 长度基线仍为 `62`；
   - `legacy_guarded` 仍是选样协议。

### 11.2 命令

```bash
cd code/step2
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 MPLCONFIGDIR=/private/tmp/mplconfig \
python3 code/construct_simple_two_intent.py \
  --config configs/step2_runtime_config.local.json \
  --output-dir outputs/step2_compare20_legacy_guarded_featfixrepair_narrow_20260528T062730Z \
  --target-count 20 \
  --review-samples 0 \
  --selection-quality-priority legacy_guarded \
  --selection-min-pair-quality-weight 0.42
```

### 11.3 产物

- 输出目录：`code/step2/outputs/step2_compare20_legacy_guarded_featfixrepair_narrow_20260528T062730Z/`

### 11.4 结果

这轮真实运行同样没有环境错误，但正式门控再次失败，而且整体结果进一步回退：

- `step3_ready_count = 13`
- `pass / fallback / reject = 3 / 10 / 7`
- `precheck pass / warn / skip = 6 / 14 / 0`
- `avg_pair_quality_weight_non_skipped = 0.6566`
- `coverage_min_avg / p10 = 0.8973 / 0.8636`
- `generation_failure_rate_attempted = 0/20 = 0.00`

对应正式失败原因：

```text
Target gate failed: step3_ready=13, generated=20, required=20, target_count=20, min_target_ratio=1.000
```

### 11.5 与前两轮对照

| 模式 | step3_ready | pass | fallback | reject | generation_failed | t_reject | t_pass |
|---|---:|---:|---:|---:|---:|---:|---:|
| legacy_guarded | 15 | 7 | 8 | 4 | 1 | 0.757990 | 0.791892 |
| legacy_guarded + featfix repair | 14 | 6 | 8 | 5 | 1 | 0.762377 | 0.796252 |
| legacy_guarded + narrow featfix repair | 13 | 3 | 10 | 7 | 0 | 0.770599 | 0.802706 |

可以看到：

1. 这轮把 `generation_failed` 清零了；
2. 但 `reject` 进一步升到 `7`；
3. `t_reject / t_pass` 又继续上移；
4. 结果是更多边界样本从 `pass/fallback` 被挤到了 `reject`。

### 11.6 关键样本变化

#### 正向变化

1. `simple2_0006`
   - 旧：`generation_failed`
   - 新：`reject`, `0.744350`
   - 新 subject：`feat(schematics): output libs to lib/@scope, drop trailing ws lint`
   - 说明：`final_strong` 的路径尾部压缩规则是有效的，已经把这条从“生成失败”推进到“可生成且格式合格”。

2. `simple2_0009`
   - 延续上一轮结果，保持为 `pass`, `0.814181`
   - 新 subject：`fix(crons): validate feature flag keys in build script`
   - 说明：更窄的触发条件仍保住了这一条的正向修复。

3. `simple2_0020`
   - 上一轮：`reject`, `0.742460`
   - 这一轮：`fallback`, `0.789564`
   - 新 subject：`feat: export TryMapValueParser, fix typo`
   - 说明：缩窄 `feat+fix` 触发后，这条不再被过度重写，明显回升。

#### 仍未解决或继续恶化

1. `simple2_0016`
   - 仍为 `reject`, `0.761923`
   - subject：`fix(nuxi,vite): ensure buildDir exists and unpin vite`
   - 说明：文本已经回到原始较优版本，但由于这一轮门控阈值继续上移，仍被压到 `reject`。

2. 多条非目标样本继续掉档
   - 例如：
     - `simple2_0002`: `fallback -> reject`
     - `simple2_0010`: `fallback -> reject`
     - `simple2_0013`: `pass -> fallback`
     - `simple2_0018`: `pass -> fallback`
   - 这些回退并不是单个样本严重写坏，而更像整轮分布变化导致的状态重分层。

### 11.7 本轮结论

这轮更窄修复的真实结论是：

1. `feat+fix` 触发条件收窄后，上一轮的一部分副作用确实被收回了；
2. `final_strong` 路径尾部压缩规则也确实解决了 `simple2_0006` 的“完全生成失败”问题；
3. 但整体正式产率没有改善，反而从 `14` 进一步降到 `13`；
4. 当前主要问题已经不再是单个失败样本写不出来，而是：
   - 小样本下的生成波动；
   - 分布校准阈值继续上移；
   - 多个边界样本被重新压入 `reject`。

因此，这一轮仍然只能作为失败对照保留，不能提升为默认正式口径。

## 12. 当前结论

截至本轮，三类策略的结论已经比较清楚：

1. `pair_quality` 不适合作为默认主排序；
2. `legacy_guarded` 相比 `legacy` 有小幅但真实的正增益；
3. 因此当前默认选样口径切换为：

```text
legacy ordering
  + defer skip candidates
  + filter extremely low-quality non-skip candidates (<= 0.42)
```

## 13. 代码状态更新

本轮完成后，代码状态更新为：

1. 保留三种显式模式：
   - `legacy`
   - `legacy_guarded`
   - `pair_quality`
2. 默认模式切换为：`legacy_guarded`
3. `pair_quality` 继续保留为实验复现模式，但不作为当前推荐默认值
