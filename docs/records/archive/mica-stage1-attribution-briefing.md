> 状态：已归档 / 过时
> 本文档是历史实现说明，可能不反映当前代码状态。
> 当前事实来源：docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md

## 1. Stage 1 到底在做什么

MICA 的总目标是：

```text
commit diff
  -> 找出有几个 intent
  -> 把每个 hunk/edit unit 分配给对应 intent
  -> 生成 structured intent plan
  -> 再渲染 commit message
```

但 Stage 1 只做前半部分：

```text
edit units
  -> latent intent slots
  -> intent count
  -> edit/hunk-to-intent attribution
```

也就是只训练模型学会三件事：

```text
1. 这个 commit 是 k=1 还是 k=2？
2. 哪些 slot 应该 active？
3. 每个 edit unit / hunk 应该归到哪个 slot？
```


所以它的实验边界：只用 Step1 的单意图数据和 Step2 的 synthetic 双意图数据，先把 attribution 基础能力训出来。

---

## 2. 一开始tiny sanity比较小的时候，attribution会失败

最早的 tiny sanity 很小：

```text
k1_train = 100
k2_train = 100
k1_dev = 25
k2_dev = 25
epochs = 3
```

它的结果表面上看还可以，因为 train loss 会下降，count head 也有一点学习信号。但真正关键的 attribution 完全失败了。

可以把 attribution 想象成让模型给 hunk 分组：

```text
正确情况：
slot1: e1, e2, e3
slot2: e4, e5

失败情况：
slot1: e1, e2, e3, e4, e5
slot2: empty
```

当时模型的失败就是第二种：几乎所有 edit units 都被压到同一个 foreground slot。

对应指标是：

```text
assignment_top1_slot_distribution = {1: 145}
```

几乎所有 edit units 的 top-1 assignment 都去了 slot 1，其他 slots 没怎么用。

更严重的是：

```text
alignment_pairwise_f1_model_oracle_k = 0.6158
alignment_pairwise_f1_all_one_cluster = 0.6158
```

这说明模型的 attribution 效果和 “把所有 edit units 都当成同一个 intent” 的 trivial baseline 一样。

也就是说，模型没有真的学会分 intent。

---

## 3. 为什么需要继续排查

因为 tiny sanity 本身有严重数据退化。

最明显的指标是：

```text
alignment_pairwise_f1_file_path_baseline = 0.96
alignment_pairwise_f1_random_gold_k_mean = 0.8922
k2_singleton_intent_fraction = 0.96
```

### 3.1 file_path_baseline = 0.96

这说明只靠文件路径就能把很多样本分得很好。

例如 synthetic k=2 样本可能长这样：

```text
intent1: 只改 src/auth/token.py
intent2: 只改 docs/readme.md
```

那模型不用理解 intent，只要看路径就能分：

```text
src/auth -> intent1
docs -> intent2
```

这不是理想的 attribution 任务。

### 3.2 random_gold_k_mean = 0.8922

这更危险。它说明在很多样本里，即使随机分，只要知道 gold k，也能拿很高分。

这通常意味着样本太简单，或者 intent 结构太退化。

### 3.3 k2_singleton_intent_fraction = 0.96

这个意思是：很多 k=2 synthetic 样本中，有 intent 只有一个 edit unit。

例如：

```text
intent1: e1, e2, e3, e4
intent2: e5
```

这种情况下，pairwise F1 很容易被大 intent 主导。模型就算漏掉小 intent，指标也可能不够敏感。

所以第一阶段的失败不能直接归因于模型结构。它可能是：

```text
数据太退化
指标不敏感
训练 schedule 不好
模型真的学不会
loss 写错
Hungarian matching 有 bug
```

这些都需要逐步排查。

---

## 4. Curriculum 重构做了什么

为了解决 tiny subset 退化问题，审计了 Step2 synthetic 数据，然后构造了更健康的 `medium curriculum`。

目标是减少几类坏样本：

```text
1. singleton-dominated k=2 样本
2. 只靠 file path 就能分开的样本
3. random gold k 都能拿高分的样本
```

这一步的意义是让评估更可信。

原来的 tiny sanity 可能像这样：

```text
intent1: src/auth/token.py 4 个 edit units
intent2: docs/readme.md 1 个 edit unit
```

太简单、太偏。

medium curriculum 更希望像这样：

```text
intent1: e1, e2, e3, e4
intent2: e5, e6, e7, e8
```

并且不让 file path 一眼就能分。

这一步后面变成了正式 split 的基础。

---

## 5. 又检查了 loss 和模型是否真的能学

需要弄清楚两个问题：

```text
1. L_align 是不是写错了？
2. assignment head 是不是根本学不会？
```

### 5.1 L_align correctness probe

结果是：

```text
perfect assignment loss = 0.1533
all-one assignment loss = 2.3217
margin = 2.1684
```

这说明 loss 是正常的。

如果 loss 写错，可能出现一种很坏的情况：

```text
perfect assignment 和 all-one assignment 的 loss 差不多
```

