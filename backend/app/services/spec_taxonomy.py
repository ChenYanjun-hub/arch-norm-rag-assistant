"""规范二级细分（subcategory）—— 侧栏导航分组 + 一键限定检索范围。

## 为什么需要
一级域只有 6 类，但「规划」下有 29 部规范。侧栏展开后是一条 29 行的平铺列表，
规划师要找「城市绿地规划标准」得逐行扫——**导航成本随语料增长线性恶化**，
而语料还会继续加。二级细分把单次扫描面从 29 降到 ≤7。

## 为什么放在 service 而不是 chunk 元数据
subcategory 是**导航/展示**概念，不是检索字段：
  - 写进 chunk payload 要重跑 89 部 PDF 的 ingest（数小时 + 语料漂移风险），
    而这个字段对向量检索本身没有贡献；
  - 需要"按二级分类限定检索"时，subcategory → spec_codes → 复用**已有的**
    `spec_code_filter`（retriever.search 已支持 MatchAny），Qdrant 不需要重建索引。
所以：**按 spec_code 在读取时 join**，单一数据源在本文件，改分类零成本、可回滚。

## 分类原则（人工编制，非关键词猜测）
1. **按规划师的查询意图分，不按发布机构/标准号分**。
   「城市绿地规划标准」(GB/T 51346) 归「绿地生态」，不因为它是 GB/T 就和别的 GB/T 一组。
2. **允许不均匀**。「居住社区」只有 2 部仍独立成组——它是规划师最高频入口，
   分类是为降低查找成本，不是为让每组数量相等。
3. **域规范数 < SUBCAT_MIN_SPECS 时不细分**。「结构」4 部、「消防」6 部，
   拆成 3 组只是多加一层点击，扫 4 行本来就不费力。
4. **兜底而不猜**：未登记的 spec_code 返回 None → 前端归入「未分类」并可见，
   宁可露出缺口，也不用关键词瞎猜出一个错分类（红线 2 的同类思路：元数据不臆断）。

维护：新增规范后跑 `python -m scripts.audit_taxonomy` 会列出未登记项。
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 域规范数低于此值不做二级细分（见上文原则 3）
SUBCAT_MIN_SPECS = 8

# 未登记规范的展示分组名（前端可见，便于发现缺口）
UNCLASSIFIED = "未分类"

# 全/半角空格、各种连字符（－‑–—）统一，便于 spec_code 匹配
_SPACE_RE = re.compile(r"[\s　]+")
_DASH_RE = re.compile(r"[－‑–—]")


def normalize_spec_code(spec_code: str) -> str:
    """归一 spec_code 用于匹配：去空格 + 统一连字符 + 大写。

    语料里同一规范存在多种写法（`建标 192-2018号` / `JGJ 76－2019` 全角横线 /
    `GB 50442 - 20XX` 带空格），不归一会漏匹配。
    """
    s = _SPACE_RE.sub("", spec_code or "")
    s = _DASH_RE.sub("-", s)
    return s.upper()


# ── 二级分类表：spec_code → 二级分类名 ────────────────────────────────
# 每域内的 key 按二级分类分组书写，便于人工核对。
SUBCATEGORY_BY_SPEC: dict[str, str] = {
    # ══════════ 规划（29 部 → 7 组）══════════
    # 居住社区（规划师最高频入口，仅 2 部也独立成组）
    "GB 50180-2018": "居住社区",
    "GB/T 47131.1-2026": "居住社区",
    # 公共设施
    "CJJ/T 87-2020": "公共设施",
    "GB 50437-2007": "公共设施",
    "GB 50442-2008": "公共设施",
    "GB 50442 - 20XX": "公共设施",
    "GB 55028-2022": "公共设施",
    # 交通市政（规划层面的交通/市政基础设施，区别于「市政」域的工程设计）
    "CJJ/T 314-2022": "交通市政",
    "DB 31T 1557-2025": "交通市政",
    "GB 50318-2017": "交通市政",
    "GB/T 50546-2018": "交通市政",
    "GB/T 51328-2018": "交通市政",
    "GB/T 51402-2021": "交通市政",
    "GB/T 51439-2021": "交通市政",
    # 绿地生态（规划层面的绿地/环境/生态修复，区别于「景观」域的设计与养护）
    "GB 51287-2018": "绿地生态",
    "GB 51411-2020": "绿地生态",
    "GB/T 51329-2018": "绿地生态",
    "GB/T 51346-2019": "绿地生态",
    # 历史风景
    "GB/T 50298-2018": "历史风景",
    "GB/T 50357-2018": "历史风景",
    "历史文化名城名镇名村保护条例(2017修正)": "历史风景",
    # 防灾地下
    "GB/T 51327-2018": "防灾地下",
    "GB/T 51358-2019": "防灾地下",
    "建标[2012]192号": "防灾地下",
    # 数据术语（技术规程/术语/信息系统类，查法条时通常不是目标，单独成组避免污染前几组）
    "CJ/T 553-2024": "数据术语",
    "CJJ/T 199-2013": "数据术语",
    "GB/T 39972-2021": "数据术语",
    "GB/T 43214-2023": "数据术语",
    "JGJ/T 30-2015": "数据术语",

    # ══════════ 市政（18 部 → 6 组）══════════
    # 道路工程
    "CJJ 193-2012": "道路工程",
    "CJJ 194-2013": "道路工程",
    "CJJ 221-2015": "道路工程",
    "CJJ 36-2016": "道路工程",
    "GB 55011-2021": "道路工程",
    # 城市照明
    "CJJ 45-2015": "城市照明",
    "CJJ/T 307-2019": "城市照明",
    # 给水排水
    "GB 51222-2017": "给水排水",
    "GB/T 51293-2018": "给水排水",
    # 综合管廊
    "GB 50838-2015": "综合管廊",
    "GB 51354-2019": "综合管廊",
    # 能源供热
    "GB/T 50293-2014": "能源供热",
    "GB/T 51074-2015": "能源供热",
    "GB/T 51357-2019": "能源供热",
    # 环卫与其他（本组是"确实不成体系"的诚实兜底，不硬凑到上面 5 组）
    "CJJ 52-2014": "环卫与其他",
    "CJJ/T 100-2017": "环卫与其他",
    "CJJ/T 149-2021": "环卫与其他",
    # ⚠️ 建标函[2004]43号《乡镇卫生院建设标准》是医疗建筑，一级域「市政」疑似归类错误，
    #    应为「建筑 · 医疗养老」。改 domain 需重 ingest 该部 + 由项目负责人拍板，
    #    此处先按现状归组并在审计报告中标记（见 docs/eval/taxonomy_audit.md）。
    "建标函[2004]43号": "环卫与其他",

    # ══════════ 建筑（20 部 → 6 组）══════════
    # 居住建筑
    "GB 50368-2005": "居住建筑",
    "JGJ 286-2013": "居住建筑",
    "GB/T 21741-2021": "居住建筑",
    # 教育建筑
    "JGJ 39-2016": "教育建筑",
    "JGJ 76－2019": "教育建筑",
    "JGJ/T 280-2012": "教育建筑",
    "城市普通中小学校校舍建设标准": "教育建筑",
    "建标 109-2008": "教育建筑",
    "建标 192-2018号": "教育建筑",
    # 医疗养老
    "GB 51039-2014": "医疗养老",
    "GB 50867-2013": "医疗养老",
    # 文化体育
    "JGJ/T 41-2014": "文化体育",
    "公共美术馆建设标准": "文化体育",
    "GB/T 50948-2013": "文化体育",
    # 光环境（采光/照明是建筑域高频查询类型，独立成组）
    "GB 50033-2013": "光环境",
    "GB/T 50034-2024": "光环境",
    # 通用与无障碍
    "GB 55031-2022": "通用与无障碍",
    "GB 50763-2012": "通用与无障碍",
    "CJJ 14-2016": "通用与无障碍",
    "JGJ/T 245-2024": "通用与无障碍",

    # ══════════ 景观（12 部 → 4 组）══════════
    # 绿地设计
    "CJJ/T 75-2023": "绿地设计",
    "DB 5301:T 21-2019": "绿地设计",
    "CJJ/T 308-2021": "绿地设计",
    # 种植养护
    "CJ/T 24-2018": "种植养护",
    "CJJ/T 287-2018": "种植养护",
    "CJJ/T 292-2018": "种植养护",
    "GB/T 51168-2016": "种植养护",
    # 工程与管控
    "GB 55014-2021": "工程与管控",
    "GB/T 51163-2016": "工程与管控",
    # 标志与术语
    "CJJ/T 171-2012": "标志与术语",
    "CJJ/T 91-2017": "标志与术语",
    "CJJ/T 237-2016": "标志与术语",

    # ══════════ 消防（6 部）/ 结构（4 部）══════════
    # 不细分：域内规范数 < SUBCAT_MIN_SPECS，加一层只增加点击成本（见原则 3）
}

# 各域二级分类的**展示顺序**（按查询频率从高到低，不按字母/数量排）
SUBCATEGORY_ORDER: dict[str, list[str]] = {
    "规划": ["居住社区", "公共设施", "交通市政", "绿地生态", "历史风景", "防灾地下", "数据术语"],
    "市政": ["道路工程", "城市照明", "给水排水", "综合管廊", "能源供热", "环卫与其他"],
    "建筑": ["居住建筑", "教育建筑", "医疗养老", "文化体育", "光环境", "通用与无障碍"],
    "景观": ["绿地设计", "种植养护", "工程与管控", "标志与术语"],
}

# 预归一，避免每次查询重复归一
_NORM_SUBCAT = {normalize_spec_code(k): v for k, v in SUBCATEGORY_BY_SPEC.items()}


def get_subcategory(spec_code: str) -> str | None:
    """返回规范的二级分类；未登记返回 None（不猜，见原则 4）。"""
    return _NORM_SUBCAT.get(normalize_spec_code(spec_code))


def is_subdivided(domain: str, spec_count: int) -> bool:
    """该域是否做二级细分。

    两个条件都要满足：域在 SUBCATEGORY_ORDER 里有定义，且规范数 ≥ SUBCAT_MIN_SPECS。
    """
    return domain in SUBCATEGORY_ORDER and spec_count >= SUBCAT_MIN_SPECS


def group_by_subcategory(
    domain: str, specs: list[Any], *, code_of: Any = None
) -> list[tuple[str, list[Any]]] | None:
    """把某域的规范清单按二级分类分组。

    Args:
        domain: 一级域名
        specs: 该域规范清单（元素可为 SpecBrief 或 dict）
        code_of: 从元素取 spec_code 的函数；None 时自动适配 SpecBrief / dict

    Returns:
        [(二级分类名, 该组规范), ...] 按 SUBCATEGORY_ORDER 排序，未登记项归入「未分类」置末；
        该域不细分时返回 None（调用方保持平铺）。
    """
    if not is_subdivided(domain, len(specs)):
        return None

    if code_of is None:
        def code_of(s: Any) -> str:  # type: ignore[misc]
            return s["spec_code"] if isinstance(s, dict) else getattr(s, "spec_code", "")

    buckets: dict[str, list[Any]] = {}
    for s in specs:
        sub = get_subcategory(code_of(s)) or UNCLASSIFIED
        buckets.setdefault(sub, []).append(s)

    order = SUBCATEGORY_ORDER.get(domain, [])
    result: list[tuple[str, list[Any]]] = [
        (name, buckets.pop(name)) for name in order if name in buckets
    ]
    # 剩余（表里没排序、或未分类）按名称稳定输出，「未分类」永远置末
    for name in sorted(k for k in buckets if k != UNCLASSIFIED):
        result.append((name, buckets[name]))
    if UNCLASSIFIED in buckets:
        result.append((UNCLASSIFIED, buckets[UNCLASSIFIED]))
        logger.warning(
            f"[taxonomy] 域「{domain}」有 {len(buckets[UNCLASSIFIED])} 部规范未登记二级分类，"
            f"已归入「{UNCLASSIFIED}」：{[code_of(s) for s in buckets[UNCLASSIFIED]]}"
        )
    return result
