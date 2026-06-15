"""POST /api/chat ── 流式问答接口（SSE）。

请求：
    POST /api/chat
    Content-Type: application/json
    {
        "query": "...",
        "session_id": "abc123",      // 可选，V2 多轮用
        "domain": "消防",            // 可选，限定规范类
        "spec_code": "GB 50180-2018" // 可选，限定单规范
    }

响应：text/event-stream，每行 `data: {...}\\n\\n`
    事件类型：retrieval / token / citations / fallback / done / error

CLAUDE.md D.4 性能要求：
    - 首字 ≤ 3s（pipeline 内部已保证）
    - LLM 中断时发 error 事件，前端能优雅恢复
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.models.schemas import ChatRequest
from app.rag.pipeline import run_rag_sync

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat")
async def chat(req: ChatRequest) -> EventSourceResponse:
    """流式问答端点。前端用 EventSource 或 fetch + ReadableStream 消费。"""
    logger.info(f"[api/chat] query={req.query[:60]!r} session={req.session_id}")

    if not req.query or not req.query.strip():
        raise HTTPException(status_code=400, detail="query 不能为空")
    if len(req.query) > 500:
        raise HTTPException(status_code=400, detail="query 超过 500 字符")

    def event_stream():
        """把 pipeline 的 dict 事件转为 SSE 'data: {json}' 帧。"""
        try:
            history = (
                [{"role": t.role, "content": t.content} for t in req.history]
                if req.history
                else None
            )
            for evt in run_rag_sync(
                req.query,
                domain_filter=getattr(req, "domain", None),
                spec_code_filter=getattr(req, "spec_code", None),
                history=history,
            ):
                # sse-starlette 接受 dict，会自动序列化 data 字段
                yield {
                    "event": evt["type"],
                    "data": json.dumps(evt.get("data", ""), ensure_ascii=False),
                }
        except Exception as e:  # pragma: no cover —— 兜底保护
            logger.exception(f"[api/chat] pipeline 异常: {e}")
            yield {
                "event": "error",
                "data": json.dumps(f"PIPELINE_FAILED: {e}", ensure_ascii=False),
            }

    return EventSourceResponse(event_stream())