那模型就没有动力去学正确分组。

但现在 perfect 明显比 all-one 好很多，所以可以说明：

```text
L_align 本身能区分正确 assignment 和 collapsed assignment。
```

### 5.2 overfit probe

让模型在很小的数据上过拟合，看它能不能硬记住 assignment。

结果：

```text
B_50_k2_only 通过
C_50_k2_plus_50_k1 通过
D_20_k2_align_only 通过
```

这说明：

```text
assignment head 是可学习的
梯度不是 0
模型不是完全没有能力做 attribution
```

如果模型连小数据都 overfit 不了，那就是结构或实现有大问题。现在能 overfit，说明主干结构不是死的。

所以到这里，结论变成：

```text
不是 loss 写错；
不是 Hungarian matching 完全错；
不是 assignment head 完全不可学；
问题更可能出在数据规模、训练 schedule、k1/k2 混合方式上。
```

---

## 6. Slot competition / schedule ablation 做了什么

接下来检查：为什么模型在正常 mixed training 下会 collapse？

这里的核心矛盾是：

```text
k1 样本要求所有 edit units 属于一个 intent
k2 样本要求 edit units 分成两个 intent
```

如果训练数据太小，或者训练初期 k1 信号太强，模型可能学成：

```text
所有 commit 都尽量用一个 slot
```

这就会压制第二个 slot 的形成。

于是做对照：

### S6：只用 k2 训练

```text
k2_split_recall = 0.88
second_slot_gold_recall = 0.4233
unit_accuracy_gain_over_all_one = 0.1301
slot_collapse_rate = 0.12
count_accuracy = 1.00
```

这说明只看 k2 时，模型是能学出第二个 slot 的。

### S0：k1/k2 mixed 训练

```text
k2_split_recall = 0.00
second_slot_gold_recall = 0.00
slot_collapse_rate = 0.56
```

这说明混合训练时，第二个 slot 被压没了。

所以当时得到一个重要结论：

```text
assignment 可学，loss 正确，但小规模 mixed Stage 1 会压制 early slot specialization。
```

也就是说：

**模型本来能学会分两个 intent，但 k1/k2 混在一起小规模训练时，它容易偷懒，把所有东西都塞进一个 slot。**

---

## 7. 为什么 T2 一开始看起来有效

为了解决 mixed collapse，试了 staged curriculum，也就是先让模型学会 k2 分裂，再逐步加入 k1。

T2 是：

```text
前 8 个 epoch：k2 only
后 7 个 epoch：mixed k1/k2，并保留 k2 replay
```

它在 tiny mixed 上效果很好：

```text
count_accuracy_mixed = 0.78
k2_split_recall_mixed = 0.92
second_slot_gold_recall_mixed = 0.4867
unit_accuracy_gain_over_all_one_mixed = 0.0438
slot_collapse_rate_mixed = 0.12
```

当时的理解是：

```text
T2 可以先培养 second slot specialization，
再用 replay 防止 mixed 阶段遗忘。
```

所以 T2 一度被认为是候选正式 schedule。

但这里没有直接冻结，而是继续扩样复现，因为 tiny scale 上有效不代表大规模稳定。

---

## 8. T2 扩样为什么推翻了之前判断

扩样后，发现：

```text
Scale A: T2 成功
Scale B: T2 有改善但不过阈值
Scale C: T2 失败，naive 反而更强
```

Scale C 单 seed 结果：

```text
naive_balanced_mixed:
  k2_split_recall = 0.8720
  second_slot_gold_recall = 0.5325
  unit_gain = 0.0888
  collapse = 0.1080
  count = 0.9240

T2:
  k2_split_recall = 0.6560
  second_slot_gold_recall = 0.3869
  unit_gain = 0.0502
  collapse = 0.2280
  count = 0.9000
```

这说明在小数据里，naive mixed 容易 collapse，所以 T2 有帮助。

但数据扩大到 500/500 后，naive mixed 看到的 k2 信号足够多，自己就能学会 second slot。T2 反而可能因为前 8 个 epoch 只看 k2，后面 reintroduction 不够自然，导致整体不如 naive。

所以修正结论：

```text
T2 是 tiny-scale 的修复技巧；
不是稳定 formal schedule。
```

---

## 9. Multi-seed comparison 最后确认了什么

为了避免 Scale C 单 seed 偶然性，做了多 seed：

```text
seeds = [13, 42, 2026]
scale = 500 k1 + 500 k2
```

结果：

```text
naive_balanced_mixed:
  pass_rate = 1.0
  mean second_slot_gold_recall = 0.5628
  mean unit_gain = 0.1002
  mean collapse = 0.1267

T2:
  pass_rate = 0.6667
  mean second_slot_gold_recall = 0.4063
  mean unit_gain = 0.0561
  mean collapse = 0.2333
```

这就说明：

```text
naive 在更大规模上不是偶然赢；
它多 seed 稳定优于 T2。
```

因此正式候选 schedule 从 T2 改为：

```text
naive_balanced_mixed_large_scale
```


---

## 10. 当前 protocol freeze 做了什么


