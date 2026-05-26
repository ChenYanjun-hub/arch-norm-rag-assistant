# chunker.py 分块策略设计 · v0.1

> **状态**：✅ 已审定（2026-05-26）
> **作用域**：`backend/app/rag/chunker.py` 与 `backend/scripts/ingest.py` 的分块逻辑
> **下游依赖**：embedder · retriever · pipeline · 引用元数据展示
> **修改流程**：任何对硬约束或决策项的变更，必须更新本文档版本号并写明原因。

---

## 1. 硬约束（CLAUDE.md E.1，铁律）

| 项 | 值 |
|---|---|
| `primary_unit` | 「条款」（X.Y.Z 一级） |
| `max_chunk_size` | 800 字 |
| `min_chunk_size` | 50 字 |
| `table_separate` | True |
| `formula_separate` | True |
| `preserve_metadata` | True |

任何 chunk 丢失规范号 / 章节 / 条文号 / 页码 → P0 bug（CLAUDE.md 红线 2）。

---

## 2. 输入特征（43 部 PDF 共性）

国标 / 行业标准 / 地标的结构高度一致：

- **层级**：章 → 节 → 条（X / X.Y / X.Y.Z，最细可至 X.Y.Z.W）
- **强制性条文**：印刷上用黑体（PDF 字体属性 `bold=True`），常以「应 / 不应 / 严禁 / 必须」开头
- **表格**：标号「表 X.Y.Z」
- **公式**：标号「式 X.Y.Z」
- **附录·条文说明**：对正文条文的官方解释，价值高
- **OCR 状态**：43 部 PDF 全部已标 `_可搜索`，已 OCR；但仍可能有错字 / 错版

---

## 3. 算法流程

```
Phase A · 文本提取
  pymupdf 按页提取 text + blocks（坐标 / 字体 / 字号 / bold）
       ↓
Phase B · 结构识别
  - 章节标题：正则 ^\s*\d+(\.\d+)*\s+\S  + 字号较大
  - 条文号：  正则 ^\s*\d+(\.\d+){1,3}\s
  - 强制性：  bold 字体 OR 关键词「应/不应/严禁/必须」  ← 决策 3
  - 表格：    pymupdf.find_tables() + 正则「表 \d」
  - 公式：    正则「式 \d」
       ↓
Phase C · 切块
  - 以「条」为单元
  - > 800 字：按子项 1)2)3) 切，clause 加后缀 "5.0.3-1"  ← 决策 4
  - < 50 字：与同节下一条合并
  - 表格 / 公式 → 独立 chunk
       ↓
Phase D · 元数据注入
       ↓
Phase E · 输出 chunks/{spec_code}.json + 同步写 SQLite metadata 表
```

---

## 4. Chunk 数据结构

```python
@dataclass
class Chunk:
    chunk_id: str           # 主键："GB50180-2018#5.0.3"
    spec_code: str          # "GB 50180-2018"
    spec_name: str          # "城市居住区规划设计标准"
    chapter: str            # "5 居住区用地"
    section: str | None     # "5.0 一般规定"
    clause: str             # "5.0.3" 或 "5.0.3-1"
    type: Literal["clause", "table", "formula", "appendix"]
    text: str               # 原文（保留「应/不应」原词）
    page_start: int
    page_end: int           # 同页时 == page_start
    is_mandatory: bool
    domain: Literal["规划","建筑","景观","消防"]  # 见 spec_domain_mapping.md
    source_pdf: str         # 相对路径
    char_count: int
```

---

## 5. 已审定的 7 个决策

| # | 决策 | 选择 | 说明 |
|---|---|---|---|
| 1 | 规范全称 + 标准号来源 | **B · 文件名正则解析** | 配合人工映射表兜底 |
| 2 | domain 分类来源 | **A · 手维护映射表** | 见 `spec_domain_mapping.md` |
| 3 | 强制性条文识别 | **B · bold + 关键词** | 双重命中更鲁棒 |
| 4 | 超长条文切分 | **B · 按子项 1)2)3)，clause 加后缀** | Prompt 注入时附"同条其他子项" |
| 5 | 表格向量化 | **B · Markdown + LLM 一句摘要** | 仅 ingestion 时调用，约 43 × 几个表格 |
| 6 | 附录条文说明 | **A · 入库，type=appendix，共享 clause 号** | 引用时分别标注 |
| 7 | OCR 容错 | **A · 完全信任 OCR 文本** | W4 评测发现问题再补救 |

---

## 6. 实现完成后的自检清单

- [ ] 43 部 PDF 全部跑通无异常
- [ ] 抽样 10 条 chunk 人工检查：元数据正确率 ≥ 95%
- [ ] 强制性条文识别准确率 ≥ 90%（抽 50 条人工核）
- [ ] 表格不被切散：100%
- [ ] 单条 chunk size 分布报告（直方图）
- [ ] 总 chunk 数预估：43 部 × 200 条 / 部 ≈ 8,000–12,000 条

---

## 7. 明确不做（避免范围蔓延）

- ❌ 跨章节关联抽取（如「5.0.3 引用 4.2.1」）
- ❌ 图片 / 示意图 OCR
- ❌ 公式 LaTeX 化（先纯文本）
- ❌ 中英规范并存（仅中文）

---

## 8. 风险与已知问题

| 风险 | 缓解 |
|---|---|
| OCR 错字导致条文号识别失败 | 跑通后输出"识别失败的 PDF 列表"，人工抽查 |
| 跨页表格 | pymupdf `find_tables()` 跨页支持有限 → 检测到时记录 warning，后续单独处理 |
| 部分老规范无标准的 X.Y.Z 编号体系 | 退化为按段落切，clause 用 "P{页码}-{段号}" |
| 「征求意见稿」「局部修订条文」 | 在 metadata 标 `status=draft / partial`，检索时降权 |

---

**版本历史**
- v0.1 (2026-05-26)：初版，7 项决策全部按推荐选定
