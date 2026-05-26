# CLAUDE.md · 项目开发规范

> 本文件是给 Claude Code 阅读的项目执行规范。任何代码生成、修改、重构都必须遵守本文件的约束。
> **本文件优先级 > Claude 默认行为**。如有冲突，以本文件为准。
> 完整产品需求详见 `/docs/PRD.md`，本文件只列开发执行层的硬约束。

---

## 模块 A · 项目上下文

### A.1 项目背景

本项目是 **建景规规范知识问答助手**——面向中型设计院规划师的 RAG 智能规范查询工具，使用自然语言查询规划/建筑/景观/消防/结构 5 类规范，**所有回答必须附带可追溯的规范引用与原文跳转链接**。

产品定位是 **"AI 版规范法条数据库"**，不是聊天伙伴。风格必须严谨权威，像查法条。

### A.2 当前阶段

- **MVP 开发期**（W1-W5）· 共 5 周
- 当前重点：跑通"能问 → 能答 → 能溯源"核心闭环
- 不做：账号体系、付费、协作、PDF 上传解读、其他专业规范

### A.3 核心约束（红线，绝对不可违反）

**🔴 RED LINE 1：不允许编造规范信息**
- LLM 回答中出现 chunks 中没有的规范号、条文号、数字 → 必须修复
- 兜底场景必须诚实告知"未查询到"，不得编造

**🔴 RED LINE 2：引用必须精确**
- 每条规范答案必须附：规范全称 + 标准号（含年份）+ 具体条文号 + 跳转链接
- 任何引用元数据错误都是 P0 bug

**🔴 RED LINE 3：强制性条文用语不可错**
- "应/不应" vs "宜/不宜" vs "可/不可" 不可混用
- 必须保留原文用词，不允许"翻译"或"通俗化"

**🔴 RED LINE 4：不写 chunks 之外的"建议"**
- LLM 不得自行给出"设计建议"或"规避方案"
- 涉及合规结论的，必须引导用户咨询主管部门

---

## 模块 B · 技术栈与目录结构

### B.1 技术栈（已锁定，未经讨论不可更换）

#### 后端
```
Python 3.11+
FastAPI                   # Web 框架
LangChain                 # RAG 编排
qdrant-client             # 向量库客户端
pymupdf (fitz)            # PDF 解析
sentence-transformers     # BGE-M3 embedding
openai (兼容 DeepSeek)    # LLM 调用
python-dotenv             # 环境变量
uvicorn[standard]         # ASGI 服务器
```

#### 前端
```
Node.js 18+
React 18 + TypeScript     # UI 框架
Vite                      # 构建工具
Tailwind CSS              # 样式
shadcn/ui                 # 组件库（可选）
zustand                   # 状态管理（轻量）
```

#### 基础设施
```
Qdrant 1.x (Docker)       # 向量数据库
SQLite                    # 元数据存储
Nginx                     # 静态文件服务
```

#### 第三方服务
```
DeepSeek API (主)         # base_url: https://api.deepseek.com, model: deepseek-chat
通义千问 Max (备)         # 切换用，结构同 OpenAI
```

**⚠️ 关键约束：**
- 不要引入未列出的库（除非明确请示并获得许可）
- 不要把 LLM 从 DeepSeek 换成 GPT-4 等"看起来更强"的模型
- 不要把 Qdrant 换成 Chroma/Milvus 等其他向量库
- 不要引入数据库 ORM（如 SQLAlchemy），SQLite 直接用 sqlite3 即可

### B.2 目录结构

