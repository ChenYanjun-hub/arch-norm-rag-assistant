"""检索：Qdrant 向量库召回（CLAUDE.md E.2）。

流程：query → embed → Qdrant top-k_rough=20 → 返回候选 chunks
后续由 reranker 精排到 top-5。

W2 实现。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# TODO(W2): 实现 retrieve_rough(query, top_k=20, domain_filter=None)
