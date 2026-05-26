"""向量化：BGE-M3（CLAUDE.md 附录锁定，不可换 OpenAI embedding）。

支持两种调用方式：
  - 本地 sentence-transformers（推荐，避免依赖第三方 API）
  - 远程 HTTP（备选，便于资源受限环境）

W1 实现。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# TODO(W1): 加载 BGE-M3 模型，提供 embed_texts(list[str]) -> list[list[float]]
