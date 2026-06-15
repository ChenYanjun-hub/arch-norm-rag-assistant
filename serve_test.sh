#!/usr/bin/env bash
# 发他人测试 · 一键启动：后端 + 前端 + cloudflared 公网穿透
#
# 用法（在你自己的终端跑，保持开着）：
#   bash serve_test.sh
# 然后把输出里的 https://xxxx.trycloudflare.com 链接发给测试者。
# Ctrl+C 停止全部（隧道+前后端）。
#
# 注意：
#   - 测试期间本机须开着；测试者提问消耗你的 DeepSeek 额度，链接勿公开传
#   - 隧道 URL 每次重启会变（cloudflared 免费快速隧道特性）

set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 0. 确认无 eval/reindex 占 Qdrant 锁（本地文件模式单进程锁）
if ps aux | grep -E "run_quality_eval|reindex_from_chunks|ingest" | grep -v grep >/dev/null; then
  echo "⚠️  有 eval/reindex/ingest 在跑（占 Qdrant 锁），请先停再启服务。"; exit 1
fi

# 清理可能残留的旧进程
pkill -f "uvicorn app.main" 2>/dev/null
pkill -f "[v]ite" 2>/dev/null
sleep 1

# 1. 后端（FastAPI :8000）
cd "$ROOT/backend"
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/test_backend.log 2>&1 &
BACK=$!

# 2. 前端（Vite :5173）
cd "$ROOT/frontend"
npm run dev > /tmp/test_frontend.log 2>&1 &
FRONT=$!

# 退出时清理全部
trap 'echo; echo "🛑 停止中..."; kill $BACK $FRONT 2>/dev/null; pkill -f cloudflared 2>/dev/null; exit 0' INT TERM

# 等后端就绪（首次加载 BGE-M3 + reranker，约 30-60s）
echo "⏳ 等后端加载模型（首次约 30-60s）..."
for i in $(seq 1 45); do
  curl -s -m 2 localhost:8000/api/health >/dev/null 2>&1 && { echo "✅ 后端就绪"; break; }
  sleep 2
done
curl -s -m 2 localhost:8000/api/stats >/dev/null 2>&1 && echo "✅ 语料就绪" || echo "⚠️ /api/stats 未响应，查 /tmp/test_backend.log"

# 3. cloudflared 穿透（前台，打印公网 URL；Ctrl+C 停全部）
echo
echo "🌐 启动公网穿透 —— 下方出现的 https://xxxx.trycloudflare.com 就是发给测试者的链接："
echo "   （Ctrl+C 停止全部服务）"
echo
cloudflared tunnel --url http://localhost:5173
