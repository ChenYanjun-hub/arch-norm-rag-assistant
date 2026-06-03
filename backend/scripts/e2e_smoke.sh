#!/bin/bash
# W6 D4 bonus · 端到端 SSE smoke test（启示 61 落地）
#
# 启动后端后跑一次完整 RAG 流，validate SSE 协议格式 + 帧数 + 关键事件。
# 防 W6 D4 发现的 SSE CRLF bug 类协议层问题悄悄回归。
#
# 用法（先确保 backend 在 :8000 已起）：
#     bash backend/scripts/e2e_smoke.sh
#
# 退出码 0 = 全过；非 0 = 某项 assertion 失败

set -e

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
QUERY="${1:-居住区配套幼儿园的服务半径不应大于多少米？}"

echo "🔥 e2e_smoke：测试 $BACKEND_URL/api/chat"
echo "   query: $QUERY"
echo ""

# 1. health check
health=$(curl -s "$BACKEND_URL/api/health" || echo "")
if ! echo "$health" | grep -q '"status":"ok"'; then
    echo "❌ /api/health 不通：$health"
    exit 1
fi
echo "✅ health: $health"
echo ""

# 2. SSE 流测试
tmp=$(mktemp)
trap "rm -f $tmp" EXIT

curl -s -N -X POST "$BACKEND_URL/api/chat" \
    -H "Content-Type: application/json" \
    -d "{\"query\":\"$QUERY\"}" > "$tmp"

# 3. 校验协议格式（行尾兼容 LF / CRLF）
n_token=$(grep -c "^event: token" "$tmp" || true)
n_citations=$(grep -c "^event: citations" "$tmp" || true)
n_metadata=$(grep -c "^event: metadata" "$tmp" || true)
n_done=$(grep -c "^event: done" "$tmp" || true)
n_fallback=$(grep -c "^event: fallback" "$tmp" || true)
n_revised=$(grep -c "^event: revised_answer" "$tmp" || true)

echo "📊 帧数统计："
echo "   token:          $n_token"
echo "   citations:      $n_citations"
echo "   metadata:       $n_metadata"
echo "   revised_answer: $n_revised"
echo "   fallback:       $n_fallback"
echo "   done:           $n_done"
echo ""

# 4. assertions
errors=0

if [[ $n_token -lt 30 ]]; then
    echo "❌ token 帧数 $n_token < 30（疑似 SSE 协议 bug 或 LLM 调用失败）"
    errors=$((errors+1))
fi

if [[ $n_done -ne 1 ]]; then
    echo "❌ done 帧数 $n_done ≠ 1"
    errors=$((errors+1))
fi

# 正常 query 应该有 citations（fallback 没有），但允许 0（兼容 fallback 测试）
if [[ $n_citations -gt 1 ]]; then
    echo "❌ citations 帧数 $n_citations > 1（应该最多 1）"
    errors=$((errors+1))
fi

# W6 D4 集成校验
if [[ $n_metadata -ne 1 ]]; then
    echo "⚠️  metadata 帧数 $n_metadata ≠ 1（W6 D4 集成应有）"
fi

if [[ $errors -eq 0 ]]; then
    echo ""
    echo "✅ e2e_smoke 通过（token=$n_token / citations=$n_citations / done=$n_done）"
    exit 0
else
    echo ""
    echo "❌ e2e_smoke 失败 $errors 项 — 详见 $tmp 前 30 行："
    head -30 "$tmp"
    exit 1
fi
