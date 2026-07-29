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

import difflib
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


# ──────────────────────────────────────────────
# W6 D4 · 量词对齐（治 dim4 用词错训练惯性，启示 58 落地）
# ──────────────────────────────────────────────
#
# 背景：W6 D3 失败实验证明 5 条 few-shot 反例对 dim4 用词错完全无效
# （+0pp / 综合 -0.7）。dim4 错与 dim7 编造同源 — LLM 标准化训练惯性，
# prompt 治不了。必须靠后处理代码层 diff chunks 原词 → 自动校正。
#
# 算法：Anchor-Match
#   1. 从 chunks 提取所有量词位置 + 前后 N 字上下文（"anchor"）
#   2. 同样从 LLM answer 提取
#   3. 对每个 answer anchor，找 chunks anchors 中匹配度最高的
#   4. 如 chunks 量词 ≠ answer 量词 + 匹配度足够高 → 用 chunks 量词替换
#
# 量词法定语义层级（按强度从高到低）：
#   严禁 / 必须 > 不应 / 不得 > 应 > 不宜 > 宜 > 不可 > 可
#
# **按长度从长到短匹配**，避免 "不应" 被识别为 "应"（子串问题）

MODAL_VERBS = [
    "严禁", "必须",      # 最强
    "不应", "不宜", "不得", "不可",  # 否定性量词（长度 2，优先）
    "应", "宜", "可",    # 肯定性量词（长度 1，最后）
]

_MODAL_PATTERN = re.compile(
    "|".join(re.escape(v) for v in sorted(MODAL_VERBS, key=lambda x: -len(x)))
)


def _extract_modal_anchors(text: str, ctx_len: int = 8) -> list[tuple[int, str, str, str]]:
    """从 text 中提取所有量词的 anchor：(pos, prefix, verb, suffix)。

    prefix = 量词前 ctx_len 字
    suffix = 量词后 ctx_len 字

    避免子串匹配（"不应" 不会被切成 "不" + "应"），靠 _MODAL_PATTERN
    按长度从长到短匹配 + non-overlapping iter 保证。
    """
    anchors: list[tuple[int, str, str, str]] = []
    last_end = 0
    for m in _MODAL_PATTERN.finditer(text):
        pos = m.start()
        if pos < last_end:  # 跳过被前一个长量词吃掉的位置
            continue
        verb = m.group(0)
        prefix = text[max(0, pos - ctx_len):pos]
        suffix = text[pos + len(verb):pos + len(verb) + ctx_len]
        anchors.append((pos, prefix, verb, suffix))
        last_end = pos + len(verb)
    return anchors


def _match_chars_tail(s1: str, s2: str) -> int:
    """两个字符串从右向左匹配的连续相同字符数。用于 prefix（量词前的 context）。"""
    count = 0
    for c1, c2 in zip(reversed(s1), reversed(s2)):
        if c1 == c2:
            count += 1
        else:
            break
    return count


def _match_chars_head(s1: str, s2: str) -> int:
    """两个字符串从左向右匹配的连续相同字符数。用于 suffix（量词后的 context）。"""
    count = 0
    for c1, c2 in zip(s1, s2):
        if c1 == c2:
            count += 1
        else:
            break
    return count


# W6 D4：方向词集合 — 用于检测"语义翻转 case"
# 如 chunks "宜大于"、answer "不应小于"，简单替换量词会产出"宜小于"荒谬词
# 保守策略：方向词不一致时跳过，不改这种 case（让 dim4 仍标记错，但不会变错）
_DIRECTION_CHARS = {"大", "小", "高", "低", "多", "少", "长", "短"}


# 引号内内容（中英文双引号 / 直角引号），用于识别"引述用户提问"的片段
_QUOTED_RE = re.compile(r'[“"「『]([^”"」』\n]{4,})[”"」』]')


