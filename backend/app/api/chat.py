"""POST /api/chat ── 流式问答接口（SSE）。

W2 实现。本文件目前仅为占位，避免 import 错误。
依赖：app.rag.pipeline.run_rag()  ← W2 完成
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()

# TODO(W2): 实现 SSE 流式问答端点
