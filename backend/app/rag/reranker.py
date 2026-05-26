"""重排：BGE-Reranker-v2（CLAUDE.md 附录锁定，不可换 Cohere）。

输入：query + top-20 chunks
输出：top-5 chunks（按相关性降序），低于 min_relevance=0.3 的丢弃

W2 实现。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# TODO(W2): 实现 rerank(query, chunks, top_k=5, min_score=0.3)
