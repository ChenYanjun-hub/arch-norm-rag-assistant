"""POST /api/eval ── 评测接口（内部用，跑评测集打分）。

W4 实现。读取 backend/data/eval/eval_set_v1_50.csv，批量过 pipeline 并打分。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()

# TODO(W4): 实现评测批跑端点
