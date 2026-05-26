"""GET /api/spec/{spec_code} ── 获取规范 PDF 文件（用于原文跳转）。

W3 实现。引用卡片点击 → 后端返回 PDF 流（含锚点 #page=N）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()

# TODO(W3): 按 spec_code 查询 metadata.db，返回对应 PDF 路径，流式输出文件
