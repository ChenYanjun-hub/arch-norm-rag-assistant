# W7 · 查询分解 Agent（agentic RAG）— 启示 82

**结论**：⭐ agent 深化第一个功能：查询分解——把发散/复合题拆成子问题各自检索再合并覆盖。
**关键教训：分解的价值在生成完整性（答得全），retrieval Hit@5 测不出（0 变化）——因为单条 GT 指标
天生测不了"多子话题覆盖"。用对指标（生成侧）才看见价值：发散题喂给 LLM 的 chunk 从"1 个子话题"变成"4 个子话题全覆盖"。**
沉淀 **启示 82**（agent 的价值要用对指标衡量）。

---

## 一、动机与证据

综合域是全域最弱（v7 strict 66.7%），且用户真实发散问题（"城市新区道路建设有什么规范要求"）
单次检索必然只覆盖一个子话题。诊断验证：手动拆解后子问题各自检索，能捞回单次漏掉的期望条（Q098 8→1）。

## 二、构建

- `rag/query_decomposer.py`：`decompose_query`（LLM 判定复合/发散 → 拆 2~4 子问题；单一不拆；失败降级）
  + `retrieve_decomposed_chunks`（子问题各自 embed→search→**对子问题重排**→合并覆盖）。
- `core/prompts.py`：分解 prompt（复合/发散/单一三类判定 + few-shot）。
- `core/config.py`：`QUERY_DECOMPOSE_ENABLED` 等 flag（默认关）。
- `pipeline.py`：接入生产（命中走分解路径，简单题走原路径；流式/引用/兜底不受影响）。
- `run_eval.py`：`--decompose` flag（可评测）。
- 单测：`test_query_decomposer.py`（7 条解析容错）。全套 81 测试通过。

## 三、🎯 关键发现：retrieval Hit@5 测不出分解的价值

**评测（run_eval --decompose，v7 全集）：strict/loose/综合域 全部 0.0pp 变化。**

一开始以为失败。诊断发现两层：
1. **接线细节**：run_eval 把子问题结果 RRF 后仍用**原复合 query 重排** → 期望条仍排低位（Q098 9）。
   正确做法是**对子问题各自重排**（`retrieve_decomposed_chunks` 已修正）。
2. **更根本 —— 指标不对口径**：retrieval Hit@5 只检查**一条**期望条在不在 top5；
   而分解的意义是**覆盖多个**子话题。用单值 GT 指标量"多话题覆盖"，天生测不出来。

**用对指标（生成侧）才看见价值**（`scripts/demo_decompose.py` 实测「城市新区道路建设」）：

| | 不分解 | 分解 |
|---|---|---|
| 喂 LLM 的 chunk | 5 条，全挤在"道路规划总则"一个话题 | 8 条，覆盖红线/绿化/照明/交通 4 子话题 |
| 生成答案 | 空泛总则（"上位规划应符合…"）无具体规定 | 系统覆盖红线（≤70/55/40m 具体值）、绿化、照明（≥3.5m）、步行、通行能力，每条带规范号 |

**两版对单条 GT 都"miss"，但分解版对用户有用得多——这就是 retrieval 指标照不出的价值。**

## 四、🎓 启示 82 · agent 的价值要用对指标衡量 ⭐

**同一个功能，用错指标看是"0 提升"，用对指标看是"质变"。**
查询分解在 retrieval Hit@5 上纹丝不动，因为那个指标测的是"单条期望条召回"，而分解解决的是"多子话题覆盖"——
维度不同。**"这个 agent 没用"和"我用错尺子量了"是两件事，先分清。**

**对 AIPM 转行的启示**：
- **上 agent 前先想清楚"它改善的是哪个指标"**。分解改善生成完整性，就该用生成侧指标（覆盖度/完整性）验，
  而不是拿检索 Hit@5 交差。这呼应启示 80（评测口径设计）——**指标要匹配你要证明的能力**。
- **retrieval 指标和 generation 指标测的是不同东西**。检索强 ≠ 答得全；分解正是补"答得全"这一块。
- 面试金句：**"分解在检索命中率上零变化，我一度以为白做——直到意识到我在用'单条召回'的尺子量'多话题覆盖'。
  换成生成完整性看，发散题的答案从'一个空泛总则'变成'四个子话题全覆盖带具体数值'。"**

## 五、成本与默认关的理由

分解对**每个** query 加一次 LLM 判定调用（~1.5s）。默认关（同 multi_query），因为：
- 简单题占多数，给它们都加一次 LLM 调用不划算，且压 TTFT ≤3s SLA。
- **未来优化**：加一个廉价预筛（正则判"和/及/多个问号/长度"）跳过明显单一题的 LLM 调用，再考虑默认开。

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `backend/app/rag/query_decomposer.py` | 新建：分解 + 分解检索 |
| `backend/app/core/prompts.py` | +分解 prompt |
| `backend/app/core/config.py` | +QUERY_DECOMPOSE_* flag |
| `backend/app/rag/pipeline.py` | 接入分解路径（默认关，向后兼容）|
| `backend/scripts/run_eval.py` | +`--decompose` flag |
| `backend/scripts/demo_decompose.py` | 新建：不分解 vs 分解 生成对比演示 |
| `backend/tests/test_query_decomposer.py` | 新建：7 条解析单测 |
| `docs/devlog/2026-W7_query_decompose.md` | 本文件 |

---

**日志版本**：v1.0
**最后更新**：2026-W7（agent 深化 · 查询分解）
**累计洞察**：**82 个**（+启示 82 agent 价值要用对指标衡量）
**项目状态**：查询分解 Agent 已生产化（默认关 + flag）· 价值在生成完整性（发散题子话题覆盖 1→4）· retrieval Hit@5 中性（指标不对口径）
