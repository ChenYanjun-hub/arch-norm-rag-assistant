"""spec_taxonomy 单测：归一匹配 / 阈值判定 / 分组顺序 / 表自身一致性。

重点不是"分类对不对"（那是人工编制的判断），而是**机制不出错**：
spec_code 写法差异不能漏匹配、未登记项必须可见、分组不能丢规范。
"""

from __future__ import annotations

from app.services.spec_taxonomy import (
    SUBCAT_MIN_SPECS,
    SUBCATEGORY_BY_SPEC,
    SUBCATEGORY_ORDER,
    UNCLASSIFIED,
    get_subcategory,
    group_by_subcategory,
    is_subdivided,
    normalize_spec_code,
)


def _specs(*codes: str) -> list[dict[str, str]]:
    return [{"spec_code": c, "spec_name": c} for c in codes]


# ── 归一匹配 ──────────────────────────────────────────────
def test_normalize_strips_spaces_and_unifies_dashes():
    # 语料里同一规范有多种写法，归一后必须一致
    assert normalize_spec_code("GB 50180-2018") == normalize_spec_code("GB50180-2018")
    assert normalize_spec_code("JGJ 76－2019") == normalize_spec_code("JGJ76-2019")
    assert normalize_spec_code("GB 50442 - 20XX") == normalize_spec_code("GB50442-20XX")
    assert normalize_spec_code("gb/t 51346-2019") == normalize_spec_code("GB/T51346-2019")


def test_normalize_does_not_touch_chinese_one():
    """`一` 不能被当连字符替换——否则含「一」的规范名/号会被改写。"""
    assert "一" in normalize_spec_code("GB/T 一张图-2021")


def test_get_subcategory_tolerates_spacing_variants():
    assert get_subcategory("GB 50180-2018") == "居住社区"
    assert get_subcategory("GB50180-2018") == "居住社区"
    assert get_subcategory("  gb 50180-2018  ") == "居住社区"


def test_get_subcategory_unknown_returns_none():
    """未登记返回 None 而不是瞎猜一个（红线 2 同类：元数据不臆断）。"""
    assert get_subcategory("GB 99999-2099") is None
    assert get_subcategory("") is None


# ── 阈值判定 ──────────────────────────────────────────────
def test_is_subdivided_respects_threshold():
    assert is_subdivided("规划", 29) is True
    assert is_subdivided("结构", 4) is False  # 域内 4 部，加一层只增加点击成本
    assert is_subdivided("消防", 6) is False
    assert is_subdivided("规划", SUBCAT_MIN_SPECS - 1) is False
    assert is_subdivided("规划", SUBCAT_MIN_SPECS) is True


def test_is_subdivided_false_for_undefined_domain():
    assert is_subdivided("市政给水", 50) is False


def test_group_returns_none_when_not_subdivided():
    assert group_by_subcategory("结构", _specs("JGJ 99-2015", "CJJ/T 301-2020")) is None


# ── 分组行为 ──────────────────────────────────────────────
def test_group_follows_declared_order_not_size():
    """展示顺序按 SUBCATEGORY_ORDER（查询频率），不按组大小排。"""
    codes = [c for c, v in SUBCATEGORY_BY_SPEC.items() if v in SUBCATEGORY_ORDER["规划"]]
    groups = group_by_subcategory("规划", _specs(*codes))
    assert groups is not None
    names = [n for n, _ in groups]
    assert names == [n for n in SUBCATEGORY_ORDER["规划"] if n in names]
    # 「居住社区」只有 2 部却排第一 —— 证明不是按数量排
    assert names[0] == "居住社区"


def test_group_preserves_all_specs():
    """分组不能丢规范（导航层丢一部 = 用户永远找不到它）。"""
    codes = [c for c, v in SUBCATEGORY_BY_SPEC.items() if v in SUBCATEGORY_ORDER["建筑"]]
    groups = group_by_subcategory("建筑", _specs(*codes))
    assert groups is not None
    assert sum(len(g) for _, g in groups) == len(codes)


def test_unclassified_bucket_is_visible_and_last():
    codes = [c for c, v in SUBCATEGORY_BY_SPEC.items() if v in SUBCATEGORY_ORDER["景观"]]
    groups = group_by_subcategory("景观", _specs(*codes, "GB 99999-2099"))
    assert groups is not None
    assert groups[-1][0] == UNCLASSIFIED
    assert groups[-1][1][0]["spec_code"] == "GB 99999-2099"


def test_group_accepts_objects_not_only_dicts():
    class Brief:
        def __init__(self, code: str) -> None:
            self.spec_code = code

    codes = [c for c, v in SUBCATEGORY_BY_SPEC.items() if v in SUBCATEGORY_ORDER["景观"]]
    groups = group_by_subcategory("景观", [Brief(c) for c in codes])
    assert groups is not None
    assert sum(len(g) for _, g in groups) == len(codes)


# ── 分类表自身一致性（防手写表引入的静默错误）────────────────
def test_no_duplicate_keys_after_normalization():
    """同一规范用两种写法登记两次 → 后者静默覆盖前者，必须挡住。"""
    normed = [normalize_spec_code(k) for k in SUBCATEGORY_BY_SPEC]
    dupes = {c for c in normed if normed.count(c) > 1}
    assert not dupes, f"归一后重复登记：{dupes}"


def test_every_subcategory_name_has_display_order():
    """分类名没进 SUBCATEGORY_ORDER 会退化成字母序，展示顺序不可控。"""
    declared = {n for names in SUBCATEGORY_ORDER.values() for n in names}
    used = set(SUBCATEGORY_BY_SPEC.values())
    assert used <= declared, f"未登记展示顺序：{used - declared}"


def test_order_table_has_no_empty_subcategory():
    """SUBCATEGORY_ORDER 里声明了但没有任何规范的分类名 = 表已过期。"""
    used = set(SUBCATEGORY_BY_SPEC.values())
    for domain, names in SUBCATEGORY_ORDER.items():
        for n in names:
            assert n in used, f"{domain} 声明了空分类「{n}」"