def find_query_echo_spans(
    answer: str,
    query: str,
    *,
    min_ratio: float = 0.90,
) -> list[tuple[int, int]]:
    """找出 answer 中「引号内 + 与用户 query 高度重合」的区间 —— 即**引述用户提问**的部分。

    为什么需要（2026-W7 实测 bug）：
        用户问"服务半径**不应**大于多少米"，LLM 答"未查询到'服务半径不应大于多少米'的直接依据"，
        align_modal_verbs 按 chunks 把这里的"不应"校正成了"宜"——**改的是用户的提问，不是规范陈述**，
        读起来像助手听错了问题。为守红线 3 而生的后处理器，在错误语境下自己改坏了量词。

    为什么要「引号 + 高相似度」双条件（只用其一都不够）：
        - 只看相似度：会误伤"答案恰好与提问用词相同的规范陈述"
          （问"绿地率不应低于多少" → 答"居住区绿地率不应低于30%"，这句该被校正）。
        - 只看引号：答案里引用**规范原文**也带引号，那些恰恰**需要**与 chunks 对齐。

    min_ratio=0.90 的依据（在 1802 条存档评测答案上实测，不是拍脑袋）：
        引号内含量词、且与 query 相似度 ≥0.6 的候选共 14 条，分布出现干净断层——
          · 0.98：唯一一条**真·引述用户提问**（Q001）
          · ≤0.79：其余 13 条全是**引用规范原文**（因提问就是围绕该条文，用词自然重合）
        取 0.90 恰好切在断层上：修好真 bug，且不挡住那 13 条的红线校正。
        方向上宁可漏保护、不可误保护——误保护会拦下红线 3 的量词校正（有害），
        漏保护只是退回原行为（无新增伤害）。

    Returns:
        [(start, end), ...] answer 中受保护、不参与量词校正的字符区间。
    """
    q = (query or "").strip()
    if not q or not answer:
        return []
    spans: list[tuple[int, int]] = []
    for m in _QUOTED_RE.finditer(answer):
        inner = m.group(1)
        if difflib.SequenceMatcher(None, q, inner).ratio() >= min_ratio:
            spans.append((m.start(1), m.end(1)))
    return spans


def align_modal_verbs(
    answer: str,
    chunks_texts: list[str],
    *,
    min_match_chars: int = 5,
    query: str | None = None,
) -> tuple[str, int]:
    """W6 D4：自动校正 answer 中的量词使其与 chunks 一致。

    保守策略：
    - 只在 prefix tail + suffix head 至少匹配 min_match_chars 字时改
    - 方向词不一致（如"大" vs "小"）跳过，避免产出"宜小于"荒谬词
    - 防止误伤 LLM 总结句、概括陈述
    - W7：跳过"引述用户提问"的片段（见 find_query_echo_spans），避免改坏用户的问题

    Args:
        answer: LLM 完整输出
        chunks_texts: 检索到的 chunks 原文列表
        min_match_chars: prefix + suffix 至少匹配多少字才认为是"同一规范条文"
        query: 用户原始问题（可选）。传入后会保护答案中"引述该问题"的片段不被校正；
            不传则行为与 W6 D4 完全一致（向后兼容）。

    Returns:
        (aligned_answer, n_corrections)：校正后 + 改动数
    """
    if not answer or not chunks_texts:
        return answer, 0

    # 1. 从所有 chunks 提取量词锚点
    chunks_anchors: list[tuple[str, str, str]] = []  # (prefix, verb, suffix)
    for text in chunks_texts:
        for _pos, prefix, verb, suffix in _extract_modal_anchors(text):
            chunks_anchors.append((prefix, verb, suffix))

    if not chunks_anchors:
        return answer, 0

    # 2. 从 answer 提取量词锚点
    answer_anchors = _extract_modal_anchors(answer)

    # 2.5 保护"引述用户提问"的片段：这些不是规范陈述，改了等于篡改用户的问题
    protected = find_query_echo_spans(answer, query or "")

    def _is_protected(pos: int) -> bool:
        return any(s <= pos < e for s, e in protected)

    # 3. 对每个 answer anchor，找 chunks 中最匹配的
    corrections: list[tuple[int, str, str]] = []  # (pos, old_verb, new_verb)
    for a_pos, a_prefix, a_verb, a_suffix in answer_anchors:
        if _is_protected(a_pos):
            continue
        best_match = 0
        best_chunk_verb: str | None = None
        for c_prefix, c_verb, c_suffix in chunks_anchors:
            pref_match = _match_chars_tail(a_prefix, c_prefix)
            suff_match = _match_chars_head(a_suffix, c_suffix)
            total_match = pref_match + suff_match
            if total_match < min_match_chars or total_match <= best_match:
                continue
            # W6 D4 保守：方向词不一致 → 跳过这个匹配（避免"宜小于"荒谬词）
            if (a_suffix and c_suffix
                    and a_suffix[0] in _DIRECTION_CHARS
                    and c_suffix[0] in _DIRECTION_CHARS
                    and a_suffix[0] != c_suffix[0]):
                continue
            best_match = total_match
            best_chunk_verb = c_verb

        if best_chunk_verb and best_chunk_verb != a_verb:
            corrections.append((a_pos, a_verb, best_chunk_verb))

    if not corrections:
        return answer, 0

    # 4. 按位置倒序替换（避免位置偏移）
    aligned = answer
    for pos, old_verb, new_verb in sorted(corrections, key=lambda x: -x[0]):
        # 防御：验证 pos 处确实是 old_verb（万一被前面的替换扰乱）
        if aligned[pos:pos + len(old_verb)] == old_verb:
            aligned = aligned[:pos] + new_verb + aligned[pos + len(old_verb):]

    return aligned, len(corrections)