当前冻结内容包括：

### 10.1 schedule 固定

```text
epochs = 15
从 epoch 1 开始 mixed k1/k2
lambda_align = 1.0
lambda_count = 0.5
lambda_exist = 0.5
no replay
no staged warmup
no Stage 2 loss
```

也就是正式 Stage 1 candidate 使用 naive mixed。

### 10.2 formal manifest 建议规模

```text
train: 1000 k1 + 1000 k2
dev:   250 k1 + 250 k2
test:  250 k1 + 250 k2
```

这比前面多 seed 比较的 500/500 更正式。

### 10.3 medium candidate pool 健康

```text
medium_candidate_count_available = 3599
fallback_applied = false
```

说明不用放宽筛选条件，数据够用。

### 10.4 split 结构健康

```text
singleton_fraction = 0.0000
file_path_baseline_mean ≈ 0.56
random_gold_k_mean ≈ 0.43
avg_edit_units ≈ 8
```

这说明：

```text
k2 样本不是 singleton-dominated；
file path baseline 不再接近 0.96；
random baseline 不再异常高；
样本平均 edit units 足够多，能测试 attribution。
```

所以 formal split 比最早 tiny sanity 健康得多。

---

## 11. Leakage / overlap 检查说明了什么

当前 hard leakage 检查：

```text
sample_id_overlap_count = 0
sha_overlap_count = 0
synthetic_id_overlap_count = 0
```

这说明 train/dev/test 之间没有明显硬泄漏。

也就是不会出现：

```text
同一个样本同时出现在 train 和 test
同一个 sha 同时出现在 train 和 test
同一个 synthetic id 同时出现在 train 和 test
```

但它也明确承认：

```text
repo_overlap_allowed_for_stage1_synthetic = true
```

也就是 Stage 1 synthetic split 不是 repo-disjoint。

这不是隐藏问题，而是一个需要诚实写明的边界。因为 Stage 1 目前主要是 synthetic attribution pretraining，不是最终真实域泛化评估。真正 real-domain final test 后续要靠 hard_b/M/RealDomainBinary 和 M-final-test 隔离。

---

## 12. 这部分已经解决了哪些问题

已经解决的问题可以总结为 7 个。

第一，确认训练代码链路能跑，loss 会下降。

第二，确认初始 tiny sanity 的失败不能直接代表模型不可行，因为数据退化严重。

第三，确认 `L_align` 和 Hungarian matching 没有结构性错误。

第四，确认 assignment head 能在小数据上过拟合，说明模型有 attribution 学习能力。

第五，确认小规模 mixed training 会导致 slot collapse，这解释了早期失败。

第六，确认 T2 只是 tiny-scale 修复，不适合作为正式 schedule。

第七，确认 larger-scale naive mixed 在多 seed 下更稳定，因此可以作为 candidate formal Stage 1 schedule。

所以现在你们已经把问题从：

```text
模型为什么完全学不起来？
```

推进到了：

```text
用哪个正式 Stage 1 protocol 做 official validation？
```

这已经是一个明显进展。

---

## 13. 现在仍然没有解决什么

### 13.1 repo overlap 是否可接受

当前 hard leakage 是 0，但 repo overlap 允许，也就是 Stage 1 synthetic split 不是 repo-disjoint。

需要确认：

```text
Stage 1 synthetic pretraining 是否允许 repo overlap？
是否需要额外做 repo-disjoint diagnostic？
```


### 13.2 official validation 的通过阈值还需要最终定死

之前用了很多阈值：

```text
k2_split_recall >= 0.50
second_slot_gold_recall >= 0.40
unit_accuracy_gain_over_all_one > 0.03
slot_collapse_rate <= 0.45
count_accuracy >= 0.55
over_split_rate_on_k1 <= 0.45
```

这些阈值用于 sanity/fix 判断可以，但正式 Stage 1 validation 要不要沿用，还是要提高，需要确认。

比如 formal validation 是否要求：

```text
second_slot_gold_recall >= 0.50？
unit gain >= 0.05？
count accuracy >= 0.80？
```


### 13.3 是否需要 flat classifier / no-slot baseline

原方案硬条件里有：

```text
flat classifier / no-slot decoder baseline
```

目前 Stage 1 主要对比了：

```text
all-one
file-path
random-gold-k
naive vs T2
```

但还没有完整比较：

```text
没有 slot decoder 的 flat classifier
普通 pairwise classifier
普通 clustering baseline
```

需要确认是否在 official Stage 1 validation 前加入，还是 Stage 1 后补。

### 13.4 是否需要 repo-disjoint / template-masked diagnostic

目前 formal split 健康，但仍基于 synthetic。审稿人可能会问：

```text
模型是不是学了 synthetic template？
模型是不是学了 repo/path shortcut？
```

后面需要 anti-shortcut：

```text
path-masked
diff-marker-masked
template-masked
repo-disjoint diagnostic
cross-project diagnostic
```

这些是否现在就做，还是 Stage 1 validation 后做，需要确定优先级。

--
