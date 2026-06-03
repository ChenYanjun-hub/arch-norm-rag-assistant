"""W6 D0：LLM 输出后处理 — 剥离"补充说明 / 另注 / 备注"等节。

背景：W5 D5 启示 52 证明 LLM 对"完整回答"的训练惯性会让它输出 chunks 外的
"补充说明"内容，prompt 写得再严约束都难根治。最稳是后处理代码层 strip 整段。

设计原则：
  1. 纯函数：input answer → output (cleaned, n_stripped) — 不依赖外部状态
  2. 保守剥离：只剥"补充说明"类节，不剥"依据/结论/原文引用"
  3. 按精度从高到低识别：标题节 > 段落标签 > 行内括注
  4. 完全独立模块，集成到 pipeline 的方式由调用方决定（streaming 策略）

集成方式（4 选 1，等用户决策）：
  A 流末批量替换：emit revised_answer 事件，前端覆盖
  B 完全放弃 streaming：等 LLM 完成 + 后处理后再 yield
  C stop sequences：用 OpenAI stop 参数阻止生成（前端无感）
  D 仅 metadata 警告：streaming 不动，metadata 标记 stripped_count

接口：
  strip_supplementary_sections(answer) -> (cleaned, n_stripped_chars)
"""

from __future__ import annotations

import re


# ── 识别模式 ────────────────────────────────────────────
# 精度排序：标题节（最稳）> 段落标签 > 行内括注（最易误伤）

# 模式 1：## / ### 标题节 — "## 补充说明" 整段到下一个同级标题或文末
_HEADING_PATTERN = re.compile(
    r"(?:^|\n)#{2,4}\s*(?:补充说明|另注|备注|附注|说明（[^）]*）|关于[^\n]{0,20}的?补充)[^\n]*"
    r"(?P<body>(?:\n(?!#{2,4}\s).*)*)",
    re.MULTILINE,
)

# 模式 2：粗体段落标签 — "**补充说明**：..." 整行段落（到空行或下一个 ** 段落）
_BOLD_LABEL_PATTERN = re.compile(
    r"(?:^|\n)\*\*(?:补充说明|另注|备注|附注|关于[^*]{0,20}的?补充|本助手补充)[^*]*\*\*\s*[：:]?\s*"
    r"(?P<body>(?:[^\n]*)(?:\n(?!\n)(?!\*\*)[^\n]*)*)",
    re.MULTILINE,
)

# 模式 3：以"**注意**："/"**说明**："/"**注**："开头的整段
# 注：这个模式较容易误伤合规提示（"涉及合规判断..."），保留模糊匹配 + 内容启发式
_INLINE_NOTE_PATTERN = re.compile(
    r"(?:^|\n)\*\*(?:另注|附注)\*\*\s*[：:]\s*"
    r"(?P<body>[^\n]*(?:\n(?!\n)(?!\*\*)[^\n]*)*)",
    re.MULTILINE,
)


# ── 主函数 ───────────────────────────────────────────────


def strip_supplementary_sections(answer: str) -> tuple[str, int]:
    """剥离 LLM 输出中的"补充说明 / 另注 / 备注"等节。

    Args:
        answer: LLM 完整回答

    Returns:
        (cleaned_answer, n_stripped_chars)：剥离后的回答 + 被剥离的字符数
    """
    if not answer:
        return answer, 0

    original_len = len(answer)
    cleaned = answer

    # 应用 3 个模式（按精度从高到低，避免误伤）
    cleaned = _HEADING_PATTERN.sub("", cleaned)
    cleaned = _BOLD_LABEL_PATTERN.sub("", cleaned)
    cleaned = _INLINE_NOTE_PATTERN.sub("", cleaned)

    # 清理：多个连续空行 → 2 个空行
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    n_stripped = original_len - len(cleaned)
    return cleaned, n_stripped


def detect_supplementary_sections(answer: str) -> list[str]:
    """检测但不剥离 — 返回匹配到的"补充说明"节摘要（用于 metadata 警告）。

    用于 W6 D1 集成方式 D（仅 metadata 警告，不实际剥离）。
    """
    matches: list[str] = []
    for pat, label in [
        (_HEADING_PATTERN, "heading"),
        (_BOLD_LABEL_PATTERN, "bold_label"),
        (_INLINE_NOTE_PATTERN, "inline_note"),
    ]:
        for m in pat.finditer(answer):
            preview = m.group(0)[:60].replace("\n", " ")
            matches.append(f"{label}: {preview}...")
    return matches
