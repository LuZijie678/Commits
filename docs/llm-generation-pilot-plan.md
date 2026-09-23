# LLM Commit Message 生成试点计划

## 1. 为什么要做这个试点

当前的 Step1、Step2、Step2.5 和 Step3-v0 工作仍然有价值，但眼下更直接的研究主线已经转向最终生成任务：

> 给定一个 commit diff 及必要上下文，生成一条自然、准确、简洁的 commit subject。

Step3-v0 的 intent classification 已不再被视为当前论文主线。它仍然保留为诊断模块，以及未来可能恢复的结构模块。这个试点要回答的是：在投入 fine-tuning 或 hunk-to-intent alignment 之前，prompt 策略、retrieval 和 oracle structure 是否真的能提升生成质量。

## 2. 研究问题

- RQ1：在同一个 LLM 下，zero-shot、few-shot ICL、retrieval ICL 和 oracle-structure-guided ICL 的差异是什么？
- RQ2：结构信息对复杂 commit message 生成的提升，是否足以支撑继续投入 Step3 alignment？
- RQ3：现有的 synthetic、`hard_b` 和 `M` 真实域资产，是否足够支持下一轮模型对比？
- RQ4：下一步工作应优先推进 Step3 intent classifier/alignment，还是应先聚焦 prompt、retrieval 和生成模型对比？

## 3. 数据角色

该试点区分四类样本：

| 类别 | 含义 | 主要用途 |
|---|---|---|
| `atomic_simple` | 来自 strict Step3 test 的真实简单单意图 commit | 检查基础生成能力 |
| `hard_b` | 真实复杂单意图 commit | 检查模型是否把配套修改过度拆成多个目标 |
| `synthetic_multi` | Step2 synthetic 多意图 commit | 计算 oracle intent coverage 与 omission |
| `M_real_multi` | 真实多意图 commit | 用 commit-level 标签检查 synthetic 到 real 的迁移压力 |

默认的完整 pilot 为每类 100 个样本。mock 配置仅使用每类 8 个样本做本地验证。

## 4. 泄漏与 exemplar 规则

pilot 的测试样本与 exemplar 池必须分离。构造 exemplar 时要排除 pilot repo、source SHA 和精确 diff fingerprint。dataset builder 会写出 `pilot_leakage_report.json`；一旦泄漏检查失败，流程必须停止。

该 pilot 不把 `hard_b` 或 `M` 当作普通的 Step2 synthetic 来源。`hard_b` 是真实复杂单意图数据；`M` 是带有 commit-level 标签、但 hunk 级结构不完整的真实多意图数据。

## 5. 生成策略

| 编号 | 策略 | 输入 |
|---|---|---|
| G0 | `diff_only_zero_shot` | 仅 diff |
| G1 | `context_zero_shot` | diff、repo、变更路径、任务规则 |
| G2 | `random_fewshot_icl` | G1 加随机 exemplar |
| G3 | `type_matched_fewshot_icl` | G1 加类型匹配 exemplar |
| G4 | `retrieval_icl` | G1 加 TF-IDF 检索 exemplar |
| G5 | `oracle_structure_guided_icl` | G4 再加 oracle structure，仅用于 `synthetic_multi` |

G5 不是可部署方案。它只用于估计结构指导的上界。如果 G5 相比 G4 没有明显收益，项目就不应立即投入复杂的 predicted-structure 模块。

## 6. 后端策略

`code/generation/llm_backend.py` 同时支持 mock backend 和 OpenAI-compatible HTTP backend。除非显式传入 `--allow-real-api`，否则真实 API 调用默认禁用。API key 只能从环境变量读取，不得写入 config、metadata 或日志。

本轮只允许做 mock 验证，不调用真实 API，不训练模型，也不做大规模生成。

## 7. 评测

评测器会报告：

