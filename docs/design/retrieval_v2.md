# 检索 v2 设计 · W3 D1 诊断 + 攻坚路径

> **本文记录 W3 Day 1 5 轮诊断的真实结论**
> 起因：W2 D3 评测发现 Hit Rate@5 (loose) 仅 47.4%，离 CLAUDE.md 80% 目标差 33pp
> 结论：与最初假设完全不同——**主要瓶颈不在 OCR，在向量召回质量本身**

---

## 一、5 轮诊断完整结果

### 假设 → 实测对照

| 轮次 | 假设 | 实测数据 | 是否主因 |
|---|---|---|---|
| 1 | OCR 把条文编号识乱（如 `4.0.3`→`40.3`）| 全库 4773 chunks 中疑似乱号 18 条（0.4%）| ❌ 不是主因 |
| 2 | OCR 字符错（"住宅"→"住名"等）| 命中 4 条 chunk（< 0.1%）| ❌ 不是主因 |
| 3 | 向量库重复入库 | Qdrant 4773 = JSON 4773，1:1 对齐 | ❌ 不存在 |
| 4 | chunker 内容级重复（chunk_id 唯一但 text 相同）| **GB 55037-2022 实测 422 chunks / 228 独立 clause = 1.85x**，"_dN"后缀机制无去重 | ✅ 是问题，但**只影响 top-10**，不影响 top-5 |
| 5 | 向量召回语义偏（BGE-M3 在专业规范文本上的弱点）| Q009/Q010 期望 GB 55037 5.1.x，top-20 全是 5.2/5.3 章节，5.1 一条都没召回 | ⭐ **真正主因** |

### 关键观察

```python
# Q010 "办公建筑的耐火等级最低要求？" 期望 GB 55037-2022 5.1.3
# 实际 top-20（按 BGE-M3 cosine 排序）：
[ 1] 0.705 GB 55037-2022 5.3.1   ← "耐火等级 ★" 但是 5.3 章节
[ 2] 0.705 GB 55037-2022 5.3.1   ← chunker _dN 重复
[ 3] 0.704 GB 55037-2022 5.3.2
[ 4] 0.704 GB 55037-2022 5.3.2   ← 重复
[ 5] 0.703 GB 55037-2022 5.2.1
...
[11] 0.653 GB 55037-2022 5.1.1   ← 5.1 章节才出现，离 expected 5.1.3 还差
```

BGE-M3 把 "5.3 防火等级条款" 和 "5.1 耐火分类" 搞反了——这是 embedding 模型在**专业术语近义但章节不同**场景的固有弱项。

---

## 二、今晚做了什么

### 已实施：retriever 层 dedup（短期 fix）

文件改动：
- `backend/app/rag/retriever.py` 新增 `dedup_results()` 函数
- `backend/app/rag/pipeline.py` search 后调用 dedup（粗排放大 2× 补偿）
- `backend/scripts/run_eval.py` 加 `--no-dedup` flag 对照

去重 key：`(spec_code, normalized_text_prefix_200)`，保留 score 最高的那条。

### 测量结果

| 指标 | dedup OFF | dedup ON | Δ |
|---|---|---|---|
| Hit@5 strict | 2.6% | 2.6% | 0 |
| Hit@5 loose | 47.4% | 47.4% | 0 |
| **Hit@10 strict** | **2.6%** | **5.3%** | **+2.6pp** ⭐ |
| Hit@10 loose | 52.6% | 52.6% | 0 |
| MRR strict | 0.026 | 0.030 | +0.004 |

**解读**：dedup 让 top-10 strict 翻倍（2.6 → 5.3），但 top-5 没动。说明 dedup 在 reranker 之前给了它更多样化的候选，但 reranker 已经在做语义筛选，dedup 与之冗余。

### 价值评估

dedup 不是"白做"：
1. **top-10 strict +2.6pp** 真实改善
2. **后续 LLM 生成时引用更多样**（前端右栏 5 张卡片不再有 2 张内容相同）
3. **进一步 query 改写 / hybrid 后，dedup 是基础设施**——避免新的检索路径再次被重复噪声污染

---

## 三、W3 D2/D3 攻坚路径

### 路径 1 ⭐ · Query 改写（推荐首攻）

**问题**：用户问 "办公建筑的耐火等级最低要求"，BGE-M3 把 "耐火等级" 匹到 5.3 防火等级，错过 5.1 耐火分类。

**方案**：用 LLM 在 embed 前把 query 扩展为多组关键词：
```
原 query: "办公建筑的耐火等级最低要求"
↓ LLM rewrite
拓展查询: [
  "办公建筑 耐火等级 最低要求",
  "民用建筑 耐火等级分类 一级 二级",
  "GB 55037 第 5 章 耐火等级",
  "建筑分类 高度 27m 24m 耐火"
]
↓ 各自 embed + retrieve + 融合（RRF 或 max-pool）
```

