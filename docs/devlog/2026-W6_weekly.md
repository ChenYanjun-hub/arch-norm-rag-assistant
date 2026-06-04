# W6 周报 · v1.0-mvp → v1.1 治理迭代 + 8 个新启示

**周期**：2026-06-03 W6 D1 ~ 2026-06-04 W6 D5（4 天 + 1 bonus）
**起点**：v1.0-mvp（综合 86.6 / veto 38 / dim7 76.7%）
**终点**：**v1.1**（综合 **88.3** / veto 27 / dim7 **87.9%** / 真顽疾 11）
**累计洞察**：53 → **61**（W6 沉淀 8 个）

---

## 一、本周战果（一句话）

> **YELLOW 限定场景上线的 RAG 系统综合质量提升 +1.7 分，编造问题降 11.2pp，
> 同时揭穿了一个活了 5 周的 SSE 协议 bug。**

---

## 二、量化结果对比

| 指标 | v1.0-mvp (W5 D5) | **v1.1 (W6 D4)** | Δ |
|---|---|---|---|
| 综合得分 | 86.6 | **88.3** | **+1.7** ⭐ |
| veto 单次 | 38 | **27** | **-11（29% ↓）** |
| 真顽疾交集 | 14（D3∩D5）| **11**（5 次交集）| **-3** |
| dim1 检索召回 | 84.5% | 83.6% | -0.9pp |
| dim2 精确条款 | 67.2% | 68.1% | +0.9pp |
| dim3 引用准确 | 98.3% | **99.1%** | +0.8pp |
| dim4 原文用词 | 86.2% | 88.8% | +2.6pp |
| dim5 数字精确 | 94.0% | 94.0% | 持平 |
| **dim7 不编造** | 76.7% | **87.9%** | **+11.2pp** ⭐⭐ |

判定：**仍 YELLOW**（综合 ≥ 75 ✅ AND veto = 0 ❌），但比 v1.0-mvp 大幅改善。

---

## 三、W6 日记摘要

### 🗓️ W6 D1（OCR 修反让 dim7 下降 5.2pp）

- 修 27 处 OCR 错字（坏境→环境 / 贼市→城市 / 改著→改善 / 政计→设计）
- 重新 ingest 4773 个 Qdrant points（220s）
- **反直觉**：综合 -1.0 / dim7 -5.2pp / veto +4
- **机制**：chunks 修干净后 LLM 更"理解" → 更敢"补充说明"
- **启示 54**：数据质量 ↑ ≠ 产品质量 ↑

### 🗓️ W6 D2（post_filter 集成 → 启示 52 完整闭环）

- 实现 `strip_supplementary_sections()` 集成到 pipeline 流末
- emit `revised_answer` 事件 + frontend 监听覆盖
- quality_eval 优先消费 revised_answer
- **核心战果**：dim7 71.6% → 82.8%（**+11.2pp**） / 综合 +1.6 / veto -8
- **启示 55**：post_filter 是 dim7 编造的工程化解药（启示 52 完整闭环）
- **启示 56**：主矛盾切换纪律（dim7 → dim4）
- **启示 57**：流式 + 后处理"双事件"集成模式

### 🗓️ W6 D3（few-shot 反例失败实验 + F.2 回滚）

- 尝试在 SYSTEM_PROMPT_MAIN 加 5 条用词反例（prompt 1204→2168 字 +80%）
- **结果**：dim4 +0pp（完全无效）/ 综合 -0.7 / dim3 -2.6pp / dim5 -1.7pp
- 长 prompt 副作用让其他维度下降
- **CLAUDE.md F.2 决策**：回滚 prompt 到 D7 状态
- **启示 58**：dim4 用词错也是训练惯性，prompt 治不了，需后处理

### 🗓️ W6 D4（align_modal_verbs 双重命中 + v1.1 tag）

