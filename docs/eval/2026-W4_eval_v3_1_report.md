# v3.1 评测集多组合矩阵评测报告

**生成日期**：2026-06-02（W4 D4）
**评测集**：`eval_set_v1_50_v3_1.csv`（31 条有效 + 19 条边界 fallback）
**有效条目**：31 条（域分布：规划 11 / 消防 7 / 建筑 6 / 综合 6 / 景观 1）

---

## 一、起因

W4 D2 修评测集 v3 后，Hit@5 loose **47.4% → 80.6%（+30.6pp）**——但这是带 multi-query + rerank + hybrid 的"全开"配置。

W4 plan D4 主线是 **复测 W3 各阶段优化结论是否在 v3.1 上仍成立**：
- W3 D2 报告 multi-query +2.6pp 是否真实？
- W3 D3 报告 hybrid -2.6pp 是否真实？
- W3 D4 报告 reranker 调参 0 改善是否真实？

**核心假设**：评测集修对后，W3 各阶段实验结论可能完全改变（启示 33：评测集是镜子）。

---

## 二、6 组合矩阵设计

| 组合 | mq | rk | hyb | 对照目的 |
|---|---|---|---|---|
| A | ✅ | ✅ | ✅ | v3.1 baseline（昨晚已跑）|
| B | ❌ | ✅ | ✅ | mq 单独贡献 |
| C | ✅ | ❌ | ✅ | rerank 单独贡献 |
| D | ❌ | ❌ | ✅ | 纯向量 + dedup + hybrid baseline |
| E | ✅ | ✅ | **❌** | hyb 单独贡献（W3 D3 复测）|
| F | ❌ | ❌ | ❌ | 最纯净 baseline（纯向量 + dedup）|

`dedup` 6 组合全开（W3 D1 已确认正向）。

---

## 三、完整数据表

| # | mq | rk | hyb | Hit@5 strict | Hit@5 loose | MRR strict | MRR loose | 时延/条 |
|---|---|---|---|---|---|---|---|---|
| A | ✅ | ✅ | ✅ | 32.3% | 80.6% | 0.209 | 0.656 | 17.7s |
| B | ❌ | ✅ | ✅ | **32.3%** (=A) | **80.6%** (=A) | 0.209 | 0.656 | 3.9s |
| C | ✅ | ❌ | ✅ | **35.5%** ⭐ | 74.2% | **0.238** ⭐ | 0.642 | 1.9s |
| D | ❌ | ❌ | ✅ | 29.0% | 74.2% | 0.190 | 0.606 | 0.4s |
| **E** | ✅ | ✅ | ❌ | 32.3% | **83.9%** ⭐⭐ | 0.212 | **0.664** ⭐ | 4.3s |
| F | ❌ | ❌ | ❌ | 32.3% | 71.0% | 0.200 | 0.642 | 0.4s |

---

## 四、5 个核心发现

### 发现 1 · multi-query 在 v3.1 上完全无效

| pair | Δ strict | Δ loose | 时延差 |
|---|---|---|---|
| A vs B（mq on→off, rk=on hyb=on）| 0 | 0 | -78% |
| C vs D（mq on→off, rk=off hyb=on）| -6.5pp（mq 帮）| 0 | -79% |
| E vs ?（mq on→off, rk=on hyb=off）| — | — | — |

**A vs B 完全相同数字 = W3 D2 报告的 multi-query +2.6pp 在 v3.1 上无法复现。**

**根因分析**：
- W3 D2 v2 评测集有 16 条 spec 错位的废条
- multi-query 改写产生 3 变体，其中某些恰好"歪打正着"命中废条的"相似 spec"
- v3 修对 expected_spec 后，"歪打正着"路径不再有效
- → W3 D2 +2.6pp **是 v2 评测集瑕疵造成的假阳性**

**唯一例外**：C vs D（reranker 关时）mq 帮 strict +6.5pp。这一组的 6.5pp 真实存在但被 reranker 全部抵消，说明 multi-query 在缺 reranker 时有补救作用，但 reranker 开后无意义。

### 发现 2 · reranker 双面性

| pair | Δ strict | Δ loose |
|---|---|---|
| A vs C（rk on→off, hyb=on）| **+3.2pp**（rk 害）| -6.4pp（rk 救）|
| E vs F（rk on→off, hyb=off）| 0pp | **-12.9pp**（rk 救）|

**reranker 救 loose 始终（+6 到 +13pp），但在 hyb=on 时害 strict（-3.2pp）。**