```
prd-rag/
├── backend/                    # 后端代码
│   ├── app/
│   │   ├── main.py            # FastAPI 入口
│   │   ├── api/               # API 路由
│   │   │   ├── chat.py        # 问答接口
│   │   │   ├── spec.py        # 规范文件接口
│   │   │   └── eval.py        # 评测接口
│   │   ├── core/              # 核心配置
│   │   │   ├── config.py      # 环境变量、常量
│   │   │   └── prompts.py     # ★ 所有 Prompt 模板
│   │   ├── rag/               # ★ RAG 核心模块
│   │   │   ├── chunker.py     # PDF 分块
│   │   │   ├── embedder.py    # 向量化
│   │   │   ├── retriever.py   # 检索
│   │   │   ├── reranker.py    # 重排
│   │   │   ├── generator.py   # LLM 调用
│   │   │   └── pipeline.py    # 端到端 RAG 流程
│   │   ├── services/          # 业务服务
│   │   │   ├── scenario.py    # 场景识别
│   │   │   ├── fallback.py    # 边界兜底
│   │   │   └── citation.py    # 引用提取
│   │   ├── models/            # 数据模型
│   │   │   └── schemas.py     # Pydantic 模型
│   │   └── utils/             # 工具函数
│   ├── data/                  # 数据目录（不入 Git）
│   │   ├── specs/             # 规范 PDF
│   │   ├── chunks/            # 分块结果 JSON
│   │   ├── metadata.db        # SQLite 数据库
│   │   └── eval/              # 评测集 CSV
│   ├── scripts/               # 一次性脚本
│   │   ├── ingest.py          # PDF 入库
│   │   └── run_eval.py        # 跑评测
│   ├── tests/                 # 测试
│   ├── .env.example
│   ├── requirements.txt
│   └── README.md
│
├── frontend/                  # 前端代码
│   ├── src/
│   │   ├── pages/             # 页面
│   │   │   ├── Home.tsx       # P1 首页
│   │   │   ├── Chat.tsx       # P2 问答页
│   │   │   └── Spec.tsx       # P3 规范原文页
│   │   ├── components/        # 通用组件
│   │   │   ├── ui/            # 基础组件
│   │   │   ├── ChatMessage.tsx
│   │   │   ├── CitationCard.tsx
│   │   │   └── FollowUpChip.tsx
│   │   ├── stores/            # zustand 状态
│   │   ├── lib/               # API 封装、工具
│   │   ├── types/             # TypeScript 类型
│   │   └── App.tsx
│   ├── public/
│   ├── package.json
│   └── README.md
│
├── docs/                      # 文档
│   ├── PRD.md                 # 产品需求文档
│   └── design/                # 设计稿
│
├── CLAUDE.md                  # ★ 本文件
├── README.md                  # 项目说明
└── .gitignore
```

### B.3 文件放置规则

| 写什么代码 | 放哪里 |
|---|---|
| 新增 API 接口 | `backend/app/api/<功能名>.py` |
| 新增 RAG 算法 | `backend/app/rag/<算法名>.py` |
| 新增业务规则（如新场景识别）| `backend/app/services/<规则名>.py` |
| 新增 Prompt 模板 | `backend/app/core/prompts.py`（**禁止散落到其他文件**）|
| 数据模型（请求/响应）| `backend/app/models/schemas.py` |
| 一次性数据处理脚本 | `backend/scripts/<脚本名>.py` |
| 前端新页面 | `frontend/src/pages/<页面名>.tsx` |
| 前端通用组件 | `frontend/src/components/<组件名>.tsx` |

**⚠️ 禁止**：不要在根目录或随意位置创建文件。如果不知道放哪，先问。

---

## 模块 C · 编码规范

### C.1 命名规范

#### Python
- 文件名：snake_case，如 `retriever.py`
- 类名：PascalCase，如 `ChunkRetriever`
- 函数/变量：snake_case，如 `retrieve_chunks()`
- 常量：UPPER_SNAKE_CASE，如 `MAX_CHUNKS_PER_QUERY = 5`
- 私有成员：前导下划线，如 `_internal_method()`

#### TypeScript
- 文件名：组件用 PascalCase（`ChatMessage.tsx`），其他用 camelCase（`apiClient.ts`）
- 类型/接口：PascalCase，如 `interface ChatResponse`
- 函数/变量：camelCase，如 `const handleSend = () => {}`
- 常量：UPPER_SNAKE_CASE
- React 组件：PascalCase

### C.2 代码质量要求

#### 强制要求
- **类型注解**：Python 函数必须有完整 type hints；TS 必须有显式类型（不允许大量 `any`）
- **错误处理**：所有外部调用（LLM API、数据库、文件 I/O）必须有 try/except 或 try/catch
- **日志**：使用 `logging` 模块，关键节点（API 调用、检索、生成）必须 log，**不允许 `print` 调试**
- **环境变量**：所有密钥、URL、配置项必须走 `.env`，**禁止硬编码**
- **文档字符串**：公开函数必须有 docstring，说明参数、返回值、异常

#### 禁止事项
- ❌ 全局可变状态（除明确的应用单例如 db connection）
- ❌ 裸 `except:` 捕获所有异常
- ❌ 在生产代码中保留 `print`、`console.log` 调试
- ❌ 在前端代码里硬编码后端 URL（用 env 或 config）
- ❌ 拷贝粘贴代码超过 5 行（应抽函数）

### C.3 注释规范

- 注释解释**为什么**，不解释**做什么**（代码本身应该清晰）
- 关键业务逻辑（如分块策略、检索阈值）必须加注释说明依据
- TODO/FIXME 必须带具体描述：`# TODO(2026-W3): 此处需要支持表格 chunk`

