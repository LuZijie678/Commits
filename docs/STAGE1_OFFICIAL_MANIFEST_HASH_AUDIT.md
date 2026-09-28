# Stage1-v1 官方 manifest 哈希差异核查（2026-09-28）

本页是对历史运行产物的**只读核查补充**，不是重新运行实验，不修改原始 manifest、completion、官方结果记录或后续 supplement。

## 核查对象与结论

- 历史运行：`stage1_official_validation_20260723T091921Z`。
- [官方结果记录](../configs/mica/official_results/stage1_official_validation_20260723T091921Z.json)和[completion](../outputs/mica_stage1_official_validation_20260723T091744Z/official_run/stage1_official_validation_completion.json)登记的 manifest SHA-256：`32943fae2925943aa183a7404da4e6546fa4a11dc231e65d007cad3f4d482e49`。
- [最终落盘的 manifest](../outputs/mica_stage1_official_validation_20260723T091744Z/official_run/stage1_official_validation_manifest.json) SHA-256：`e0fa6c3c4a32f638a0257203ed360a4e29d1c99bd15eee378f02536ef13e808b`；后续[unit-accuracy supplement](../configs/mica/official_results/stage1_official_validation_20260723T091921Z_supplement_v1.json)也引用这一最终文件哈希。
- 官方结果记录列出的其他 12 个输出文件，在本工作树的实际 SHA-256 均与登记值一致；只有 manifest 一项不符。

## 形成机制与可复核证据

[运行程序](../code/mica/runners/run_stage1_official_validation.py)先写出不含 `metadata.output_hashes` 的 manifest，然后计算包括该 manifest 在内的输出哈希；随后把哈希表加入 manifest 并再次写入同一文件。第二次写入改变了被哈希的文件本身，因此第一次计算的 manifest 哈希不再是最终文件哈希。completion 与官方结果记录保留了第一次计算的值，最终 manifest 和后续 supplement 则对应第二次写入后的文件。

核查时从最终 manifest 的 JSON 对象中仅移除 `metadata.output_hashes`，按项目 `write_json` 的 `json.dumps(..., ensure_ascii=False, indent=2) + "\n"` 格式重建初版字节，再计算 SHA-256，**恰好得到**登记值 `32943fae2925943aa183a7404da4e6546fa4a11dc231e65d007cad3f4d482e49`。这与代码的写入顺序完全吻合，说明差异可由自引用写入解释；无需假定预测、指标或人工修改发生变化。此推断不是对原始运行环境的重新执行证明。

## 使用边界

保留两种哈希及原文件，不把登记值直接改成最终值，也不声称原始 `output_hashes` 13/13 与最终落盘文件匹配。后续若修复生成程序，应避免把 manifest 自身列入写回该 manifest 的哈希表，并用独立测试覆盖此情况。该技术问题的定位**不撤销** Stage1-v1 的 `pilot_only` / `NO_GO_STAGE2` 科研审计结论。
