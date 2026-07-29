"""边界兜底：返回各场景的标准回复（CLAUDE.md E.4 + 红线 4）。

W2 简版：3 类核心场景（chitchat / out_of_scope / no_result）
W3 D5 完整版（本次升级）：8 类全覆盖
  - chitchat / out_of_scope / no_result（已有）
  - input_empty / input_too_long（新增，从 pipeline error 路径迁移）
  - sensitive / deprecated / ambiguous（新增 W3 D5 主菜）

约束（CLAUDE.md 红线 4）：兜底回复绝不调 LLM 生成，必须是预设文案——
避免 LLM 自由发挥越界给"如何规避"类建议。
"""

from __future__ import annotations

from app.services.scenario import DEPRECATED_SPECS

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

# ── 输入为空（W3 D5 新增）──────────────────────
FALLBACK_INPUT_EMPTY = (
    "请输入您想查询的规范问题。\n\n"
    "示例：\n"
    "- 居住区配套幼儿园的服务半径不应大于多少米？\n"
    "- 高层民用建筑的耐火等级最低要求？"
)

# ── 输入超长（W3 D5 新增）──────────────────────
# 注：MAX_QUERY_LEN 跟 scenario 保持一致
FALLBACK_INPUT_TOO_LONG = (
    "您的问题过长（超过 4000 字符上限）。\n\n"
    "**建议拆分**成 2-3 个具体子问题分别提问，例如：\n"
    '1. 先查"目标设计对象的关键参数"（如服务半径、耐火等级）\n'
    '2. 再查"相关辅助参数"\n\n'
    "短而精的提问也能让答案更聚焦。"
)

# ── 敏感问题（涉及规避审查 / 绕过审批）W3 D5 新增 ────
# CLAUDE.md 红线 4：涉及合规结论必须引导咨询主管部门
FALLBACK_SENSITIVE = (
    "本助手不回答涉及**规避审查、绕开审批、违规操作**的咨询。\n\n"
    "合规判定属于规划主管部门和审图机构的职责范围，建议咨询：\n"
    "- 当地**规划/建设主管部门**\n"
    "- 有资质的**施工图审查机构**\n"
    "- 持证的**项目咨询单位**\n\n"
    "本助手仅提供现行规范的**原文条款查询**，不提供合规规避方案。\n"
    "如需查询某条具体规范的原文要求，欢迎重新提问。"
)

# ── 模糊提问（W3 D5 新增）──────────────────────
FALLBACK_AMBIGUOUS = (
    "您的问题信息不够具体，本助手难以匹配到准确的规范条文。\n\n"
    "请补充以下信息后重新提问：\n\n"
    "1. **专业领域**：规划 / 建筑 / 消防 / 景观\n"
    "2. **设计对象**：如居住区 / 幼儿园 / 高层建筑 / 防火门 / 绿地\n"
    "3. **查询参数**：如服务半径上限 / 耐火极限要求 / 最小宽度 / 退距\n\n"
    "**示例**：'居住区配套幼儿园的服务半径不应大于多少米？'"
)


# ── 作废规范（W3 D5 新增，动态文案）─────────────────
def build_fallback_deprecated(deprecated_code: str) -> str:
    """根据已废止 spec_code 生成提示文案。

    Args:
        deprecated_code: 用户 query 中提及的废止规范号（如 "GB 50180-93"）

    Returns:
        含废止号 + 现行替代号的提示
    """
    info = DEPRECATED_SPECS.get(deprecated_code)
    if not info:
        # 兜底：未在硬编码列表里，给通用提示
        return (
            f"您提到的《{deprecated_code}》可能已废止或被替代。\n\n"
            "建议先核实该规范的现行版本（可查国家标准全文公开系统 std.samr.gov.cn），"
            "再查询该现行版本的相关条文。\n\n"
            "本助手仅覆盖现行国标 / 行业标 / 地方标。"
        )

    return (
        f"您提到的《{info['name']}》{deprecated_code} 已被替代。\n\n"
        f"**现行版本**：《{info['name']}》{info['current']}（{info['year']} 年发布）\n\n"
        f"建议改问该现行规范的具体条文，例如：\n"
        f'"{info["current"]} 关于 XXX 的要求是什么？"\n\n'
        "本助手仅基于现行规范回答，不引用已废止条文。"
    )