---

## 模块 D · API 设计规范

### D.1 RESTful 风格

```
POST /api/chat              # 发起问答（流式）
GET  /api/spec/{spec_code}  # 获取规范文件
GET  /api/health            # 健康检查
POST /api/feedback          # 反馈（V2）
```

### D.2 请求/响应 schema

**所有 API 请求和响应必须用 Pydantic 模型定义**，位于 `backend/app/models/schemas.py`。

示例：

```python
# 问答请求
class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    session_id: str | None = None

# 引用（结构化）
class Citation(BaseModel):
    spec_name: str
    spec_code: str           # 如 "GB 50180-2018"
    clause: str              # 如 "表 5.0.3"
    page: int | None
    is_mandatory: bool
    original_text: str       # 原文摘引，不超过 50 字

# 问答响应（流式输出每个 chunk）
class ChatChunk(BaseModel):
    type: Literal["token", "citations", "follow_ups", "done", "error"]
    data: str | list[Citation] | list[str] | None
```

### D.3 错误处理

统一错误响应格式：
```json
{
  "error": {
    "code": "RETRIEVAL_FAILED",
    "message": "检索服务暂不可用，请稍后重试",
    "details": null
  }
}
```

错误码规范：
| 前缀 | 含义 |
|---|---|
| `INPUT_*` | 输入参数错误（400）|
| `RETRIEVAL_*` | 检索相关错误（500）|
| `LLM_*` | LLM 调用错误（502/504）|
| `STORAGE_*` | 数据库/文件错误（500）|

### D.4 流式输出

问答接口使用 **Server-Sent Events (SSE)** 协议：
```
Content-Type: text/event-stream

data: {"type":"token","data":"幼"}
data: {"type":"token","data":"儿"}
data: {"type":"token","data":"园"}
...
data: {"type":"citations","data":[...]}
data: {"type":"follow_ups","data":["...","..."]}
data: {"type":"done"}
```

**关键要求**：
- 首字必须在 3 秒内返回（性能监控）
- LLM 中断时必须发送 `error` 事件，前端能优雅恢复

---

## 模块 E · RAG 业务逻辑约束

### E.1 分块策略（铁律）

```python
# 分块的硬规则
CHUNKING_RULES = {
    "primary_unit": "条款",           # 以"条"为基本单元
    "max_chunk_size": 800,            # 单 chunk 字符数上限
    "min_chunk_size": 50,             # 太短的应合并
    "table_separate": True,           # 表格独立成块，不可切散
    "formula_separate": True,         # 公式独立成块
    "preserve_metadata": True,        # 每个 chunk 必须保留规范号/章节/条文号/页码
}
```

**绝对不能做**：
- ❌ 把一个"条"切成多个 chunk（除非超过 max_chunk_size）
- ❌ 把表格内容切散到多个 chunk
- ❌ 丢失 chunk 的元数据（规范号、条文号、页码）

### E.2 检索策略

```python
RETRIEVAL_CONFIG = {
    "top_k_rough": 20,           # 粗排召回数
    "top_k_rerank": 5,           # 精排保留数
    "min_relevance": 0.3,        # 相关性阈值，低于此触发兜底
    "filter_by_domain": True,    # 支持按规范类别过滤
}
```

**流程**：
1. 向量检索 Top-20（BGE-M3 + cosine）
2. Rerank 重排 Top-5（BGE-Reranker-v2）
3. 过滤相关性 < 0.3 的 chunks
4. 如剩余 chunks 数 = 0 → 触发兜底逻辑（A5 模块）

### E.3 生成阶段约束

**LLM 生成的系统提示词（System Prompt）核心约束**：

```
你是一位严谨的设计规范查询助手。回答必须严格遵守以下规则：

1. **只基于提供的规范片段回答**。如片段中没有相关信息，明确告知"未在现行规范库中查询到"，绝不编造。

2. **保留原文用词**。"应/不应/宜/不宜/可/不可"等用词必须与规范原文完全一致，不得替换为"必须""应该""一定"等口语化表达。

3. **数字必须精确**。如原文是"不应大于 300m"，绝不能写成"大约 300m"或"小于 300m"。

4. **引用必须完整**。每条事实陈述都必须明确指向具体规范（规范全称+标准号+条文号）。

5. **不给设计建议**。涉及合规判断的，明确提示"建议咨询规划主管部门或专业审图机构"。

6. **结论先行**。如能直接回答，先给结论再展开依据。

7. **结构清晰**。重要信息高亮，避免大段无结构文字。
```

