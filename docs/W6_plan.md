# W6+ 路线图 · 力争 YELLOW → GREEN

> **基础**：v1.0-mvp（commit `bea9932`，tag `v1.0-mvp`）综合 86.6 / veto 14 三次交集 / YELLOW
> **目标**：veto 三次交集 → 0 → GREEN（综合 ≥ 75 AND veto = 0）
> **起点**：2026-06-04（W5 完结后）

---

## 一、W6+ 主线（按 ROI 排）

| # | 任务 | 优先级 | 预期收益 | 需用户决策 |
|---|---|---|---|---|
| 1 | 后处理 strip "补充说明 / 另注" 整段 | **P0** | dim7 76.7% → 90%+ / 顽疾 veto -8~10 | ⚠️ 集成方式 |
| 2 | chunks OCR 校对（人工抽样 + LLM 自校）| P0 | 评测准度 +5pp / Judge 偏差 -10% | ⚠️ 修复策略 |
| 3 | Judge prompt v2（防 Judge hallucinate）| P1 | Judge 准确率 60-70% → 85%+ | ✅ 改 prompt 必问 |
| 4 | 评测集扩到 250 条 | P1 | 统计稳定性 +30% | ✅ 新增 query 必审 |
| 5 | quality_eval --repeat N 跑交集模式 | P0 | 落地启示 53（三次交集）| ❌ 直接做 |
| 6 | 前端 React UI 完整化 | P2 | 现仅 CLI / API | ✅ 大规模新建 |
| 7 | 答辩 Demo 录屏视频 | P2 | 答辩物料 | ⚪ 选做 |
| 8 | chunks 表格分块改进 | P3 | 跨页表格 / 复杂结构 | ⚠️ 改分块策略 |

---

## 二、P0 任务详解

### P0-1 · 后处理 strip 补充说明节（治 dim7 编造顽疾）

**原理**：W5 D5 启示 52 证明"补充说明"是 LLM 训练惯性，prompt 写得再严无用。最稳妥是后处理代码层 strip 整段。

**实现位置**：`backend/app/rag/post_filter.py`（新文件）

**接口**：
```python
def strip_supplementary_sections(answer: str) -> tuple[str, int]:
    """剥离 LLM 输出中的"补充说明 / 另注 / 备注"等节。

    返回 (cleaned_answer, n_stripped_chars)
    """
```

**识别模式**（按精度从高到低）：
1. `## 补充说明` / `### 补充说明` 整段（到下一个 `##` 或文末）
2. `**补充说明**：...` 整行段落
3. `**注意**：` / `**说明**：` / `**另注**：` / `**备注**：`
4. `（注：...）` / `(注：...)` 行内括注

**集成方式选项**（需用户确认）：
- **A 流末批量替换**：LLM 完成后扫 answer，剥离后通过 `revised_answer` 事件 emit（前端要支持）
- **B 完全放弃 streaming**：等 LLM 完成 + 后处理后再 yield tokens（牺牲 UX）
- **C stop sequences**：用 OpenAI stop 参数让 LLM 看到"## 补充说明"就停止（前端无感）
- **D 仅 metadata 警告**：streaming 不动，metadata 标记 stripped_count（不实际剥离）

### P0-2 · chunks OCR 校对

**背景**：W5 D5 启示 49 — PDF OCR 错字会污染 Judge 判断。Q090 "定牌" / Q084 类似情况都是 chunks 本身错。

**实现位置**：`backend/scripts/check_chunks_quality.py`（新文件）

**启发式检测**（不依赖人工）：
- 单字符不合常理（如 "定牌" 这种孤立非标准词）
- 连续标点 / 异常 unicode
- 已知错字模式库（"游患"等已知错字）
- 数字 / 字母混排异常（如"1〇" 误为 "10"）

**修复策略选项**（需用户确认）：
- **A 人工抽样修复**：用工具扫出 ~100 可疑 chunks，人工抽 30 个修
- **B LLM 自校对**：让 DeepSeek 校对可疑 chunks（成本高，需小心）
- **C 重新 OCR**：对 PDF 重跑 OCR（用更好的引擎）
- **D 不修，仅标记**：在 chunk metadata 加 `ocr_quality=low`，让 Judge 知道这条不可信

### P0-3 · quality_eval --repeat N（落地启示 53）

**原理**：单次 LLM Judge 50% 噪声，三次交集才是真 veto。把这个落地为工具参数。

**实现位置**：`backend/scripts/run_quality_eval.py`（修改）

**接口**：
```bash
python -m scripts.run_quality_eval --csv ... --limit 0 --repeat 3
```

输出三次跑的 union / intersection / majority vote 三种 veto 集，并在 markdown 报告里给出。

**无需用户决策** — 落地已确认的方法论。

---

## 三、P1 任务详解

### P1-1 · Judge prompt v2（防 Judge hallucinate）

W5 D3 元评测发现 Judge 凭印象造错字（"游患"/"宜案用"/"路同密度"）。

**修订方向**（已在 W5 D3 报告写过）：
- 加 "Judge 自我警惕 hallucination" 4 条约束
- chunks 截断 200 → 500 字
- 用 5 条 chunks 而不是 3 条
- 加 "不确定时给 1 分" 避险条款

**需用户确认**（CLAUDE.md F.2 改 prompt 必问 + 跑评测验证）

### P1-2 · 评测集扩到 250

W5 D2 时主动选了不扩（v4.5 116 条已暴露问题）。W6+ 答辩 / B2B 推广前应扩到 250 增加统计稳定性。

**需用户审核**：100 条新 query（按"温柔挑战 5 步法"批量过审）

---

## 四、W6 D1 起步建议

**今晚（用户回来后）确认 3 个决策点后启动**：

1. **集成方式 A/B/C/D**：后处理 strip 集成到 pipeline 的策略
2. **OCR 修复策略 A/B/C/D**：是否修 + 怎么修
3. **W6 D1 当日任务排序**：先做 P0-1 / P0-2 / P0-3 哪个

**今晚（用户没回来前）已开始**：
- ✅ 写 W6 路线图（本文件）
- ✅ 实现 `post_filter.py` 纯函数 + 单测（不集成，等用户选集成方式）
- ✅ 写 `check_chunks_quality.py` 骨架（不实际修，等用户选修复策略）

---

## 五、W6 完成标准（YELLOW → GREEN）

| 验收项 | 当前 (v1.0-mvp) | W6 目标 |
|---|---|---|
| 综合得分 | 86.6 | ≥ 88 |
| **veto 三次交集** | **14** | **≤ 3** |
| dim7 不编造 | 76.7% | ≥ 90% |
| Judge 准确率 | 60-70% | ≥ 85% |
| 评测集 | 150 | 250（可选）|
| **判定** | **YELLOW** | **GREEN** |

---

## 六、不做项（明确边界）

- ❌ 引入 Vercel / Next.js（CLAUDE.md B.1 锁死）
- ❌ 换 LLM 到 GPT-4 / Claude
- ❌ 换向量库
- ❌ 加用户账号体系 / 付费 / 协作（V2 范围）
- ❌ 大规模重写后端（保持 FastAPI 不动）

---

**文档版本**：v1.0
**最后更新**：2026-06-03 W5 D5 结题后
**对应 commit**：未 push（等 W6 D0 起步任务完成一起 commit）