- 实现 `align_modal_verbs()` 后处理函数（启示 58 工程化落地）
- 锚点匹配算法：从 chunks 抽量词上下文 → 改 answer 用词
- 方向词 guard：避免"宜小于"荒谬词（保守跳过语义翻转 case）
- 9 个新单测（29/29 全过）
- Pipeline 链式集成：strip → align → revised_answer
- Frontend 加治理透明度小栏（⚑/✂/✎）
- **核心战果**：dim4 +3.4pp / dim7 意外 +5.2pp（间接漂移）/ 综合 87.2 → **88.3** ⭐
- **打 v1.1 tag**
- **启示 59**：后处理改一维可能带动其他维度（正向漂移）
- **启示 60**：后处理链式叠加合规性

### 🗓️ W6 D4 bonus（SSE CRLF bug 揭穿 — 活了 5 周）

- 用户首次手动启动前端 demo → 反馈"前端不显示回答"
- 诊断：hex dump 看到 SSE 字节是 CRLF（`\r\n\r\n`）
- frontend `indexOf('\n\n')` 永远找不到帧分隔符 → token 帧全丢
- 修复：兼容 CRLF/LF + 写 `e2e_smoke.sh` 防回归
- **启示 61**：评测金字塔 5 层 — 缺 `e2e_smoke` 让协议层 bug 活 5 周 ⭐⭐

---

## 四、本周 8 个新启示（54-61）

| # | 启示 | 出处 |
|---|---|---|
| 54 | 数据质量 ↑ ≠ 产品质量 ↑（OCR 修反让 dim7 -5.2pp）| W6 D1 |
| 55 | post_filter 是 dim7 编造的工程化解药（启示 52 闭环）| W6 D2 |
| 56 | 顽疾主矛盾会随治理进度切换（dim7→dim4）| W6 D2 |
| 57 | 流式 + 后处理"双事件"集成模式 | W6 D2 |
| 58 | dim4 用词错也是训练惯性，prompt 治不了 | W6 D3 |
| 59 | 后处理改一维带动其他维度（正向漂移）⭐ | W6 D4 |
| 60 | 后处理链式叠加合规性（后处理矩阵）| W6 D4 |
| 61 | 端到端集成测试缺位让 SSE bug 活 5 周 ⭐⭐ | W6 D4 bonus |

---

## 五、CLAUDE.md F.2 纪律实战（本周 3 次）

| 实验 | 表面 Δ | 校正 Δ | 决策 | 备注 |
|---|---|---|---|---|
| W6 D1 OCR 修 | -1.0 | -1.0 | 保留 | 数据层修复客观正确，不回滚 |
| W6 D3 few-shot | -0.7 | -0.7 | **回滚** | F.2 标准案例（真下降 + 主目标失败）|
| W6 D4 align | +1.1 | +1.1 | 保留 | 历史最佳，打 v1.1 |

---

## 六、本周工程产出

### 新增文件（W6 D1-D5）

| 文件 | 行数 | 用途 |
|---|---|---|
| `backend/scripts/fix_chunks_ocr.py` | 110 | W6 D1 OCR 批量替换 |
| `backend/scripts/reindex_from_chunks.py` | 140 | 从 chunks JSON 重 embed |
| `backend/app/rag/post_filter.py` | ~280 | W6 D2 strip + W6 D4 align（含方向词 guard）|
| `backend/tests/test_post_filter.py` | ~280 | 29 个单测（覆盖 W5/W6 真实顽疾回归）|
| `backend/scripts/e2e_smoke.sh` | 75 | W6 D4 bonus 端到端 SSE 测试 |
| `docs/W6_plan.md` | ~150 | W6+ 路线图（含 ROI 排序）|
| `docs/dev_startup_cheatsheet.md` | ~150 | 前后端启动指南 |
| `docs/devlog/2026-W6_D1-D4.md + D5_weekly.md` | ~1300 | W6 4 篇日记 + 周报 |
| `docs/devlog/AIPM转行必备知识.md` | +600 行 | 启示 54-61 |

### 修改文件

