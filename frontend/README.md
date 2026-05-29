# Frontend · 建景规规范知识问答助手

Vite + React 18 + TypeScript + Tailwind CSS v4 + zustand 的 SPA 前端。

> 详细规范见根目录 `CLAUDE.md` B.1（前端栈锁定）。本文件只讲怎么跑。

---

## 环境要求

- Node.js 18+（当前实测 24.14.1）
- npm 10+

## 启动

```bash
# 安装依赖
npm install

# 启动 dev server（默认 :5173，含 /api → localhost:8000 代理）
npm run dev

# 构建生产包
npm run build
```

**注意**：前端依赖后端 FastAPI 正在 `localhost:8000` 提供 `/api/chat` 与 `/api/health`。
启动后端：

```bash
cd ../backend
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 目录结构（CLAUDE.md B.2）

```
src/
├── pages/
│   └── Chat.tsx          # P2 问答主页（含输入框、消息列表、示例 query）
├── components/
│   ├── ChatMessage.tsx   # 单条消息（user / assistant，含流式光标）
│   └── CitationCard.tsx  # 引用卡片（规范号 + 条文号 + 强制性标）
├── stores/
│   └── chatStore.ts      # zustand 全局状态（消息列表 + isStreaming）
├── lib/
│   └── apiClient.ts      # fetch + ReadableStream 解析 SSE 帧
├── types/
│   └── chat.ts           # SSEEvent / Citation / ChatMessage 类型定义
└── App.tsx               # 根组件（当前仅渲染 ChatPage）
```

## SSE 事件结构（与后端 pipeline.py 对齐）

| 事件 | data 类型 | 说明 |
|---|---|---|
| `retrieval` | `{ n_candidates, n_kept, min_relevance }` | 检索阶段元信息 |
| `token` | `string` | 逐 token 流式文本 |
| `citations` | `Citation[]` | 引用列表（在 done 之前下发） |
| `fallback` | `string` | 兜底标识（chitchat/out_of_scope/no_result）|
| `done` | `{ ttft_ms, total_ms, tokens_out }` | 流结束 + 性能 |
| `error` | `string` | 异常 |

## 待补（W2/W3）

- 历史会话持久化（V2）
- shadcn/ui 组件库迁移
- 规范原文跳转页（P3 Spec.tsx）
- 暗黑模式
