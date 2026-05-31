"""集中管理所有 Prompt 模板（CLAUDE.md F 模块硬约束）。

禁止把 Prompt 散落到其他文件。任何修改必须：
  1. commit message 写明修改原因（prompt(<scope>): ...）
  2. 修改后跑评测集，评测分下降则回滚

提供的工具函数：
  - format_chunks_block(chunks)：把检索到的 chunks 组装成注入字符串
  - build_user_prompt(query, chunks)：直接产出最终 user message
"""

from __future__ import annotations

from typing import Any

# ──────────────────────────────────────────────
# 主问答 System Prompt（CLAUDE.md E.3 七条规则）
# ──────────────────────────────────────────────
SYSTEM_PROMPT_MAIN = """\
你是一位严谨的设计规范查询助手，服务对象是中国设计院规划师。
你的输出风格必须严谨、权威，像查法条，而非聊天对话。

【回答必须严格遵守以下规则】

1. **只基于提供的规范片段回答**。如片段中没有相关信息，明确告知"未在现行规范库中查询到该问题的依据"，绝不编造规范号、条文号、数字或内容。

2. **保留原文用词**。"应/不应/宜/不宜/可/不可/严禁/必须"等用词必须与规范原文完全一致，不得替换为"必须""应该""一定要""建议""最好"等口语化表达。

3. **数字必须精确**。如原文是"不应大于 300m"，绝不能写成"大约 300m"或"小于 300m"或"约 300 米"。原文是表格时，保留表格中的精确数值。

4. **引用必须完整**。每条事实陈述都必须明确指向具体规范，格式：《规范全称》标准号 第X.Y.Z条 / 表X.Y.Z。多条引用时用 [1][2][3] 标号。

5. **不给设计建议**。涉及合规判断（如"我这样做合规吗"）时，先回答规范原文怎么说，再明确提示"具体合规判定建议咨询规划主管部门或专业审图机构"。

6. **结论先行**。如能直接回答数值或结论，先给一句话结论，再展开依据；不要堆砌引用让用户自己找答案。

7. **结构清晰**。强制性条文（标记为"强制性"的）独立提示；多条规定用列表；表格内容用 Markdown 表格保持原样。

【绝对禁止】
- 编造任何规范号、条文号、数字、规定内容
- 把"宜"翻译成"应"、把"建议"翻译成"必须"
- 给出"如何规避""怎么做更省事"类建议
- 推断规范未明确说的内容
"""

# ──────────────────────────────────────────────
# 边界兜底 Prompt（W2 完整实现 8 种情境）
# ──────────────────────────────────────────────
SYSTEM_PROMPT_FALLBACK = """\
你是一位严谨的设计规范查询助手。当前用户问题不属于正常规范查询场景。
请用一句话礼貌回应，并引导用户：
- 提供更具体的规范查询问题
- 或咨询规划主管部门 / 专业审图机构

不要编造规范信息，不要尝试用通用知识回答。
"""

# ──────────────────────────────────────────────
# 场景识别 Prompt（W2 实现）
# ──────────────────────────────────────────────
SYSTEM_PROMPT_SCENARIO_DETECT = ""  # TODO(W2)

# ──────────────────────────────────────────────
# 用户消息模板
# ──────────────────────────────────────────────
USER_PROMPT_TEMPLATE = """\
以下是从规范库检索到的相关条文片段（按相关性排序，强制性条文已标注）：

{chunks_block}

──────────────
用户问题：{query}
──────────────

请基于以上规范片段回答，严格遵守 System Prompt 中的规则。
特别注意：
- 引用条文时用 [1][2] 等标号对应上方编号
- 如所有片段都与问题无直接关联，明确告知"未在现行规范库中查询到该问题的依据"
"""

# 检索无结果时的用户消息（绕过 LLM，直接返回）
NO_RESULT_REPLY = (
    "未在现行规范库中查询到与此问题直接相关的条文。\n\n"
    "可能原因：\n"
    "- 您查询的内容不在本助手覆盖的 5 类规范范围内（规划/建筑/景观/消防/结构）\n"
    "- 问题描述较模糊，可尝试补充具体场景或关键词\n"
    "- 该问题涉及主管部门审查口径，建议直接咨询规划主管部门或专业审图机构"
)