- 格式指标：非空、单行、长度、artifact、重复率；
- 传统文本指标占位：BLEU、ROUGE-L、METEOR、BERTScore 在未安装未来可选依赖前一律记为 `not_applicable`；
- synthetic 结构指标：基于 oracle intent subjects 的 intent coverage 与 omission；
- `hard_b` 代理指标：false multi-expression / over-segmentation proxy；
- `M` 代理指标：真实多意图 coverage pressure，明确不是 gold hunk-level evaluation。

LLM-as-a-judge 被实现为单独接口，默认关闭。它在完成校准前，不能被当作证据使用。

## 8. 为什么先做 ICL，再谈 Fine-Tuning

只有当 pilot 证明生成策略和结构信息确实重要时，fine-tuning 才有理由启动。当前框架先在单一模型下比较 prompting 与 retrieval，再支持后续的模型对比轮次，最后才决定是否需要 LoRA/SFT。

## 9. 下一轮真实 Pilot 的确认项

在任何真实 API 运行前，必须先汇报：

- provider 和 model；
- generation 参数；
- 样本数和策略数；
- 预期请求数；
- 预估 token 量；
- cache 路径和输出根目录。

默认的完整真实 pilot 是 400 个样本乘 6 个策略，即 2400 个请求。

## 10. Real API Probe

在 65-request Canary 之前，项目先使用更小的 Real API Probe。Probe 是 provider 集成检查，不是生成质量实验。

Probe 会从每个类别抽取 1 个样本：

```text
atomic_simple = 1
hard_b = 1
synthetic_multi = 1
M_real_multi = 1
```

总共只执行 5 个请求：

```text
atomic_simple: G1
hard_b: G1
synthetic_multi: G4
synthetic_multi: G5
M_real_multi: G4
```

Probe 会检查 provider、base URL、model name、API-key 环境变量、OpenAI-compatible 请求格式、response parsing、cache/resume 行为、retrieval logging 和日志安全。API key 只能从环境变量读取，不得写入 config、metadata、reports、cache、prompts 或 generation logs。

只有 Probe 通过，才能进入 Canary。Probe 本身不支持任何论文结论。

## 11. Real API Canary

下一步真实 API 动作是低成本 Canary，而不是完整 pilot。它使用 20 个样本：5 个 `atomic_simple`、5 个 `hard_b`、5 个 `synthetic_multi`、5 个 `M_real_multi`。

Canary 对全部 20 个样本只跑 G0、G1 和 G4；另外只对 5 个 `synthetic_multi` 跑 G5。因此计划请求数为：

```text
20 * 3 + 5 * 1 = 65
```

Canary 用来验证 dataset isolation、prompt rendering、retrieval logging、cache/resume 行为、output schema 和 API 稳定性。它不是论文质量的生成结果。

真实调用前的固定 go/no-go 条件为：

- dataset leakage gate passed;
- exemplar leakage gate passed;
- planned request count is exactly 65;
- G5 only runs on `synthetic_multi`;
- prompt rendering completed;
- no unexpected truncation;
- cache and resume work;
- evaluation schema works;
- API key is absent from logs and metadata.

真实 Canary 结束后，还要额外检查：API success rate 至少 0.95，format-valid rate 至少 0.95，single-line rate 至少 0.95，empty-output rate 至多 0.05，并且 manual review 已完成。

## 12. Git LFS 与运行时输出策略

运行时 `outputs/**` 目录不是源资产，不应提交。这里包括 rendered prompts、generation outputs、predictions、request caches、judge caches，以及大型中间 JSONL 文件。

`datasets/hard_b/canonical/` 与 `datasets/m_verified/canonical/` 下的 canonical verified data 仍然属于版本管理对象，必要时可使用 Git LFS。历史提交中已经存在的 LFS 对象，不应在普通 feature work 中顺手清理；任何历史清理都应单独评审。