| 文件 | 关键改动 |
|---|---|
| `backend/app/rag/pipeline.py` | 链式集成 strip → align → emit metadata + revised_answer |
| `backend/scripts/run_quality_eval.py` | 优先消费 revised_answer 做 Judge |
| `backend/app/core/prompts.py` | W6 D3 加 few-shot 反例（实验失败已回滚）|
| `frontend/src/types/chat.ts` | 加 PipelineMeta（含 post_filter_stripped_chars / modal_verb_corrections）|
| `frontend/src/stores/chatStore.ts` | switch case 加 metadata / revised_answer 处理 |
| `frontend/src/components/RightPanel.tsx` | 加 3 个治理角标（⚑/✂/✎）|
| `frontend/src/lib/apiClient.ts` | **W6 D4 bonus 修 SSE CRLF bug** ⭐ |
| `backend/data/chunks/*.json` | 24 chunks 27 处 OCR 修复 + ocr_fixed_v1 标记 |
| `backend/data/qdrant_local/` | 4773 points 重建 |

---

## 七、未解决的 11 条真顽疾（W7+ 候选）

| 类型 | n | 典型 case |
|---|---|---|
| dim4 用词 | 7 | Q139 宜→应（align 漏改）/ Q117 chunks 错字"不应低丁" / Q109 语义翻转跳过 |
| dim7 编造 | 5 | Q115 dangling [5] / Q125 编造 II 类区 / Q142 跨规范引用 |
| dim5 数字 | 3 | Q003 query↔chunks 不匹配 / Q102 单位错 |

**W7+ 候选治理**：
- 扩展 align 治方向词/搭配词
- chunks 二轮 LLM 校对错字
- `_align_numbers()` 后处理函数
- 评测扩 250 让统计稳定性 +30%

---

## 八、关键 commit 时间线

```
W5 D5 v1.0-mvp:    bea9932 (综合 86.6 / veto 38 / dim7 76.7%)
W6 D0 起步:        2f0b0dc (post_filter 函数 + OCR 工具骨架)
W6 D1 OCR 修:      7f54324 (反直觉 -1.0)
W6 D2 post_filter: e720520 (dim7 +11.2pp)
W6 D3 fewshot:     760d0fe (失败 + F.2 回滚)
W6 D4 align v1.1:  50f7d46 (综合 88.3 历史最佳)
W6 D4 bonus SSE:   f58b5a6 (CRLF bug + e2e_smoke)
```

---

## 九、W7+ 规划方向

**P0**（高 ROI）：
- 写 `_align_numbers()` 后处理治 dim5（启示 60 后处理矩阵第 3 层）
- 评测扩到 250 让 11 条真顽疾的统计意义更稳

**P1**（中 ROI）：
- demo 视频录制（answer_deck + demo_script 已就绪）
- chunks 二轮 LLM OCR 校对（Q117 类）

**P2**（低 ROI / 长期）：
- 扩展 align 治方向词 / 搭配词
- Judge prompt v2 防 Judge 自身 hallucinate

**不做项**：
- 引入 Vercel / Next.js（CLAUDE.md B.1 锁死）
- 换 LLM / 向量库
- 用户账号 / 付费（V2 范围）

---

## 十、一句话回顾

> **W6 是项目从"评测驱动开发"走到"工程化治理 + 透明度上线"的 4 天**：
> 把 W5 D3 元评测识别出来的"dim7 编造顽疾"用 post_filter 工程化解决（启示 55），
> 把 W6 D2 切换出的"dim4 用词错新主矛盾"用 align 工程化解决（启示 59-60），
> 顺手揭穿了 SSE 协议层 5 周的隐藏 bug（启示 61）。
>
> 综合 86.6 → 88.3，dim7 76.7% → 87.9%，**前端首次端到端可用**。
> 8 个新 AIPM 启示 全部落地到 v6.1。

---

**周报版本**：v1.0
**最后更新**：2026-06-04 W6 D5
**对应 tag**：v1.1
**累计**：6 周 / 28 篇日志 / 61 AIPM 洞察 / 70+ commits