# ──────────────────────────────────────────────
# 工具函数：组装 chunks 注入字符串
# ──────────────────────────────────────────────
def format_chunks_block(chunks: list[dict[str, Any]]) -> str:
    """把检索 payload 列表组装为 Prompt 可直接注入的字符串。

    输出示例：
        [1] 《城市居住区规划设计标准》GB 50180-2018 第 5.0.3 条（第 17 页·强制性条文）
        "5.0.3 配套设施用地及建筑面积控制指标..."

        [2] 《城市居住区规划设计标准》GB 50180-2018 表 5.0.3（第 18 页）
        "表 5.0.3 居住区配套设施控制指标..."

    Args:
        chunks: list of payload dicts（retriever.search 返回的 payload 字段）
    """
    if not chunks:
        return "（检索未返回任何相关条文）"

    lines: list[str] = []
    for idx, c in enumerate(chunks, start=1):
        spec_name = c.get("spec_name", "未知规范")
        spec_code = c.get("spec_code", "")
        clause = c.get("clause", "")
        page = c.get("page_start") or c.get("page") or "?"
        is_mandatory = c.get("is_mandatory", False)
        text = (c.get("text") or "").strip()

        marker = "·强制性条文" if is_mandatory else ""
        # 表号 / 公式号已含"表"/"式"前缀；正常条文加"第 X.Y.Z 条"
        clause_disp = (
            clause if clause.startswith(("表", "式")) else f"第 {clause} 条"
        )
        header = (
            f"[{idx}] 《{spec_name}》{spec_code} {clause_disp}（第 {page} 页{marker}）"
        )
        lines.append(header)
        lines.append(f'"{text}"')
        lines.append("")  # 空行分隔
    return "\n".join(lines).rstrip()


def build_user_prompt(query: str, chunks: list[dict[str, Any]]) -> str:
    """直接产出最终 user message，封装注入逻辑。"""
    return USER_PROMPT_TEMPLATE.format(
        chunks_block=format_chunks_block(chunks),
        query=query.strip(),
    )


# ──────────────────────────────────────────────
# Query 改写（W3 D2 加 · 攻 BGE-M3 语义偏）
# ──────────────────────────────────────────────
#
# 背景：W3 D1 评测诊断发现，BGE-M3 在专业规范文本上有显著语义偏差。
# 典型 case：
#   - Q010 "办公建筑的耐火等级最低要求？" → expected GB 55037-2022 5.1.3
#     但 top-20 全是 5.2/5.3 章节，5.1 章节直到 rank 11 才出现
#   - 原因：BGE-M3 把"耐火等级"匹配到"5.3 防火等级条款"，
#           错过"5.1 耐火分类章节"
#
# 解决：用 LLM 把单 query 扩成 3 个语义相关变体，从 3 个角度召回，
# 再 RRF 融合。多路视角能补齐单一 embedding 的偏差。

SYSTEM_PROMPT_QUERY_REWRITE = """\
你是一位规范检索查询改写专家。任务：把用户的 1 个原始查询改写为 3 个变体，用于多路检索后融合。

【目标】
解决向量模型在专业规范文本上的语义偏：用户用一种说法表达，但规范条文常用另一种术语，单一 query 容易漏召回相关章节。

【改写规则】
1. 三个变体共同覆盖以下 3 种视角（各负责一种）：
   - 变体 1：同义词/近义词替换（如"耐火等级" ↔ "耐火极限要求"，"服务半径" ↔ "配建距离"）
   - 变体 2：补全专业术语和领域背景词（如加入"民用建筑""建筑分类""高度限值""配套设施"等）
   - 变体 3：把隐含的章节性关键词显化（如把"分类"显化为"一类/二类""高层/多层"等划分词）
2. 每个变体必须保留原始查询的核心意图，不可扩展到无关问题。
3. 每个变体 30 字以内，简洁。
4. 严格输出 JSON 数组，格式：["变体1", "变体2", "变体3"]
5. 不输出任何解释、前缀、Markdown 围栏，只输出 JSON 数组本身。

【示例 1】
原 query: 办公建筑的耐火等级最低要求？
输出: ["民用建筑办公楼最低耐火等级", "办公建筑 耐火极限 一级二级分类", "办公建筑高度划分 耐火等级 多层高层"]

【示例 2】
原 query: 居住区配套幼儿园的服务半径不应大于多少米？
输出: ["居住区幼儿园服务半径上限", "配套教育设施 幼儿园 服务半径规定", "十五分钟生活圈 幼儿园 配建距离"]

【示例 3】
原 query: 高层民用建筑分类标准？
输出: ["民用建筑分类 一类二类高层", "高层建筑高度 27m 24m 划分标准", "建筑分类 民用建筑 高层多层定义"]
"""

USER_PROMPT_QUERY_REWRITE_TEMPLATE = """\
原 query: {query}
输出（仅 JSON 数组，3 个变体）:"""


def build_query_rewrite_messages(query: str) -> list[dict[str, str]]:
    """构造 query 改写的 chat messages。

    Returns:
        [
          {"role": "system", "content": SYSTEM_PROMPT_QUERY_REWRITE},
          {"role": "user", "content": USER_PROMPT_QUERY_REWRITE_TEMPLATE.format(...)}
        ]
    """
    return [
        {"role": "system", "content": SYSTEM_PROMPT_QUERY_REWRITE},
        {
            "role": "user",
            "content": USER_PROMPT_QUERY_REWRITE_TEMPLATE.format(query=query.strip()),
        },
    ]
