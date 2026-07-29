"""Agent 智能调度（W7 agent 深化 · Router）。

背景：三个 agent（查询分解 / 引用核验 / 工具调用）此前是独立 flag，**全部默认关**——
    因为每个都对**每条** query 无差别加一次 LLM 调用（分解判定 ~1.5s、核验 ~1.3s），
    压 TTFT ≤3s SLA 且多数简单题根本用不上。结果：能力做出来了，没人敢开。

方案：加一层**廉价路由**决定每条 query 走哪条路，让 agent 从"实验室 flag"变成"生产能力"：
    - 规则预筛（正则，~0ms，零 LLM 成本）——复用 scenario.py 同款思路
    - 规则有把握 → 直接定路由；规则没把握 → **安全回退 plain**（常规 RAG）

设计原则（沿用 scenario.py 的取舍）：
    **宁可漏触发，不可误触发**。漏触发 = 退化成原来的常规 RAG（无损）；
    误触发 = 白付 LLM 成本 + 可能答偏（有损）。所以所有规则都要求强信号。

路由目标：
    "tool"      → 工具调用 Agent（目录导航 / 精确条文 / 现行状态）
    "decompose" → 查询分解 Agent（发散 / 复合题）
    "plain"     → 常规 RAG（默认）

接口：
    route(query) → {"route": str, "reason": str, "matched": str}
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── 规范号：GB/GB-T/JGJ/CJJ/DB/WW 等 + 数字（识别"精确查表"意图的强信号）──
_SPEC_CODE_RE = re.compile(
    r"(GB\s*/?\s*T?\s*\d{4,5}|JGJ\s*/?\s*T?\s*\d{2,3}|CJJ\s*/?\s*T?\s*\d{2,3}"
    r"|DB\s*\d{2}|WW\s*/?\s*T?\s*\d{4}|建标\s*\[?\d{4})",
    re.IGNORECASE,
)

# 条文号 / 表号：5.0.3 / 第5.0.3条 / 表5.0.3
_CLAUSE_RE = re.compile(r"(第\s*)?\d+\.\d+(\.\d+)?\s*条?|表\s*\d+\.\d+")

# ── tool 路由信号 ──────────────────────────────────────────
# ① 目录导航："收录了哪些…规范" / "规范库里有哪些" / "有哪些消防规范"
_CATALOG_RE = re.compile(
    r"(收录|规范库|库里|你有).{0,8}(哪些|什么|多少)|哪些.{0,6}规范(有|吗|\?|？|$)"
    r"|规范.{0,4}(清单|列表|目录)"
)
# ② 现行状态："还有效吗" / "是否现行" / "作废了吗"
_STATUS_RE = re.compile(
    r"(还|是否|是不是).{0,4}(有效|现行|在用)|(作废|废止|失效|过期).{0,3}(了吗|吗|没有|\?|？)"
    r"|现行(有效)?吗|最新版本(是|吗)"
)
# ③ 精确条文："第5.0.3条的原文" / "GB xxx 5.0.3 是什么"
_CLAUSE_LOOKUP_RE = re.compile(r"原文|条文内容|这条.{0,4}(说|写|规定)什么|怎么写的")

# ── decompose 路由信号 ────────────────────────────────────
# ① 发散："有什么规范要求" / "有哪些要求" / "需要注意什么"
_BROAD_RE = re.compile(
    r"(有什么|有哪些|哪些).{0,6}(要求|规定|标准|规范|注意)"
    r"|需要注意(什么|哪些)|注意事项|(要求|规定).{0,3}(有哪些|是什么)"
)

# ② 复合：一句里并列两个及以上要点（和/与/及/顿号连接），末尾落到"要求/因素/区别"类名词。
#    覆盖三种真实写法：
#      "建筑密度上限和容积率要求"（名词 和 名词 + 要求）
#      "数量、位置和宽度应考虑哪些因素"（顿号列举 + 因素）
#      "绿地率和绿化覆盖率有什么区别"（并列 + 区别）
#    窗口取 20：中文复合名词短语常较长（如"公园绿地服务半径覆盖率的强制性"达 15 字）。
_COMPOUND_RE = re.compile(
    r"[^，。？?]{2,20}(和|与|及|以及|、)[^，。？?]{2,20}"
    r"(的)?\s*(要求|规定|标准|指标|因素|区别|差异)"
)

# ③ 具体指标名词：出现这类"可量化的单一属性"时，即便措辞像发散，实为单点问题。
#    依据：评测集里"幼儿园园址选择对服务半径有什么要求""填方路基对填料的最大粒径有什么要求"
#    这类措辞误导型样本，语义上只问一个量 → 不该分解（分解＝白付 LLM 成本）。
_SPECIFIC_METRIC_RE = re.compile(
    r"半径|粒径|宽度|高度|面积|比例|密度|坡度|厚度|间距|净宽|净高|极限|烈度"
    r"|稳定性|层数|规模|数量|下限|上限|最低|最小|最大|覆盖率|多少"
)


def route(query: str) -> dict[str, str]:
    """判定该 query 走哪条 agent 路径（纯规则，~0ms、零 LLM 成本）。

    Returns:
        {"route": "tool"|"decompose"|"plain", "reason": 中文说明, "matched": 命中的信号名}

    契约：任何不确定的情况都返回 "plain"（常规 RAG），保证无损降级。
    """
    q = (query or "").strip()
    if not q:
        return {"route": "plain", "reason": "空查询", "matched": ""}

    has_spec_code = bool(_SPEC_CODE_RE.search(q))
    has_clause = bool(_CLAUSE_RE.search(q))

    # ── tool 路由（要求强信号：目录问法，或 规范号+条文号/状态问法）──
    if _CATALOG_RE.search(q):
        return {"route": "tool", "reason": "目录导航类（问收录了哪些规范）", "matched": "catalog"}
    if has_spec_code and _STATUS_RE.search(q):
        return {"route": "tool", "reason": "现行状态类（规范号 + 状态问法）", "matched": "status"}
    if has_spec_code and has_clause:
        # 规范号 + 条文号 = 精确定位意图（不论是否显式说"原文"）
        return {
            "route": "tool",
            "reason": "精确条文类（规范号 + 条文号）",
            "matched": "clause_lookup",
        }
    if has_clause and _CLAUSE_LOOKUP_RE.search(q):
        return {"route": "tool", "reason": "精确条文类（条文号 + 问原文）", "matched": "clause_lookup"}

    # ── decompose 路由（发散 / 复合）──
    # 复合优先：并列结构是强信号，即便含具体指标名词（"净宽和净高"确实要拆两路）
    if _COMPOUND_RE.search(q):
        return {"route": "decompose", "reason": "复合题（一句问两个要点）", "matched": "compound"}
    if _BROAD_RE.search(q):
        # 措辞像发散、但落在某个具体量上 → 实为单点，不拆（治误触发，省 LLM 成本）
        if _SPECIFIC_METRIC_RE.search(q):
            return {
                "route": "plain",
                "reason": "措辞似发散但指向具体指标，判为单点",
                "matched": "broad_but_specific",
            }
        # 规则到此为模糊区：词法上与"真发散题"无法区分（评测实证误触发全集中于此），
        # matched=broad 即代表"不确定"，调用方可选择升级到 LLM 判定（resolve_route）。
        return {"route": "decompose", "reason": "发散题（问某对象有哪些要求）", "matched": "broad"}

    # ── 兜底：常规 RAG（宁可漏触发，不误触发）──
    return {"route": "plain", "reason": "常规内容查询", "matched": ""}


def resolve_route(query: str, *, allow_llm: bool = False) -> dict[str, str]:
    """规则路由 + （可选）对模糊区升级到 LLM 判定。

    分层依据（评测实证）：规则对 目录/条文/状态/明确并列复合 已做到 100% 准确，
    唯独 "X的设计要求有哪些" 这类词法歧义区会误触发；只对这一小撮付 LLM 成本。

    Args:
        allow_llm: 是否允许对模糊区调用 LLM（默认 False = 纯规则、0ms、零成本）。
    """
    r = route(query)
    if not allow_llm or r["matched"] != "broad":
        return r

    # 模糊区 → LLM 判定 broad / single
    try:
        from app.core.config import ROUTER_LLM_TIMEOUT_SECONDS, settings
        from app.core.prompts import build_route_judge_messages
        from app.rag.generator import get_client

        resp = get_client().chat.completions.create(
            model=settings.deepseek_model,
            messages=build_route_judge_messages(query),
            temperature=0.0,
            max_tokens=8,
            timeout=ROUTER_LLM_TIMEOUT_SECONDS,
            stream=False,
        )
        verdict = (resp.choices[0].message.content or "").strip().lower()
    except Exception as e:
        logger.warning(f"[agent_router] LLM 判定失败，保留规则结果: {e}")
        return r

    if "single" in verdict:
        return {
            "route": "plain",
            "reason": "模糊区经 LLM 判定为单点问题",
            "matched": "llm_single",
        }
    if "broad" in verdict:
        return {
            "route": "decompose",
            "reason": "模糊区经 LLM 判定为发散问题",
            "matched": "llm_broad",
        }
    return r  # 判定无法解析 → 保留规则结果
