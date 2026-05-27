"""边界兜底：返回各场景的标准回复（CLAUDE.md E.4 + 红线 4）。

W2 简版：实现 3 类核心场景对应的兜底文案，由 pipeline 在 LLM 调用前短路。
W3 完整版：8 类全覆盖 + LLM 改写润色。
"""

from __future__ import annotations

# ── 闲聊 ─────────────────────────────────────
FALLBACK_CHITCHAT = (
    "你好，我是建景规规范知识问答助手，专注规划/建筑/景观/消防 4 类设计规范的查询。\n\n"
    "你可以这样提问：\n"
    "- 居住区配套幼儿园的服务半径不应大于多少米？\n"
    "- 防火墙的耐火极限要求？\n"
    "- 城市道路绿化的种植设计标准？\n\n"
    "试着问问看？"
)

# ── 超范围 ───────────────────────────────────
FALLBACK_OUT_OF_SCOPE = (
    "该问题不属于本助手的服务范围。\n\n"
    "本助手仅覆盖：**规划 / 建筑 / 景观 / 消防** 4 类设计规范（共 39 部国标/行业标/地方标）。\n\n"
    "如需查询其他领域的问题，请使用对应专业工具或咨询相关主管部门。"
)

# ── 检索无结果（已在 prompts.py NO_RESULT_REPLY，此处复用） ──
from app.core.prompts import NO_RESULT_REPLY  # noqa: E402,F401

FALLBACK_NO_RESULT = NO_RESULT_REPLY