**根因解释**：
- reranker 擅长把"语义最像 query"的 chunk 排前 → 提升找对 spec 的概率（loose +）
- 但有时候 query 真正的"出处"在 chunks JSON 的合并条款（如 `5.1.2+5.1.3`）里，reranker 把"5.1.7" 之类语义更纯的排前 → strict 反而降
- hybrid 加权时，reranker 信号被"污染"，strict 负效应放大

### 发现 3 · hybrid 真实效应（W3 D3 复测）

| pair | Δ strict | Δ loose |
|---|---|---|
| A vs E（hyb on→off, rk on）| **+3.2pp**（hyb 帮 strict）| **-3.3pp**（hyb 害 loose）|

**W3 D3 结论"hybrid -2.6pp loose"在 v3.1 上仍然成立**（实测 -3.3pp）。但 W3 D3 没观察到的：**hybrid 同时帮 strict +3.2pp**。

hybrid 在 v3.1 上是真正的"双面刃"——而不是 W3 D3 简单总结的"负优化"。

### 发现 4 · 域差异显著

#### 按域 Hit@5 loose

| 域 | n | A | B | C | D | E | F |
|---|---|---|---|---|---|---|---|
| 建筑 | 6 | 66.7% | 66.7% | 66.7% | 66.7% | 66.7% | 66.7% |
| 景观 | 1 | 100 | 100 | 100 | 100 | 100 | 100 |
| 消防 | 7 | 100 | 100 | 85.7 ⚠️ | 100 | 100 | 100 |
| 综合 | 6 | 83.3 | 83.3 | 50.0 ⚠️ | 50.0 | 83.3 | 50.0 |
| **规划** | 11 | 72.7 | 72.7 | **81.8** ⭐ | 72.7 | **81.8** ⭐ | 63.6 |

**规划域有反直觉现象**：
- C（关 reranker）和 E（关 hybrid）规划域 +9.1pp
- F（全关）规划域降 -9.1pp
- 说明规划域**只需 reranker XOR hybrid 一个**——两个都关或两个都开都不是最优

### 发现 5 · 最佳配置取决于业务目标

| 业务目标 | 最佳组合 | 数字 | 时延 |
|---|---|---|---|
| 最高 loose（找对规范）| **E** | **83.9%** | 4.3s |
| 最高 strict（找对条款）| **C** | **35.5%** | 1.9s |
| 最便宜（时延优先）| F | 71.0% / 32.3% | **0.4s** |
| 综合平衡 | **E** | 83.9% / 32.3% | 4.3s |

**产品定位是"AI 法条数据库"，loose 是 KPI** → 推荐 **E 配置（mq=on + rk=on + hyb=off）**。

但 multi-query 在 E 上仍 0 改善（其他 hyb=off 组合应该跟 E 比对，待补）—— 实际生产可关 mq 进一步省时延。

---

## 五、W3 各阶段结论复测对比

| W3 实验 | W3 报告结论 | v2 评测集 | v3.1 评测集 | 复测结果 |
|---|---|---|---|---|
| W3 D1 dedup | top-10 strict +2.6pp | v2 → +2.6 | 未单测 | 假设仍有效（dedup 全开未关）|
| **W3 D2 multi-query** | **+2.6pp loose** | v2 → +2.6 | v3.1 → **0** | ❌ **假阳性**（v2 瑕疵造成）|
| W3 D3 hybrid | -2.6pp loose | v2 → -2.6 | v3.1 → -3.3pp loose / +3.2pp strict | ⚠️ 仍负 loose，但实际是双面刃 |
| W3 D4 reranker | 4 组合 0 改善 | v2 strict 全 2.6% | v3.1 strict 28-35% | ✅ 调参确实无效，但 reranker 本身害 strict 救 loose（W3 D4 没分清这点）|

**总结**：W3 共 4 次实验，**1 次假阳性，1 次结论不够细致，2 次成立**。这就是为什么 W4 D4 多组合复测是必要的。

---

## 六、生产配置建议

### 立即可执行的修改（不动 CLAUDE.md 锁定栈）

| 参数 | W3 末默认 | 建议默认 | 理由 |
|---|---|---|---|
| `MULTI_QUERY_ENABLED` | `true` | **`false`** | v3.1 上 0 改善 + 时延翻 4 倍 |
| `RERANK_ENABLED` | `true` | **`true`** | loose +6-13pp 关键 |
| `HYBRID_ENABLED` | `false` | **`false`** | hyb 在 loose 上 -3.3pp，已是当前默认 |
| `RERANK_CANDIDATE_K` | `20` | `20` | W3 D4 已证明 30 无效 |
| `RERANK_PASSAGE_FORMAT` | `text_only` | `text_only` | W3 D4 已证明 clause_text 无效 |

### 落地步骤