**完整 Prompt 模板必须放在 `backend/app/core/prompts.py`，统一管理**。

### E.4 边界兜底逻辑

8 种子情境必须 100% 命中，对应处理参考 PRD 附录中边界兜底章节。

**判定优先级（自上而下）**：
1. 输入是否为空/超长/含敏感词 → INPUT_* 错误
2. 是否闲聊（如"你好"）→ 简短礼貌回应
3. 是否模糊提问（query 关键信息不全）→ 主动追问
4. 是否超范围（非 5 类规范）→ 提示替代渠道
5. 是否敏感问题（涉及规避审查）→ 引导咨询主管部门
6. 是否涉及作废规范 → 提示已废止 + 现行版本
7. 是否检索无结果（min_relevance 阈值过滤后为 0）→ 诚实告知
8. 否则进入正常生成流程

### E.5 性能要求（必须达标）

| 指标 | 目标 | 监控位置 |
|---|---|---|
| TTFT P95 | ≤ 3s | 前端 + 后端 log |
| 总响应时长 P95 | ≤ 15s | 同上 |
| 吐字速度 | ≥ 20 tokens/s | 后端 log |
| 错误率 | ≤ 1% | 后端 log |

**实现要求**：
- 必须使用流式输出（streaming）
- LLM 调用必须有 30 秒超时
- 失败必须有重试机制（最多 1 次）

---

## 模块 F · Prompt 工程规范

### F.1 Prompt 文件组织

所有 Prompt 集中在 `backend/app/core/prompts.py`，使用常量管理：

```python
SYSTEM_PROMPT_MAIN = """..."""           # 主问答 Prompt
SYSTEM_PROMPT_FALLBACK = """..."""       # 边界兜底 Prompt
SYSTEM_PROMPT_SCENARIO_DETECT = """..."""# 场景识别 Prompt
USER_PROMPT_TEMPLATE = """..."""         # 用户消息模板（含 chunks 注入）
```

### F.2 Prompt 修改规范

- 任何 Prompt 修改必须在 git commit message 中说明**修改原因**
- 修改后必须跑评测集验证，**评测分下降则回滚**
- 重要 Prompt 修改建议先在 50 条评测集上试跑

### F.3 Chunks 注入格式

```
以下是从规范库检索到的相关条文片段（按相关性排序）：

[1] 《城市居住区规划设计标准》GB 50180-2018 表 5.0.3（第 14 页·强制性条文）
"幼儿园服务半径不宜大于 300m，规模宜为 6~12 班..."

[2] ...

用户问题：居住区配套幼儿园的服务半径不应大于多少米？

请基于以上规范片段回答，严格遵守规则（见 System Prompt）。
```

---

## 模块 G · 任务执行规范

### G.1 何时该问，何时该做

**直接做（不必询问）**：
- 修复明确的 bug
- 按本文档规范创建新文件
- 实现 PRD 中已明确定义的功能
- 单元测试编写

**必须先问（停下来确认）**：
- 引入新的第三方库
- 修改技术栈（如换 LLM、换向量库）
- 修改 RAG 流程的硬约束（如改分块策略、改相关性阈值）
- 修改 Prompt 模板
- 大规模重构（涉及 > 5 个文件）
- 删除现有功能

### G.2 任务完成后必须给的反馈

完成每个开发任务后，**主动告诉我**：
1. **做了什么**：简短列出修改/新增的文件
2. **怎么验证**：给出测试命令或验证步骤
3. **风险点**：是否有不确定的地方需要后续关注
4. **下一步建议**：如有依赖任务，提示我

### G.3 不确定时的处理

- 如果遇到 PRD 或本文档未明确的需求点 → **停下来问，不要猜**
- 如果代码方案有 2 种以上合理选择 → **列出来让我选，不要默认替我决定**
- 如果发现 PRD 中的设计与实际开发存在矛盾 → **先指出矛盾，由我决策后再实施**

---

## 模块 H · Git 与提交规范

### H.1 分支策略

单人项目，简化：
- `main`：主分支，保持可运行状态
- `dev/<功能>`：开发分支，开发完成合并到 main
- 重要里程碑打 tag：`v0.1-mvp-w2`

### H.2 Commit message 格式

```
<类型>(<范围>): <简短描述>

[可选的详细说明]
```

**类型**：
- `feat`：新功能
- `fix`：bug 修复
- `refactor`：重构（不影响功能）
- `perf`：性能优化
- `docs`：文档
- `test`：测试
- `chore`：杂项（依赖、配置等）
- `data`：数据更新（规范库、评测集）

