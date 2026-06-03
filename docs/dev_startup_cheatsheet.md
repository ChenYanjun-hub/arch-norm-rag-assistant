# 本地开发启动 Cheat Sheet · 前后端 + Demo 访问

> 5 分钟从零到能在浏览器看到 RAG 系统输出

---

## 🚨 重要前置条件

Qdrant 用 **local file mode**（单进程锁）— **同一时间只能有一个进程读 Qdrant**：

- ✅ 后端 FastAPI 跑（占锁）→ 前端可用
- ❌ quality_eval 跑（占锁）→ 后端起不来
- ❌ 后端跑 + 跑 quality_eval → 冲突报错

**启动前必须先确认 quality_eval 已结束**：
```bash
ps aux | grep run_quality_eval | grep -v grep
# 没输出 = 没在跑，可以启动
```

如果有进程：等 watcher 通知或手动 `kill <PID>`（不推荐，会丢评测进度）。

---

## 1️⃣ 启动后端（FastAPI on :8000）

```bash
cd /Users/Zhuanz/Documents/项目开发/建景规规范问答助手/backend
.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**验证后端起来**：
- 看到 `INFO: Application startup complete.`
- 浏览器打开 `http://localhost:8000/docs` 看 OpenAPI Swagger（FastAPI 自带）
- 或 `curl http://localhost:8000/api/health` 看健康检查

**初次启动会加载 BGE-M3 + Reranker 模型**（~30-60s 首次）。

---

## 2️⃣ 启动前端（Vite dev server on :5173）

**另开一个终端**：

```bash
cd /Users/Zhuanz/Documents/项目开发/建景规规范问答助手/frontend
npm run dev
```

**验证前端起来**：
- 看到 `Local: http://localhost:5173/`
- 浏览器打开 `http://localhost:5173/`

Vite proxy 配置已经把 `/api/*` 转发到 `localhost:8000`，前端代码用相对路径调 `/api/chat`。

---

## 3️⃣ 推荐 demo query 清单（验证 W6 D4 集成）

按你之前 W5 D5 deck 的 demo_script.md 顺序，**重点关注 metadata 区域**（看 W6 D2/D4 集成是否生效）：

### A. 强制条文（最稳，dim7 治理后干净）
```
居住区配套幼儿园的服务半径不应大于多少米？
```
预期：答案含"宜为 300m~500m"（用词跟 chunks 原文一致）、引用 GB 50180-2018 表 5.0.3。

### B. 看 W6 D2 post_filter 是否生效（应该没"补充说明"节）
```
办公建筑照明的照度标准值是多少？
```
预期：W5 D3 时这条触发 dim7（编造"设计室 500lx"），W6 D2 post_filter 应该 strip 掉。

### C. 看 W6 D4 align_modal_verbs 是否生效
```
建筑采光与照明系统的控制设计要求？
```
预期：之前 W6 D3 Q077 触发 dim4（"宜→应"），W6 D4 align 应该自动改回"宜采用"。

### D. 边界 fallback
```
你好
```
预期：礼貌简短回应，不去检索规范库。

```
如何规避消防审查
```
预期：拒绝 + 引导咨询主管部门。

---

## 4️⃣ 看 W6 集成的隐藏数据（metadata 事件）

打开浏览器 DevTools → Network → 选 `chat` 请求 → 看 EventStream：

每条 query 流的末尾会有：

```
event: metadata
data: {
  "dangling_count": 0,
  "n_citations_in_answer": 3,
  "n_chunks_available": 5,
  "post_filter_stripped_chars": 47,
  "post_filter_applied": true,
  "modal_verb_corrections": 2
}
```

字段解读：
- `dangling_count` > 0 → LLM 编造了越界 [N]（W5 D4 监控）
- `post_filter_stripped_chars` > 0 → 剥离了"补充说明"节（W6 D2 治理）
- `modal_verb_corrections` > 0 → 量词被自动改回 chunks 原词（W6 D4 治理）

如果有 `event: revised_answer`，那是 post_filter 净化后的最终回答，**会覆盖之前 token 流式打出的内容**。前端 UI 会在末尾"轻微一刷"。

---

## 5️⃣ 常见问题

### Q1: 后端启动报"Address already in use"
`lsof -i :8000` 看占用进程，`kill <PID>`。

### Q2: Qdrant 报"already locked"
有 quality_eval 在跑。`ps aux | grep run_quality_eval` 看 PID，等它结束或 `kill`。

### Q3: 前端打开但 query 报 502
后端没起 / 后端起来但还在加载 BGE-M3。等 30-60s。

### Q4: DeepSeek API 报 "API key 错误"
检查 `backend/.env` 里 `DEEPSEEK_API_KEY` 是否正确。

### Q5: 前端组件什么样？
当前是简单的 Chat UI（zustand store + 流式渲染）。还没做 PDF 跳转、域 filter UI 等。是 MVP 级别。

---

## 6️⃣ 录 demo 视频时的额外建议

1. **后端 log 显示在副屏**：让观众看到 dangling / post_filter / modal_verb 实时触发
2. **DevTools Network 截图**：展示 metadata 事件中的隐藏数据 — 透明度的核心证据
3. **对比 W5 vs W6 同一 query**：先用 git checkout 切到 v1.0-mvp tag 跑一次（看会编造），再切回 main 跑一次（看治理后干净）—— 但需要重 ingest，成本高

---

## 7️⃣ 一键启动脚本（可选，方便录屏）

如果觉得手动两步麻烦，可以写：

```bash
# start_dev.sh（放项目根）
#!/bin/bash
set -e

# 后端
cd backend
.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
cd ..

# 等后端起来
echo "等后端启动（BGE-M3 加载需 ~30s）..."
sleep 30

# 前端
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

echo "✅ 后端 PID=$BACKEND_PID, 前端 PID=$FRONTEND_PID"
echo "停止：kill $BACKEND_PID $FRONTEND_PID"
echo "浏览器访问 http://localhost:5173/"

wait
```

---

**当前 W6 D4 状态**：quality_eval 跑批中（PID 10760，~44/116），跑完后即可启动。
**地址**：`http://localhost:5173/`（前端） · `http://localhost:8000/docs`（后端 API 文档）
