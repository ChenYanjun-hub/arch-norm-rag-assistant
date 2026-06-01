"""场景识别：判断用户输入属于哪种场景。

W2 简版（已实现）：chitchat / out_of_scope / normal
W3 D5 完整版（本次升级）：补 input_empty / input_too_long / sensitive / deprecated / ambiguous
                          = 共 8 种场景全覆盖（CLAUDE.md E.4 边界兜底）

判定优先级（自上而下短路，CLAUDE.md E.4）：
    1. input_empty       —— 空字符串
    2. input_too_long    —— 超 500 字
    3. sensitive         —— 涉及规避审查 / 绕过审批
    4. deprecated        —— 涉及已废止规范号
    5. chitchat          —— 闲聊
    6. out_of_scope      —— 超范围（明显非 5 类规范）
    7. ambiguous         —— 模糊提问（query 信息密度太低）
    8. normal            —— 正常 RAG 流程
"""

from __future__ import annotations

import logging
import re
from typing import Literal

logger = logging.getLogger(__name__)

ScenarioType = Literal[
    "input_empty",
    "input_too_long",
    "sensitive",
    "deprecated",
    "chitchat",
    "out_of_scope",
    "ambiguous",
    "normal",
]

# 输入长度上限（CLAUDE.md D.2 + pipeline 一致）
MAX_QUERY_LEN = 500

# ── 敏感问题关键词（涉及规避 / 绕过审查）──
# 注意：宁错漏不错杀。CLAUDE.md 红线 4：不写 chunks 之外的"建议"
# W4 D3 part 2 修：扩"过审"距离 + 加"偷偷"+ 修"顺利"系列
_SENSITIVE_PATTERNS = [
    r"如何.{0,8}规避",
    r"怎么.{0,8}规避",
    r"如何.{0,8}绕过",
    r"怎么.{0,8}绕过",
    r"不被.{0,8}审查",
    r"不被.{0,8}发现",
    r"绕(过|开).{0,5}(审|检|查)",
    r"违规.{0,4}(怎么|如何)",
    # 偷偷做事系列（W4 D3 加：原 `偷.{0,3}做` 漏 "偷偷把..."）
    r"偷偷.{0,15}(做|建|盖|搞|算|报|拿|放|做)",
    r"偷.{0,3}做",
    r"藏.{0,3}起来",
    r"瞒.{0,3}过",
    r"假报.{0,3}",
    r"虚报.{0,3}",
    r"少算.{0,3}",
    # 过审系列（W4 D3 扩：5 字 → 20 字距离，覆盖"怎么能让 XX 顺利过审"）
    r"怎么.{0,20}过审",
    r"如何.{0,20}过审",
    r"怎么.{0,20}过(检|查)",
    # 顺利过 + 审/检 类（明显的规避意图）
    r"顺利.{0,8}过(审|检|关)",
]
_SENSITIVE_RE = re.compile("|".join(_SENSITIVE_PATTERNS), re.IGNORECASE)

# ── 已废止规范号（硬编码常见的几个高频废止规范）──
# 格式：废止号 → 现行替代号 + 提示
# 维护建议：每年扫一次国家标准委公告，补 1-2 个常见废止号
DEPRECATED_SPECS: dict[str, dict[str, str]] = {
    "GB 50180-93": {
        "current": "GB 50180-2018",
        "name": "城市居住区规划设计标准",
        "year": "2018",
    },
    "GB 50180-2002": {
        "current": "GB 50180-2018",
        "name": "城市居住区规划设计标准",
        "year": "2018",
    },
    "GB 50016-2006": {
        "current": "GB 50016-2014 / GB 55037-2022",
        "name": "建筑设计防火规范 / 建筑防火通用规范",
        "year": "2014 / 2022",
    },
    "GB 50096-1999": {
        "current": "GB 50096-2011 / GB 55037-2022",
        "name": "住宅设计规范 / 建筑防火通用规范",
        "year": "2011 / 2022",
    },
    "JGJ 39-87": {
        "current": "JGJ 39-2016",
        "name": "托儿所、幼儿园建筑设计规范",
        "year": "2016",
    },
    "GBJ 16-87": {
        "current": "GB 50016-2014 / GB 55037-2022",
        "name": "建筑设计防火规范 / 建筑防火通用规范",
        "year": "2014 / 2022",
    },
}