**预期收益**：召回多样性翻倍，捕捉到原 query 偏离的章节
**工时**：3-4h（含 prompt 设计 + 融合逻辑 + 评测）
**成本**：每次问答多 1 次 LLM 调用（DeepSeek，约 +500ms TTFT）

### 路径 2 · Hybrid 检索（BM25 + 向量）

**问题**：BGE-M3 在专业术语上有语义偏差，但 BM25 对**精确关键词**很强（如 "5.1.3" "耐火极限" 等）。

**方案**：
```python
def hybrid_search(query, alpha=0.5):
    bm25_results = bm25_retrieve(query, top_k=20)
    vec_results = vector_retrieve(query, top_k=20)
    return rrf_fuse(bm25_results, vec_results, alpha)  # Reciprocal Rank Fusion
```

**预期收益**：补全 BGE-M3 错过的"含 expected_clause 编号或专业术语"的 chunks
**工时**：4-5h（含 BM25 索引建立 + 融合 + 评测）
**新依赖**：rank_bm25 库（轻量 ~0.5MB）

### 路径 3 · chunker 重做（长期）

**问题**：现有 chunker 用 `_dN` 后缀容忍切多次，导致内容重复。

**方案**（W3 D3/D4）：
- 移除 `_dN` 机制，改为 emit 前按 text-hash 全局去重
- 把 PDF 章节标题、上文 context 加进 chunk 的 metadata，丰富 embedding 输入

**新增依赖**：无
**预期收益**：数据库 -30~40%（按 GB 55037 推算 4773 → ~3000）

### 路径 4 · 切 Qdrant Docker（基础设施）

**问题**：本地文件锁让评测时必须 stop backend。

**方案**：
```yaml
# docker-compose.yml
services:
  qdrant:
    image: qdrant/qdrant:v1.11
    ports: ["6333:6333"]
    volumes: ["./data/qdrant_docker:/qdrant/storage"]
```
然后 `QDRANT_URL=http://localhost:6333`，retriever.py 已支持。

**工时**：1-1.5h

---

## 四、W3 一周规划（基于今晚诊断重排）

| 天 | 主线 | 目标数字 |
|---|---|---|
| **D1（今天）** | ✅ 5 轮诊断 + retriever dedup + 设计文档 | Hit@10 strict 2.6→5.3 |
| D2 | Query 改写（路径 1）| Hit@5 loose 47→55+? |
| D3 | Hybrid 检索（路径 2）| Hit@5 loose 55→65+? |
| D4 | 评测集 v3（修 expected_clause 容差）+ chunker 重做 | Hit@5 strict 5→20+? |
| D5 | Qdrant Docker + 切换 + 重新评测 | 工程债清零 |

W3 目标：**Hit@5 loose ≥ 65%**（剩余 15pp 留给 W4 攻"综合题 0%"和"对抗样本 0%"两块硬骨头）。

---

## 五、AIPM 启示（今晚收获）

### 启示 1 · "诊断要诚实"

最初假设 "OCR 错位 → 重 ingest" 是错的。如果不停下来做 5 轮诊断，今晚就会跑去搞 PaddleOCR/Marker 重 ingest，**最终发现解决不了主要问题**。

诊断时要遵守的原则：
1. **不下结论前先量化**（不仅看错例，要全库统计）
2. **每个假设都要能被数字证伪**
3. **当数字与直觉冲突时，相信数字**

### 启示 2 · "改了不涨"也是有价值的结论

dedup 改完 Hit@5 没动，看起来"白干"。但：
- 排除了一个潜在主因（节约后续诊断时间）
- top-10 strict +2.6pp 真实改善
- 为后续 query 改写 / hybrid 提供干净的基础设施

**AIPM 视角**：评测体系的价值不只是"算出涨了多少"，更是"算出哪些动作没用"——后者帮你停止浪费时间。

### 启示 3 · 评测数字告诉你"瓶颈在哪一层"

47.4% loose 与 2.6% strict 的巨大差距告诉我：
- 召回质量（找到对的 spec_code）47%
- 精确度（找到对的 clause）2.6%
- **召回层先攻**，因为精确度本身依赖召回成功

这是数据驱动决策的典型——没有数字，你以为"strict 这么低肯定是 OCR"，结果根本不是。

---

**文档版本**：v1.0
**最后更新**：2026-05-30
**对应阶段**：W3 Day 1 完成（5 轮诊断 + retriever dedup）
