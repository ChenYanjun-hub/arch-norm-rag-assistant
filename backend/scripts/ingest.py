"""一次性脚本：扫描 data/specs/ 下的 43 部规范 PDF，分块 → 向量化 → 入 Qdrant + 元数据入 SQLite。

用法：
    cd backend && python -m scripts.ingest [--rebuild]

W1 实现。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def main() -> None:
    # TODO(W1): 实现完整 ingestion 流水线
    raise NotImplementedError("W1 实现")


if __name__ == "__main__":
    main()