# 用于在 query 中识别废止规范号
# 规范号格式较多，简化匹配："GB|JGJ|CJJ|GBJ|TB 数字-数字"
# W4 D3 part 2 修：原正则把 "1999" 匹 "99" 时位置在 "1" 不开头 → 失败
# 加全四位年份 1993/1987/1999，并保留旧两位写法兼容
_DEPRECATED_NAMES_RE = re.compile(
    r"(?:GB|JGJ|CJJ|GBJ|TB)[\s/]?\d+\s*[-–—]\s*"
    r"(?:1993|1987|1999|2002|2006|93|87|99)(?!\d)",  # 加 (?!\d) 防止 1993 误吞前面
    re.IGNORECASE,
)


def _detect_deprecated(q: str) -> str | None:
    """如 query 中提及已废止规范号，返回该 spec_code（标准化形式）；否则 None。"""
    # 先粗筛
    m = _DEPRECATED_NAMES_RE.search(q)
    if not m:
        return None
    raw = m.group(0)
    # 标准化：去多余空格 + 大写 + 统一 - 字符
    normalized = re.sub(r"\s+", " ", raw).strip().upper()
    normalized = normalized.replace("–", "-").replace("—", "-")
    # 反查 DEPRECATED_SPECS（key 也做相同标准化）
    for key in DEPRECATED_SPECS:
        if key.upper().replace(" ", "") in normalized.replace(" ", ""):
            return key
    return None


# ── 闲聊关键词（行级硬规则）──
# W4 D3 part 2 修：末尾允许"啊呀哈呢吧呦哟嘛" + 加"这个系统/这是什么"类自我介绍
_TAIL = r"[\s\?！？!~。.啊呀哈呢吧呦哟嘛]*"
_CHITCHAT_PATTERNS = [
    rf"^(你好|您好|hi|hello|嗨|早上好|晚上好|下午好){_TAIL}$",
    rf"^(谢谢|多谢|感谢|thx|thanks?){_TAIL}$",
    rf"^(再见|拜拜|bye|goodbye){_TAIL}$",
    # 自我介绍类：原"你是谁/介绍自己"基础上加"这|这个|该|本(系统|工具|助手|AI|平台)"
    rf"^(你是谁|你是什么|介绍.{{0,5}}自己|你能.{{0,3}}什么){_TAIL}$",
    rf"^(这|这个|该|本)(系统|工具|助手|程序|AI|平台).{{0,10}}(是|能|做|帮|查|干).{{0,5}}\??$",
    rf"^(测试|test|123|hello world){_TAIL}$",
]
_CHITCHAT_RE = re.compile("|".join(_CHITCHAT_PATTERNS), re.IGNORECASE)

# ── 超范围关键词（明显不属于设计规范的话题）──
# 宁错漏不错杀——只标命中度最高的几类
_OUT_OF_SCOPE_KEYWORDS = (
    # 个人 / 情感 / 闲谈
    "推荐一下", "好不好", "好吃",
    # 编程 / 技术 / 其它领域
    "python", "代码", "怎么写", "bug", "报错",
    # 时事 / 八卦
    "新闻", "股票", "天气", "翻译",
    # 显然非规范类
    "做菜", "做饭", "电影", "游戏", "电视剧",
)

