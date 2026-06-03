# 建景规规范问答助手 · 项目结题总结

**项目名**：建景规规范知识问答助手（Architectural Norm RAG Assistant）
**项目阶段**：W1-W5 MVP 5 周开发
**当前版本**：v1.0-mvp（W5 D5 收官）
**最后更新**：2026-06-03

---

## 一、项目定位

> **"AI 版规划/建筑/景观/消防/结构规范的法条数据库"**

面向中型设计院规划师的 RAG 智能查询工具，回答**严谨权威 + 可追溯到原文**，不做聊天伙伴。

### 1.1 解决什么问题

规划/建筑/景观/消防/结构 5 类规范散落在 39+ PDF 中（共 ~6000 条条文），设计师查阅困难：
- 关键词搜索难定位精确条款
- 跨规范查询需开多个 PDF 对照
- 强制性条文用语易混淆（应/不应 vs 宜/不宜）
- 数字数据（服务半径/绿地率/容积率等）查询慢

### 1.2 产品红线（CLAUDE.md 4 条）

- 🔴 不允许编造规范信息
- 🔴 引用必须精确（规范全称 + 标准号 + 条文号 + 跳转）
- 🔴 强制性条文用语不可错（应/不应/宜/不宜 不可混用）
- 🔴 不写 chunks 之外的"建议"

---

## 二、技术架构

### 2.1 技术栈（CLAUDE.md B.1 锁定，全程未变）

```
后端：Python 3.11 + FastAPI + LangChain + qdrant-client + sentence-transformers + openai SDK
前端：Node.js 18 + React 18 + TypeScript + Vite + Tailwind CSS + zustand
基础设施：Qdrant 1.x (local file mode) + SQLite + Nginx
第三方：DeepSeek API (主, deepseek-chat) + 通义千问 Max (备)
```

### 2.2 RAG Pipeline 流程

```
用户 query
  ↓
[1] 输入校验 + 场景识别（8 类边界兜底）
  ↓
[2] Query 改写（W3 D2 加 · 多 query 召回）
  ↓
[3] 向量检索 (BGE-M3 1024-dim + Qdrant cosine)
  ↓
[4] Rerank (BGE-Reranker-v2-m3, top-20 → top-5)
  ↓
[5] DeepSeek 流式生成 (SYSTEM_PROMPT_MAIN 7 条规则 + 4 条防编造硬约束)
  ↓
[6] 流末输出 citations + metadata(dangling_count)
  ↓
SSE 流式返回到前端
```

### 2.3 最终上线配置（Combo E）

经 W4-W5 6 组合 regression 验证：

| 配置 | 设置 | 选择理由 |
|---|---|---|
| multi_query | ✅ ON | regression loose 93.1% 最优 |
| reranker | ✅ ON | 关键质量保障 |
| hybrid (BM25) | ❌ OFF | hyb=on 害 loose -1pp |

---

## 三、5 周开发历程

| 周 | 主题 | 关键成果 | 指标里程碑 |
|---|---|---|---|
| W1 | 项目地基 | 跑通 PDF 入库 + 39 部规范向量化 | - |
| W2 | RAG MVP | 评测体系跑通 / v2 50 条 / 8 类 fallback | strict 2.6% / loose 50% |
| W3 | RAG 性能优化 | Multi-query (D2) / Hybrid 探索 / Reranker (D4) | strict 32.3% / loose 83.9% |
| W4 | 工程纪律 | 评测集深度核 (D3) / 多组合 (D4) / 自动回归 (D5) | strict 64.9% / loose 89.1% |
| W5 | 质量验证收官 | 评测扩 150 / 7 维度 LLM Judge / Prompt 加固 / 答辩 | **strict 76.7% / loose 93.1% / 综合 87.5** |

---

## 四、评测体系（项目最大资产之一）

### 4.1 评测集进化曲线

```
v1 → v2 → v3 → v3.1 → v4 → v4.5
38   50   50    38    100   150 条
↓    ↓    ↓     ↓     ↓     ↓
W2   W2   W3   W4D3  W5D1  W5D2

strict 进化：
2.6% → 16.1% → 32.3% → 64.9% → 76.7%
                ↑
        W3 D4 报告"32.3% = reranker 物理上限"
        被 W4 D3 + W5 D1 + W5 D2 三次推翻
```