# ──────────────────────────────────────────────
# W7 D1 · 数字对齐（后处理矩阵第 3 层 · 治 dim5 数字精确）
# ──────────────────────────────────────────────
#
# 背景：W6 D4 align_modal_verbs 已治 dim4 用词错（启示 60 后处理矩阵）。
# 启示 60 预测：后处理可叠加 — 第 3 层治 dim5 数字精确。
#
# 算法：跟 align_modal_verbs 同样的 Anchor-Match：
#   1. 从 chunks 提取所有 "数字+单位" token（如 "300m" / "1.5m²" / "35%"）
#   2. 从 answer 同样提取
#   3. anchor 匹配（prefix tail + suffix head ≥ min_match_chars）
#   4. 数字不一致 → 改回 chunks 原数字
#
# 保守策略：
#   - 数字+单位作为整体 token（"300m" 不会拆成 "300" 和 "m"）
#   - 单位不一致也视为不一致（如 "3.0m" vs "3.0m²" 缺平方）
#   - 方向词 guard：chunks 在数字前是"大于"，answer 是"小于" → 跳过
#     （避免改成 "小于 300"但语义跟原文相反）
#   - 范围数字 "300m~500m" 在 regex 内会拆成两个独立 anchor，各自匹配

# 数字 + 单位 token 模式
# 单位：m / cm / mm / km / hm / m² / m³ / hm² / % / ° / 度 / 人 / 套 / 班 / 户 / 床 / kg / t / 级
_NUMBER_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)"              # 数字（整数或小数）
    r"\s*"                            # 可选空格
    r"(?:m[²³]?|cm|mm|km|hm[²³]?|%|°|度|人|套|班|户|床|kg|t|级)?"  # 可选单位
)

# 方向词集合（数字前出现）— 用于 anchor 反向匹配防误改
_NUMBER_DIRECTION_CHARS = {"大", "小", "高", "低", "多", "少", "长", "短", "等"}


def _extract_number_anchors(text: str, ctx_len: int = 8) -> list[tuple[int, str, str, str]]:
    """从 text 提取所有数字 anchor：(pos, prefix, number_with_unit, suffix)。

    number_with_unit 是 "300m" / "1.5%" / "35%" 这种整体 token，
    保留原文空格状态（normalize 留给上层）。
    """
    anchors: list[tuple[int, str, str, str]] = []
    for m in _NUMBER_PATTERN.finditer(text):
        token = m.group(0).strip()
        if not token or not any(c.isdigit() for c in token):
            continue
        pos = m.start()
        prefix = text[max(0, pos - ctx_len):pos]
        suffix = text[pos + len(m.group(0)):pos + len(m.group(0)) + ctx_len]
        anchors.append((pos, prefix, token, suffix))
    return anchors


