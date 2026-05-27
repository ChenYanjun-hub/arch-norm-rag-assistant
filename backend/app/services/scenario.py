"""场景识别：判断用户输入属于哪种场景。

W2 简版：仅识别 3 类（足以覆盖大多数边角情况），其余 5 类 W3 再补：

    ✅ chitchat     —— 闲聊（你好/谢谢/再见类）
    ✅ out_of_scope —— 超范围（明显不属于 5 类规范的内容）
    ✅ normal       —— 正常 RAG 流程
    ⏸ ambiguous   —— 模糊提问（TODO W3）
    ⏸ sensitive   —— 敏感问题（TODO W3）
    ⏸ deprecated  —— 涉及作废规范（TODO W3）

判定优先级（CLAUDE.md E.4）：自上而下短路。
"""

from __future__ import annotations

import logging
import re
from typing import Literal

logger = logging.getLogger(__name__)

ScenarioType = Literal["chitchat", "out_of_scope", "normal"]

# ── 闲聊关键词（行级硬规则）──
_CHITCHAT_PATTERNS = [
    r"^(你好|您好|hi|hello|嗨|早上好|晚上好|下午好)[\s\?！？!~。.]*$",
    r"^(谢谢|多谢|感谢|thx|thanks?)[\s\?！？!~。.]*$",
    r"^(再见|拜拜|bye|goodbye)[\s\?！？!~。.]*$",
    r"^(你是谁|你是什么|介绍.{0,5}自己|你能.{0,3}什么)[\s\?！？!~。.]*$",
    r"^(测试|test|123|hello world)[\s\?！？!~。.]*$",
]
_CHITCHAT_RE = re.compile("|".join(_CHITCHAT_PATTERNS), re.IGNORECASE)

# ── 超范围关键词（明显不属于设计规范的话题）──
# 注意：宁错漏不错杀——这里只标命中度最高的几类
_OUT_OF_SCOPE_KEYWORDS = (
    # 个人 / 情感 / 闲谈
    "推荐", "推荐一下", "怎么样", "好不好", "好吃",
    # 编程 / 技术 / 其它领域
    "python", "代码", "怎么写", "bug", "报错",
    # 时事 / 八卦
    "新闻", "股票", "天气", "翻译",
    # 显然非规范类
    "做菜", "做饭", "电影", "游戏", "电视剧",
)


def detect_scenario(query: str) -> ScenarioType:
    """场景识别主入口。

    Args:
        query: 已经 strip + 长度校验过的用户 query

    Returns:
        ScenarioType
    """
    q = query.strip()

    # 1. 闲聊（精确正则匹配）
    if _CHITCHAT_RE.match(q):
        logger.info(f"[scenario] chitchat: {q[:30]!r}")
        return "chitchat"

    # 2. 超范围：明显非规范类关键词命中 且 query 短
    #    长 query 即便含这些词也可能是"防火"涉及到"代码"，先不动
    if len(q) <= 30:
        for kw in _OUT_OF_SCOPE_KEYWORDS:
            if kw in q.lower():
                logger.info(f"[scenario] out_of_scope (kw={kw!r}): {q[:30]!r}")
                return "out_of_scope"

    return "normal"