### 4.2 评测工具链（7 个脚本）

| 脚本 | 功能 |
|---|---|
| `run_eval.py` | 检索层评测（Hit@5 / MRR） |
| `run_fallback_eval.py` | 8 类边界兜底评测 |
| `run_regression.py` | 跨组合 + 跨评测集对照（W4 D5） |
| `run_quality_eval.py` | **7 维度 LLM Judge** (W5 D2) |
| `sample_quality_review.py` | 抽样人工核对工具（W5 D3） |
| `build_eval_v*.py` | 评测集构建（v3/v4/v4.5） |
| `gen_eval_v*_draft.py` | LLM 候选 query 生成（W5 D1） |

### 4.3 7 维度评分体系（PRD I.3）

| 维度 | 权重 | 方式 | 一票否决 |
|---|---|---|---|
| 1. 检索召回 (Hit@5 loose) | 20% | 自动 | 否 |
| 2. 精确条款 (Hit@5 strict) | 15% | 自动 | 否 |
| 3. 引用准确 | 20% | LLM Judge | 否 |
| 4. 原文用词 | 15% | LLM Judge | ★ 是 |
| 5. 数字精确 | 10% | LLM Judge | ★ 是 |
| 6. 边界识别 | 10% | 自动 | 否 |
| 7. 不编造 | 10% | LLM Judge | ★ 是 |

---

## 五、W5 最终量化结果

### 5.1 RAG 系统综合质量（W5 D5 终极测试，工具修复后）

| 验收项 | 验收线 | W5 D5 实测 (n=116, 0 skip) | 通过 |
|---|---|---|---|
| 综合得分 | ≥ 75（GREEN）| **86.6 / 100** | ✅ +11.6 |
| 一票否决项（单次 Judge）| = 0 | 38 / 116（32.8%）| ❌ |
| **真实 veto 顽疾**（D3/D4/D5 三次交集）| = 0 | **14 / 116（12.1%）** | ❌ |
| RAG 配置 | 通过 regression 验证 | Combo E loose 93.1% | ✅ |

### 5.2 7 维度（D3 baseline → D5 终值）

| 维度 | D3 (单次 baseline) | D5 (终值) | Δ |
|---|---|---|---|
| dim1 检索召回 | 84.5% | 84.5% | 0 |
| dim2 精确条款 | 67.2% | 67.2% | 0 |
| dim3 引用准确 | 96.6% | **98.3%** | +1.7pp ✅ |
| dim4 原文用词 | 83.6% | **86.2%** | +2.6pp ✅ |
| dim5 数字精确 | 93.1% | 94.0% | +0.9pp |
| dim7 不编造 | 78.4% | 76.7% | -1.7pp ⚠️ |
| **综合** | **86.0** | **86.6** | **+0.6** ✅ |

### 5.3 关键洞察：单次 Judge 噪声 ~50%

W5 D5 跑完发现 D3/D4/D5 三次 veto 的交集只有 **14 条** — 即"真实顽疾 veto"是 14/116，远低于任一单次跑的 30-33%。

**结论**：~50% 的 veto 信号是 LLM Judge 的非确定性噪声，**单次评测会高估问题严重程度**。这是 W5 最重磅元评测发现（启示 53）。

### 5.4 按域 veto 触发率

| 域 | n | D3 触发率 | D4/D5 触发率 |
|---|---|---|---|
| 消防 | 11 | **0.0%** ✅ | **0.0%** ✅ |
| 规划 | 41 | 19.5% | ≈19.5% |
| 景观 | 17 | 29.4% | ≈29.4% |
| 建筑 | 35 | 45.7% | **~37.1%** ✅ |
| 综合 | 12 | 50.0% | ≈50.0% |

---

## 六、项目未达成（GREEN 卡点）

### 6.1 dim7 编造（78.2% / 35 条触发）