# ── 模糊提问识别（ambiguous）──
# 信号 1：query 极短（< MIN_VERY_SHORT）必模糊
# 信号 2：短-中长 query 缺乏具体名词或问号词 → 模糊
MIN_VERY_SHORT = 4   # < 4 字必模糊（如"GB"/"规范"/"高度"）
MID_LEN = 15         # 4-15 字按"具体词+问号"组合判断
_QUESTION_WORDS = (
    "?", "？", "几", "多少", "什么", "怎么", "如何",
    "哪", "是否", "能否", "是不是", "需要", "可以", "应该",
    "要求", "标准", "规定",
)
# 至少需要一个"具体内容"关键词，避免"是否合规"这类纯抽象问句被放行
_CONCRETE_HINT_KEYWORDS = (
    # 设计对象（具体名词）
    "居住区", "住宅", "幼儿园", "学校", "医院", "建筑", "楼", "厂房",
    "道路", "绿地", "公园", "广场", "停车", "幼托",
    # 设计指标（具体属性）
    "服务半径", "耐火", "防火", "高度", "宽度", "面积", "层数",
    "间距", "密度", "容积率", "绿地率", "退距", "退线",
    # 设计规范代码
    "GB", "JGJ", "CJJ",
)


def _detect_ambiguous(q: str) -> bool:
    """判定是否模糊提问（信息密度太低）。

    返回 True 表示需要追问，False 表示可以进入正常 RAG 流程。
    宁可放行错给 LLM（让 RAG 自己兜底"未查询到"），不要错判把正常 query 拦下。

    规则（按长度分段）：
      - 极短（< 4 字）：必模糊（如"GB"/"规范"/"高度"）
      - 短-中长（4-15 字）：
          · 0 个具体关键词 → 模糊
          · ≥ 1 个具体关键词 且 含问号词 → normal（如"幼儿园的要求"）
          · ≥ 2 个具体关键词 → normal（如"幼儿园服务半径"）
          · 只有 1 个具体关键词且无问号词 → 模糊（如"幼儿园"4 字）
      - 长（> 15 字）：默认 normal
    """
    L = len(q)
    if L < MIN_VERY_SHORT:
        return True

    n_concrete = sum(1 for kw in _CONCRETE_HINT_KEYWORDS if kw in q)
    has_question = any(w in q for w in _QUESTION_WORDS)

    if L <= MID_LEN:
        # 0 个具体词必模糊
        if n_concrete == 0:
            return True
        # 至少 1 个具体词 + 问号词 → normal
        if has_question:
            return False
        # ≥ 2 个具体词无问号 → normal
        if n_concrete >= 2:
            return False
        # 仅 1 个具体词无问号 → 模糊
        return True

    return False


def detect_scenario(query: str) -> ScenarioType:
    """场景识别主入口（CLAUDE.md E.4 优先级自上而下短路）。

    Args:
        query: 用户原始 query（未必 strip 过）

    Returns:
        ScenarioType
    """
    q = (query or "").strip()

    # 1. 输入空
    if not q:
        logger.info("[scenario] input_empty")
        return "input_empty"

    # 2. 输入超长
    if len(q) > MAX_QUERY_LEN:
        logger.info(f"[scenario] input_too_long: len={len(q)}")
        return "input_too_long"

    # 3. 敏感问题（涉及规避 / 绕过审查）
    if _SENSITIVE_RE.search(q):
        logger.info(f"[scenario] sensitive: {q[:30]!r}")
        return "sensitive"

    # 4. 涉及已废止规范号
    if _detect_deprecated(q):
        logger.info(f"[scenario] deprecated: {q[:30]!r}")
        return "deprecated"

    # 5. 闲聊（精确正则匹配）
    if _CHITCHAT_RE.match(q):
        logger.info(f"[scenario] chitchat: {q[:30]!r}")
        return "chitchat"

    # 6. 超范围：短 query 含明显非规范关键词
    if len(q) <= 30:
        for kw in _OUT_OF_SCOPE_KEYWORDS:
            if kw in q.lower():
                logger.info(f"[scenario] out_of_scope (kw={kw!r}): {q[:30]!r}")
                return "out_of_scope"

    # 7. 模糊提问（最弱判定，放最后）
    if _detect_ambiguous(q):
        logger.info(f"[scenario] ambiguous: {q[:30]!r}")
        return "ambiguous"

    return "normal"