**范围**：
- `rag` / `api` / `ui` / `db` / `prompt` 等

**示例**：
```
feat(rag): 实现 BGE-M3 向量化与 Qdrant 入库
fix(api): 修复流式输出末尾缺失换行符问题
data(specs): 新增 GB 50016-2014 防火规范入库
prompt(main): 加强强制性条文用语约束
```

### H.3 .gitignore 必备项

```
# 环境变量
.env
.env.local
*.env

# Python
__pycache__/
*.pyc
.venv/
venv/

# Node
node_modules/
dist/
.next/

# 数据（避免误传规范 PDF 等大文件）
backend/data/specs/
backend/data/*.db
backend/data/chunks/*.json

# IDE
.vscode/
.idea/
*.swp

# OS
.DS_Store
Thumbs.db

# 日志
*.log
logs/
```

---

## 模块 I · 评测与质量保障

### I.1 评测集位置

- 评测集 CSV：`backend/data/eval/eval_set_v1_50.csv`
- 评测脚本：`backend/scripts/run_eval.py`

### I.2 评测时机

| 时机 | 评测规模 | 通过标准 |
|---|---|---|
| 每完成一个 RAG 模块 | 20 条小样本 | 检索 Hit Rate@5 ≥ 80% |
| 每周末 | 50 条 | 综合得分 ≥ 70 |
| W4-W5 集中评测 | 250 条 | 综合得分 ≥ 75 · 一票否决 0 |

### I.3 评测指标

参考 PRD 第二部分评测体系。代码中评测函数必须实现：
- 检索层：Hit Rate@K, Recall@K, MRR, NDCG@K
- 生成层：基于 7 维度的人工/LLM Judge 打分

---

## 模块 J · 调试与排查规范

### J.1 必须有的日志点

```python
# RAG pipeline 关键节点
logger.info(f"[chat] received query: {query[:50]}...")
logger.info(f"[retrieval] top_k_rough={len(rough_results)}, top_k_rerank={len(reranked)}")
logger.info(f"[generation] ttft={ttft_ms}ms, total_tokens={total_tokens}")
logger.warning(f"[fallback] triggered: scenario={fallback_type}")
logger.error(f"[llm_api] call failed: {error}")
```

### J.2 性能监控数据格式

每次请求结束输出 JSON 日志：
```json
{
  "timestamp": "2026-05-25T10:30:00Z",
  "session_id": "abc123",
  "query": "...",
  "ttft_ms": 2300,
  "total_ms": 12500,
  "tokens_in": 450,
  "tokens_out": 380,
  "retrieval_hits": 5,
  "fallback_triggered": false,
  "error": null
}
```

### J.3 常见问题排查路径

| 现象 | 排查顺序 |
|---|---|
| 答案不准确 | 1. 看检索召回的 chunks 是否相关 2. 看 Prompt 是否被 LLM 正确遵守 3. 看分块是否切错 |
| 速度慢 | 1. 看 TTFT 是不是 LLM 慢 2. 看检索阶段是否瓶颈 3. 看 Rerank 是否过重 |
| 引用错误 | 1. 看 chunks 元数据是否完整 2. 看 Prompt 中引用格式约束 3. 看后处理是否丢失字段 |
| 流式中断 | 1. 看 LLM API 是否超时 2. 看前端 SSE 连接 3. 看是否有未处理异常 |

---

## 附录 · 关键决策快速参考

| 决策项 | 选择 | 不要换成 |
|---|---|---|
| LLM | DeepSeek V3 | GPT-4 / Claude / 文心 |
| Embedding | BGE-M3 | OpenAI text-embedding |
| Rerank | BGE-Reranker-v2 | Cohere Rerank |
| 向量库 | Qdrant | Chroma / Milvus / Pinecone |
| 元数据库 | SQLite | PostgreSQL / MySQL |
| 后端 | FastAPI | Flask / Django |
| 前端 | React + TS + Vite | Next.js / Vue |
| 样式 | Tailwind | CSS-in-JS / SCSS |

---

## 最后：一句话总结

> **Claude Code 的目标**：在 PRD 定义的产品方向下，按本规范产出可执行、可维护、可验证的代码。
>
> **不可越界**：业务红线（不编造、引用精确、用语精确）+ 技术红线（不擅自换技术栈）+ 协作红线（不确定时停下来问）

---

**文档版本**：v1.0
**最后更新**：2026-05-25
**维护人**：项目负责人

如本文档与 PRD 冲突，以本文件为准（本文件优先解决执行层歧义）。
如本文档需修改，提交 commit 时使用 `docs(claude): ...` 格式。
