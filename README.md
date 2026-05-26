# 建景规规范知识问答助手

> 面向设计院规划师的 RAG 智能规范查询工具。覆盖规划/建筑/景观/消防/结构 5 类规范，每条回答附可追溯的规范引用与原文跳转链接。
>
> **产品定位**：AI 版规范法条数据库 · 严谨权威 · 绝不编造。

---

## 项目状态

- 当前阶段：MVP 开发期（W1–W5，共 5 周）
- 当前里程碑：W1 · 数据入库与 RAG 基础设施

---

## 仓库结构

```
.
├── CLAUDE.md              ★ 项目开发规范（所有代码生成/修改的硬约束，优先级最高）
├── README.md              本文件
├── backend/               FastAPI + LangChain + Qdrant 后端
│   └── README.md          后端启动说明
├── frontend/              React + TS + Vite 前端（W3 起步）
├── docs/
│   ├── PRD.md             产品需求文档
│   ├── Claude_Code_启动Prompt集合.md
│   ├── 准备日_To-Do清单.md
│   └── 初版评测集_使用说明.md
├── 规范库/                43 部规范 PDF（不入 Git）
│   └── …
└── md/                    原始文档归档（后续清理）
```

---

## 快速上手

详见 [`backend/README.md`](backend/README.md)。

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # 然后填入 DEEPSEEK_API_KEY
uvicorn app.main:app --reload
curl http://localhost:8000/api/health
```

---

## 核心红线（CLAUDE.md A.3）

1. **不编造**：chunks 之外的规范号/条文号/数字一律禁止
2. **引用必须精确**：规范全称 + 标准号（含年份）+ 条文号 + 跳转链接
3. **保留原文用词**：「应/不应/宜/不宜/可/不可」不可互换
4. **不给合规建议**：涉及合规结论引导用户咨询主管部门

技术栈锁定：DeepSeek V3 · BGE-M3 · BGE-Reranker-v2 · Qdrant · SQLite · FastAPI · React+TS+Vite。
未经讨论不得更换。

---

## License

内部课程作业项目，暂未开源。
