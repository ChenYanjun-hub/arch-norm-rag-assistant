"""场景识别：判断用户输入属于哪种场景（闲聊/模糊/超范围/正常等）。

服务 pipeline 的判定优先级（CLAUDE.md E.4）。
W2 实现。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# TODO(W2): 实现 detect_scenario(query: str) -> ScenarioType