**4 种典型编造模式（W5 D3 归纳）**：
1. 编造引用号 [4][5][6] — **修复 ~75%** ✅
2. 补充说明区编造 — **修复 ~0%** ❌（顽疾）
3. 编造"强制性条文"标签 — 修复 ~33%
4. 编造跨规范引用 — 修复 ~0%

### 6.2 W6+ 改进方向（已沉淀到 AIPM 启示 52）

- **后处理 strip 整段"补充说明"/"另注"/"备注"节** — prompt 写得再严也根治不了 LLM 训练惯性
- chunks OCR 质量提升 — PDF 错字会污染 Judge 判断（启示 49）
- LLM Judge 自身防 hallucinate 加固 — Judge 准确率 60-70% 仍可提升

---

## 七、项目最大资产（不是代码，是认知）

### 7.1 AIPM 转行必备知识（52 个洞察）

`docs/devlog/AIPM转行必备知识.md` v5.5 沉淀的洞察分布：

```
v1 (W1): 8 个 - 项目地基
v2 (W2): 5 个 - RAG MVP
v3 (W3): 5 个 - 性能优化
v4 (W4 D1-D2): 6 个 - 工程纪律
v5 (W4 D3-D5): 12 个 - 评测集是产品（最重要！）
v5.1 (W4 D4): 4 个 - 多组合对照
v5.2 (W5 D1): 2 个 - 评测集扩量
v5.3 (W5 D2): 2 个 - 用户审核训练场
v5.4 (W5 D3): 5 个 - 元评测（评测的评测）
v5.5 (W5 D4): 3 个 - 评测工具故障是隐藏变量

总计 52 个 AIPM 转行核心洞察
```

### 7.2 三大方法论（最值钱的"软资产"）

1. **EDD（Evaluation-Driven Development）9 步闭环**（v5.5 终版）
2. **温柔挑战 5 步法** — 用户审核 AI 草案的标准流程（W4 D3 → W5 D2）
3. **跨评测集回归 + 防假阳性**（W4 D5 + 启示 39）

---

## 八、上线决策（项目结题判定）

### 8.1 推荐结论

**YELLOW（限定场景上线）**：
- 综合 87.5 ✅ 远超 75 GREEN 线
- veto 29.1% ⚠️ 主要是"补充说明"训练惯性导致
- 适合**专业设计师**作为查询辅助（用户能识别"补充说明"是 LLM 增补）
- 不适合**学生 / 非专业用户**单独使用（可能被"补充说明"误导）

### 8.2 不推荐 GREEN 上线的原因

- veto = 0 的硬门槛未达成
- 28 条持续触发 veto（W5 D4 修订后仍存在）
- 后处理 strip 补充说明节是 W6 工作

### 8.3 不应回退 RED

- 综合 87.5 远超 60 红线
- 4 类编造模式中 [N] 编造 + 跨规范联想已基本根治
- 消防域 0% veto 证明 RAG 系统**真正能做到不编造**

---

## 九、附件

| 文件 | 用途 |
|---|---|
| `docs/PRD.md` | 完整产品需求文档 |
| `CLAUDE.md` | Claude Code 开发规范（4 大红线 + 10 个模块）|
| `docs/devlog/2026-W{1-5}_D*.md` | 25 篇开发日志（W1-W5 全程）|
| `docs/devlog/AIPM转行必备知识.md` | 52 个 AIPM 洞察 v5.5 |
| `docs/eval/W5_quality_report.md` | W5 综合质量评估报告 |
| `docs/eval/W5_D4_prompt_fix_compare.md` | D3 vs D4 prompt 修订对比 |
| `docs/eval/W4_eval_v3_1_report.md` | 多组合评测报告 |
| `backend/data/eval/eval_set_v1_150_v4_5.csv` | 最终评测集 v4.5 |
| `backend/data/eval/quality/quality_*.json` | 4 次 quality_eval 完整结果 |
| `backend/data/eval/regression/regression_*.md` | 跨集 regression 报告 |

---

**项目作者**：陈彦君
**Github**：https://github.com/ChenYanjun-hub/arch-norm-rag-assistant（私有）
**最后版本**：v1.0-mvp
**完成日期**：2026-06-03