仓库当前对 `outputs/llm_generation_pilot_*/`、`outputs/llm_generation_canary_*/` 和 `outputs/step3_*/` 使用显式 ignore 规则。已经被 Git 跟踪的输出文件，仍需通过 `git rm --cached` 或等价操作解除追踪；仅靠 `.gitignore` 不会把它们从 Git 中移除。

## 13. Canonical Repository Identity

生成检索流程在比较仓库身份时，必须使用 canonical repository identity，而不是原始字符串是否相等。原因是同一个 GitHub 仓库可能被写成：

- `owner/repo`
- `Owner/Repo`
- `https://github.com/Owner/Repo`
- `https://github.com/Owner/Repo.git`
- `git@github.com:Owner/Repo.git`

这些形式都必须归并到同一个 canonical identity，例如 `arthursonzogni/ftxui`。

pipeline 会保留原始 `repo` 字段用于展示和调试，同时新增：

- `repo_canonical`
- `repo_identity_parse_status`

无论是 dataset filtering、exemplar filtering、retrieval、logging 还是 review artifacts，只要涉及 same-repo guard，都必须比较 `repo_canonical`，而不是原始 repo 字符串。

## 14. Retrieval Leakage Guard

同仓库 exemplar 绝不能进入 ICL prompt。retrieval guard 现在会在四个维度上排除候选：

- same canonical repository identity
- source SHA overlap
- exact diff fingerprint overlap
- exact normalized subject overlap

retrieval log 会同时记录原始 repo identity、canonical repo identity，以及因 canonical same-repo matching 而被排除的候选列表。原始字符串比较只保留为诊断字段，不能作为正式 gate。

如果某个 Probe 或 Canary 在 canonicalization 之后仍然放入了 same-repo exemplar，该轮运行必须在 formal gating 中判为无效。

## 15. Retrieval Quality Diagnostics

本轮 TF-IDF retrieval 算法本身没有变化。新增的是透明诊断，而不是悄悄替换 exemplar。

每条 retrieval log 都会记录：

- `requested_k`
- `returned_k`
- `similarity_scores`
- `similarity_top1`
- `similarity_min`
- `similarity_mean`
- `similarity_p50`
- `low_similarity_threshold`
- `low_similarity_count`
- `low_similarity_ratio`
- `low_similarity_warning`
- `retrieval_quality_status`

默认阈值是 `0.10`。它不会改变排序行为，只是把弱检索暴露出来，方便后续 prompt-strategy 实验决定是否需要单独做 threshold-filtered retrieval ablation。

## 16. Invalidated Probe Policy

如果某个 Probe 包含 canonical same-repo 泄漏，该 Probe 必须被判为无效：

- it may still be used for debugging and qualitative observation;
- it must not be used as the formal Go / No-Go gate into the 65-request Canary;
- any downstream review summary must state that the Probe was invalidated.

无效化报告必须写明受影响样本、原始与 canonical repo identity，以及无效原因。

## 17. Prompt Strategy Pilot

如果 Canary 通过，下一轮计划中的 prompt-strategy pilot 将使用 80 个样本，每类 20 个。它会对全部样本运行 G0-G4，并且只对 `synthetic_multi` 运行 G5。

```text
80 * 5 + 20 = 420 requests
```

这是第一轮用于观察 prompt-strategy 趋势的运行。它仍然不能回答最终模型排序或 fine-tuning 决策。

## 18. Manual Review Protocol

Canary 会写出 `canary_manual_review_template.csv`。manual review 应至少检查每类 5 个样本。

评审重点：

- `atomic_simple`: format, faithfulness, concise subject quality;
- `hard_b`: whether supporting edits are over-segmented into fake multiple goals;
- `synthetic_multi`: compare G4 and G5 for intent omission and structure usefulness;
- `M_real_multi`: check whether major real intents are omitted.

mock 输出不能用于真实质量结论。

## 19. Human Review Gate

