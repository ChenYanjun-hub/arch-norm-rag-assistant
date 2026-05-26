# Backend · 建景规规范知识问答助手

FastAPI + LangChain + Qdrant 的 RAG 后端服务。

> 详细规范见根目录 `CLAUDE.md`，产品需求见 `docs/PRD.md`。本文件只讲怎么跑起来。

---

## 环境准备

### 1. Python 环境（3.11+）

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 环境变量

```bash
cp .env.example .env
# 然后用编辑器把 DEEPSEEK_API_KEY 等字段填上真实值
```

### 3. Qdrant 向量库（Docker）

```bash
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 \
  -v $(pwd)/data/qdrant_storage:/qdrant/storage \
  qdrant/qdrant
```

### 4. 规范库 PDF

骨架阶段已通过软链接挂载到 `data/specs/`，指向项目根的 `规范库/` 文件夹（43 部 PDF）。
无需额外操作；如需替换/新增规范，直接放进 `规范库/` 即可。

---

## 启动服务

```bash
# 开发模式（热重载）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 健康检查
curl http://localhost:8000/api/health
# → {"status":"ok","version":"0.0.1-skeleton"}
```

---

## 主要脚本

| 脚本 | 用途 | 阶段 |
|---|---|---|
| `python -m scripts.ingest` | 扫描 PDF → 分块 → 向量化 → 入库 | W1 |
| `python -m scripts.run_eval --set v1_50` | 跑评测集打分 | W4 |

---

## 目录速查

```
backend/
├── app/
│   ├── main.py            # FastAPI 入口
│   ├── api/               # 路由：chat / spec / eval
│   ├── core/              # config / prompts（★ Prompt 集中地）
│   ├── rag/               # chunker / embedder / retriever / reranker / generator / pipeline
│   ├── services/          # scenario / fallback / citation
│   ├── models/schemas.py  # Pydantic 模型
│   └── utils/
├── data/                  # 不入 Git
│   ├── specs/             # → 软链接到 ../../规范库/
│   ├── chunks/            # 分块结果 JSON
│   ├── eval/              # 评测集
│   └── metadata.db        # SQLite
├── scripts/               # 一次性脚本
└── tests/
```

详见 `CLAUDE.md` 的 B.2 与 B.3 节。