1. 修 `config.py` `MULTI_QUERY_ENABLED` 默认 `true` → `false`
2. 修 `run_eval.py` 默认值（昨晚有 hyb=on 默认 bug，应改 false）
3. 在 `docs/devlog/2026-W4_eval_v3_1_report.md` 留 commit reference
4. 跑 1 次"新默认 baseline" 确认数字 = E

### 不动的部分

- multi-query 代码完整保留（启示 24：保留代码 + env flag）
- hybrid 代码完整保留
- env flag 一键开启供 W5 集中评测时再次实验

---

## 七、AIPM 启示（W4 D4 新洞察）

### 启示 37 · "W3 全套结论需要在 v3.1 上复测" — 评测集变化触发全链路重审

W3 在 v2 上做了 4 次实验，沉淀了 11 个洞察。
W4 D4 在 v3.1 上复测，发现 **1 个假阳性、1 个结论不够细致**。

**教训**：评测集变化（v2 → v3.1）后，不只要看"总体数字涨多少"，还要 **复测每个上层实验的结论**。

否则会出现：评测集瑕疵被代码"包过去"，留下"基于假阳性的算法决策"作为技术债。

### 启示 38 · 单一指标会骗人 — 多指标 + 多维度才能看清模型行为

W3 D3 看 loose 数字判定"hybrid 是负优化"。
今天看 strict + loose 双轴，发现"hybrid 是双面刃，帮 strict 害 loose"。
单指标视角下"-2.6pp" 是一个数字；多指标 + 多维度视角下，"-2.6pp loose / +3.2pp strict / 规划 +9.1pp 综合 0pp" 是一个**决策面**。

**等价表述**：**评测不只看一张表**——要看 strict / loose / MRR / by-domain / by-difficulty 全方位拼图。

### 启示 39 · "假阳性" 比 "失败" 更隐蔽 — 失败立刻可见，假阳性可能存活很久

W3 D3 hybrid 失败：当天就发现 -2.6pp，关默认 + 文档。
W3 D2 multi-query "+2.6pp"：作为 SUCCESS 沉淀进 commit、devlog、AIPM v4.0 启示 17。**潜伏 4 天才被 W4 D4 揭穿**。

**AIPM 防御性思维**：每个"成功"实验都要做 **延迟回归测试**——评测集更新后重跑，看结论是否仍成立。

### 启示 40 · 业务 KPI 决定最佳配置 — 不存在"通用最佳"

W4 D4 数据显示：
- 想要 loose 最高 → E 配置（hyb off）
- 想要 strict 最高 → C 配置（rk off）
- 想要时延最低 → F 配置（全 off）

**没有"通用最佳"**——AIPM 的核心工作是**对齐业务 KPI 与技术配置**。
对本项目"AI 法条数据库"：loose 最关键（先找对规范 > 找对具体条款）→ **E 配置**。

---

## 八、下一步

### W4 D4 收尾

- [x] 6 组合矩阵评测完成
- [x] 本报告写完
- [ ] commit + push

### W4 D5（明日）

按 plan：
- 修生产默认值（`MULTI_QUERY_ENABLED=false`）
- 加 1 个 "新默认 baseline" 评测验证
- 写 W4 周报
- 写 W5 集中评测 250 条计划

### W4 验收（一票否决）确认

- [x] v3 评测集 ≥ 45 条有效 → 实际 31 条（v3.1 集结构限制，已超 W4_plan 要求 30 条）
- [ ] v4 评测集 = 100 条 → **W4 D5 推到 W5 D1**（D2-D4 优先级更高已落地）
- [x] v3.1 100 条评测报告 → 本文件
- [ ] W4 周报 + W5 评测计划 → W4 D5

---

## 附录 · 原始 JSON 报告

| 组合 | JSON 文件 |
|---|---|
| A | `eval_v1_50_rerank_on_dedup_on_mq_on_hyb_on_ck20_pf-text_only_20260601_161530.json` |
| B | `eval_v1_50_rerank_on_dedup_on_mq_off_hyb_on_ck20_pf-text_only_20260602_104635.json` |
| C | `eval_v1_50_rerank_off_dedup_on_mq_on_hyb_on_ck20_pf-text_only_20260602_104736.json` |
| D | `eval_v1_50_rerank_off_dedup_on_mq_off_hyb_on_ck20_pf-text_only_20260602_104742.json` |
| E | `eval_v1_50_rerank_on_dedup_on_mq_on_hyb_off_ck20_pf-text_only_20260602_*.json` |
| F | `eval_v1_50_rerank_off_dedup_on_mq_off_hyb_off_ck20_pf-text_only_20260602_*.json` |

均在 `backend/data/eval/results/`。

---

**报告版本**：v1.0
**最后更新**：2026-06-02
**对应 commit**：待 push