Real API Probe 现在在 65-request Canary 之前增加了明确的人类评审 gate。这个 gate 只基于已经完成的 5-request real Probe；它不使用 mock 输出，也不能被 LLM-as-a-judge 取代。

human-review bundle 对每条 Probe 记录都必须展示：

- generated subject and reference subject;
- original commit message;
- diff excerpt with enough code evidence for review;
- retrieval exemplars and similarity scores for G4/G5;
- oracle intent plan for G5 only;
- automatic format checks and runtime metadata;
- reviewer prompts tailored to `atomic_simple`, `hard_b`, `synthetic_multi`, and `M_real_multi`.

该 bundle 用于支持以下人工判断：

- single-line format validity;
- faithfulness to diff;
- completeness over major changes;
- hallucination / unsupported claims;
- hard_b over-segmentation;
- G4 vs G5 comparison on the same synthetic multi-intent sample;
- real-domain unsupported inference, especially wording like `for ABI stability`.

Codex 可以生成 bundle 并校验已填写的 review form，但不能替用户填写 `manual_*` 判断。

## 20. Manual Review 字段定义

Probe review form 以“每条 real Probe generation 一行”的方式组织，并包含：

- `manual_format_ok`
- `manual_faithful`
- `manual_complete`
- `manual_concise`
- `manual_oversegmentation`
- `manual_omission`
- `manual_hallucination`
- `manual_oracle_plan_copying`
- `manual_retrieval_example_reasonable`
- `manual_prompt_defect_detected`
- `manual_overall_accept`
- `manual_confidence`
- `manual_failure_category`
- `notes`
- `reviewer`
- `reviewed_at`

普通布尔型 review 字段都必须填写 `true` 或 `false`。其中有两个字段带策略限定：

- `manual_oracle_plan_copying`: required only for G5, otherwise `not_applicable`
- `manual_retrieval_example_reasonable`: required only for G4/G5, otherwise `not_applicable`

`manual_failure_category` 可以包含以下一个或多个值：

```text
format
unfaithful
omission
hallucination
oversegmentation
oracle_copying
retrieval_irrelevant
prompt_defect
other
none
```

validator 会检查这些类别是否与布尔 review 字段保持一致。

## 21. Probe Go / No-Go Criteria

除非以下条件全部满足，否则 65-request Canary 仍然保持 blocked：

- preflight passed;
- completed request count is 5;
- failed request count is 0;
- API success and parse success rates are 1.0;
- empty-output rate is 0;
- single-line rate is at least 0.8;
- key leakage is false;
- cache works;
- resume works;
- manual review is completed;
- manual format / faithfulness / completeness rates are each at least 0.8;
- manual hallucination rate is at most 0.2;
- prompt defect count is 0.

如果 manual review 未完成，则决策为 `No-Go`，原因是 `manual_review_incomplete`。如果检测到 prompt defect，则决策为 `No-Go`，原因是 `prompt_revision_required`。

5-request Probe 仍然只是协议 gate，不是论文评测。

## 22. 为什么 Probe Review 不能被 LLM Judge 替代

LLM judge 仍然是可选项，而且默认关闭。在 Probe gate 上，它不能替代人工评审，原因有三点：

1. The Probe includes only 5 records, so the review objective is protocol sanity, not model ranking.
2. The gate asks for evidence-sensitive judgments such as over-segmentation, unsupported rationale, and oracle-plan copying.
3. A judge model could repeat the same prompt bias the project is trying to detect.

因此，在进入 65-request Canary 之前，human review CSV 是硬性前提。

## 23. Pilot 之后的路线决策

G5 是 oracle 上界，不是可部署方法。如果 G5 并未明显优于 G4，项目就不应立即投入 Step3 structure prediction。如果 G5 明显更好，下一轮对比应是 no structure、predicted structure 和 oracle structure 三者对照。

fine-tuning 应排在 ICL 与 retrieval pilot 之后；模型比较则应排在 prompt strategy 固定之后。
