"""RAG 端到端流程编排（CLAUDE.md E.4 判定优先级）。

流程（自上而下短路）：
    1. 输入校验（空/超长/敏感词）→ INPUT_*
    2. 闲聊识别 → 简短礼貌回应
    3. 模糊提问 → 主动追问
    4. 超范围（非 5 类规范）→ 提示替代渠道
    5. 敏感问题 → 引导咨询主管部门
    6. 涉及作废规范 → 提示已废止 + 现行版本
    7. 检索 + 重排 → 若结果空 → 兜底"未查询到"
    8. 正常生成 → 流式输出 + 引用 + 追问推荐

W2 实现。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# TODO(W2): 实现 async def run_rag(query: str) -> AsyncIterator[ChatChunk]
