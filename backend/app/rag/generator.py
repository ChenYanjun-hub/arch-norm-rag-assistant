"""LLM 生成：DeepSeek V3（CLAUDE.md 附录锁定，不可换 GPT-4/Claude）。

使用 openai SDK 兼容模式调用 DeepSeek。
必须流式输出（stream=True），TTFT P95 ≤ 3s，总时长 P95 ≤ 15s。
超时 30s，失败重试 1 次。

W2 实现。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# TODO(W2): 实现 stream_generate(system, user_messages) -> AsyncIterator[str]
