"""引用提取：从 chunks 元数据组装 Citation 对象。

任何字段缺失都是 P0 bug（CLAUDE.md 红线 2）。
W2 实现。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# TODO(W2): 实现 build_citations(chunks: list[dict]) -> list[Citation]