def align_numbers(
    answer: str,
    chunks_texts: list[str],
    *,
    min_match_chars: int = 5,
) -> tuple[str, int]:
    """W7 D1：自动校正 answer 中的数字使其与 chunks 一致。

    保守策略：
    - 数字+单位整体作为 token（"3.0m" vs "3.0m²" 算不一致）
    - 方向词 guard：prefix 末字含方向词且不一致时跳过
    - min_match_chars=5：保证只改"同一句话"里的数字

    Args:
        answer: LLM 输出（建议是 align_modal_verbs 之后的 aligned_answer）
        chunks_texts: 检索到的 chunks 原文
        min_match_chars: prefix + suffix 至少匹配多少字

    Returns:
        (aligned_answer, n_corrections)
    """
    if not answer or not chunks_texts:
        return answer, 0

    chunks_anchors: list[tuple[str, str, str]] = []
    for text in chunks_texts:
        for _pos, prefix, num, suffix in _extract_number_anchors(text):
            chunks_anchors.append((prefix, num, suffix))

    if not chunks_anchors:
        return answer, 0

    answer_anchors = _extract_number_anchors(answer)
    corrections: list[tuple[int, str, str]] = []  # (pos, old_token, new_token)

    for a_pos, a_prefix, a_num, a_suffix in answer_anchors:
        best_match = 0
        best_chunk_num: str | None = None
        for c_prefix, c_num, c_suffix in chunks_anchors:
            # 完全相等的不算（不需要改）
            if c_num.replace(" ", "") == a_num.replace(" ", ""):
                continue
            pref_match = _match_chars_tail(a_prefix, c_prefix)
            suff_match = _match_chars_head(a_suffix, c_suffix)
            total_match = pref_match + suff_match
            if total_match < min_match_chars or total_match <= best_match:
                continue
            # 方向词 guard：prefix 末字含方向词不一致时跳过
            # (chunks "大于 300m"，answer "小于 300m" 不该改成 "大于 300m" 因为语义反)
            if (a_prefix and c_prefix
                    and a_prefix[-1] in _NUMBER_DIRECTION_CHARS
                    and c_prefix[-1] in _NUMBER_DIRECTION_CHARS
                    and a_prefix[-1] != c_prefix[-1]):
                continue
            best_match = total_match
            best_chunk_num = c_num

        if best_chunk_num and best_chunk_num != a_num:
            corrections.append((a_pos, a_num, best_chunk_num))

    if not corrections:
        return answer, 0

    aligned = answer
    for pos, old_token, new_token in sorted(corrections, key=lambda x: -x[0]):
        if aligned[pos:pos + len(old_token)] == old_token:
            aligned = aligned[:pos] + new_token + aligned[pos + len(old_token):]

    return aligned, len(corrections)


def detect_number_diffs(
    answer: str,
    chunks_texts: list[str],
    *,
    min_match_chars: int = 5,
) -> list[dict]:
    """检测但不修改 — 返回 answer vs chunks 的数字差异。"""
    if not answer or not chunks_texts:
        return []
    chunks_anchors: list[tuple[str, str, str]] = []
    for text in chunks_texts:
        for _pos, prefix, num, suffix in _extract_number_anchors(text):
            chunks_anchors.append((prefix, num, suffix))
    diffs: list[dict] = []
    for a_pos, a_prefix, a_num, a_suffix in _extract_number_anchors(answer):
        best_match = 0
        best_chunk_num: str | None = None
        for c_prefix, c_num, c_suffix in chunks_anchors:
            if c_num.replace(" ", "") == a_num.replace(" ", ""):
                continue
            t = _match_chars_tail(a_prefix, c_prefix) + _match_chars_head(a_suffix, c_suffix)
            if t >= min_match_chars and t > best_match:
                best_match = t
                best_chunk_num = c_num
        if best_chunk_num and best_chunk_num != a_num:
            diffs.append({
                "pos": a_pos,
                "answer_number": a_num,
                "chunks_number": best_chunk_num,
                "context": (a_prefix + a_num + a_suffix)[:40],
            })
    return diffs


def detect_modal_verb_diffs(
    answer: str,
    chunks_texts: list[str],
    *,
    min_match_chars: int = 5,
) -> list[dict]:
    """检测（但不修改）answer vs chunks 的量词差异。用于 metadata 警告。

    Returns:
        list of {pos, answer_verb, chunks_verb, context} dicts
    """
    if not answer or not chunks_texts:
        return []
    chunks_anchors: list[tuple[str, str, str]] = []
    for text in chunks_texts:
        for _pos, prefix, verb, suffix in _extract_modal_anchors(text):
            chunks_anchors.append((prefix, verb, suffix))

    diffs: list[dict] = []
    for a_pos, a_prefix, a_verb, a_suffix in _extract_modal_anchors(answer):
        best_match = 0
        best_chunk_verb: str | None = None
        for c_prefix, c_verb, c_suffix in chunks_anchors:
            t = _match_chars_tail(a_prefix, c_prefix) + _match_chars_head(a_suffix, c_suffix)
            if t >= min_match_chars and t > best_match:
                best_match = t
                best_chunk_verb = c_verb
        if best_chunk_verb and best_chunk_verb != a_verb:
            diffs.append({
                "pos": a_pos,
                "answer_verb": a_verb,
                "chunks_verb": best_chunk_verb,
                "context": (a_prefix + a_verb + a_suffix)[:40],
            })
    return diffs
