"""W7 D4：fix_chunks_ocr.fix_units 单元测试 — 锁定人均面积单位 ² 修复的正则行为。

fix_units 在 W7 D4 把 chunks 替换数从 13 扩到 56 处（含核心 GB 50180 用地表），
正则 blast radius 较大，必须用单测锁住「该修的修、不该碰的绝不碰」：

正向（应修）：
  - ² 完全丢失：'0.35m/人' → '0.35m²/人'
  - ² 误识为 r：'0.50mr/人' → '0.50m²/人'
  - 范围两端都修：'2m/人～10m/人'
  - 表头单位标签：'(m/人)' / '《mr/人)' → '(m²/人)'
  - 每床/每生：'6.00m/床'、'5m/生'

反向（绝不碰，否则把正确/无关单位改坏）：
  - 已正确：'m²/人'、cosmetic 'm2/人'
  - 体积单位：'m³/人'（用水量等，³ 阻断匹配）
  - 其他字母单位：'km/人'、'cm/人'
  - 非人均分母：'m/s'、'm/h'
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from scripts.fix_chunks_ocr import (  # noqa: E402
    WATERMARK_LINES,
    fix_units,
    strip_page_furniture,
)


class TestFixUnitsPositive(unittest.TestCase):
    """应当修复的 case。"""

    def test_dropped_superscript(self):
        out, n = fix_units("旧区改建不应低于0.35m/人")
        self.assertEqual(out, "旧区改建不应低于0.35m²/人")
        self.assertEqual(n, 1)

    def test_garbled_r(self):
        out, n = fix_units("新区建设不应低于0.50mr/人")
        self.assertEqual(out, "新区建设不应低于0.50m²/人")
        self.assertEqual(n, 1)

    def test_range_both_ends(self):
        out, n = fix_units("人均硬质活动场地面积宜为2m/人～10m/人")
        self.assertEqual(out, "人均硬质活动场地面积宜为2m²/人～10m²/人")
        self.assertEqual(n, 2)

    def test_header_paren(self):
        out, n = fix_units("公园绿地分级规划控制指标(m/人)")
        self.assertEqual(out, "公园绿地分级规划控制指标(m²/人)")
        self.assertEqual(n, 1)

    def test_header_book_mark_and_r(self):
        out, n = fix_units("人均有效避难面积《mr/人)")
        self.assertEqual(out, "人均有效避难面积《m²/人)")
        self.assertEqual(n, 1)

    def test_per_bed_and_per_student(self):
        out, n = fix_units("卧室使用面积不应小于6.00m/床；教室5m/生")
        self.assertEqual(out, "卧室使用面积不应小于6.00m²/床；教室5m²/生")
        self.assertEqual(n, 2)

    def test_per_person_trip(self):
        out, n = fix_units("用地按0.5m/人次控制")
        self.assertEqual(out, "用地按0.5m²/人次控制")
        self.assertEqual(n, 1)


class TestFixUnitsNegative(unittest.TestCase):
    """绝不能误伤的 case（修了就是制造新错误，违反 RED LINE 2）。"""

    def test_already_correct(self):
        out, n = fix_units("人均用地3.0m²/人")
        self.assertEqual(out, "人均用地3.0m²/人")
        self.assertEqual(n, 0)

    def test_cosmetic_m2(self):
        # 'm2/人' 是 cosmetic 退化，Judge/LLM 都认得，不在本次修复范围
        out, n = fix_units("人均用地3.0m2/人")
        self.assertEqual(out, "人均用地3.0m2/人")
        self.assertEqual(n, 0)

    def test_volume_m3_not_touched(self):
        # 'm³/人' 是体积（用水/用气量），绝不能改成面积 m²
        out, n = fix_units("人均日用水量0.2m³/人")
        self.assertEqual(out, "人均日用水量0.2m³/人")
        self.assertEqual(n, 0)

    def test_km_cm_not_touched(self):
        out, n = fix_units("步行5km/人，误差2cm/人")
        self.assertEqual(out, "步行5km/人，误差2cm/人")
        self.assertEqual(n, 0)

    def test_speed_units_not_touched(self):
        out, n = fix_units("风速5m/s，流量3m/h")
        self.assertEqual(out, "风速5m/s，流量3m/h")
        self.assertEqual(n, 0)

    def test_empty(self):
        out, n = fix_units("")
        self.assertEqual(out, "")
        self.assertEqual(n, 0)


class TestStripPageFurniture(unittest.TestCase):
    """页脚水印剥离 —— 关键是"只整行删、绝不改保留行的字符"。"""

    def test_removes_full_watermark_lines(self):
        out, n_wm, n_pg = strip_page_furniture(
            "3.0.14 城镇道路养护应采取防尘、降噪措施。\n住房城乡建设部信息公开\n浏览专用"
        )
        self.assertEqual(out, "3.0.14 城镇道路养护应采取防尘、降噪措施。")
        self.assertEqual(n_wm, 2)
        self.assertEqual(n_pg, 0)

    def test_rejoins_sentence_split_by_watermark(self):
        """真实缺陷形态：水印把一句规范切两半（GB 55037 11.0.6）。"""
        out, n_wm, n_pg = strip_page_furniture(
            "11.0.6 施工所需用火、用电和用气均应符合消\n住房城乡建\n防安全要求\n浏览专用"
        )
        self.assertEqual(out, "11.0.6 施工所需用火、用电和用气均应符合消\n防安全要求")
        self.assertEqual(n_wm, 2)

    def test_removes_page_number_adjacent_to_watermark(self):
        out, n_wm, n_pg = strip_page_furniture(
            "…Ⅲ等养护的\n6\n住房城乡建设部信息公开\n浏览专用\n道路宜三日一巡"
        )
        self.assertEqual(out, "…Ⅲ等养护的\n道路宜三日一巡")
        self.assertEqual((n_wm, n_pg), (2, 1))

    def test_keeps_list_number_not_adjacent_to_watermark(self):
        """条文列项序号必须留 —— 只有紧贴水印的纯数字行才当页码删。"""
        out, n_wm, n_pg = strip_page_furniture(
            "4.1.1 应符合下列规定:\n1 第一项内容\n2 第二项内容"
        )
        self.assertEqual(out, "4.1.1 应符合下列规定:\n1 第一项内容\n2 第二项内容")
        self.assertEqual((n_wm, n_pg), (0, 0))

    def test_bare_number_alone_is_kept(self):
        out, n_wm, n_pg = strip_page_furniture("2.1.5 定义如下\n1\n说明文字")
        self.assertEqual(out, "2.1.5 定义如下\n1\n说明文字")
        self.assertEqual((n_wm, n_pg), (0, 0))

    def test_never_touches_real_clause_mentioning_ministry(self):
        """🔴 红线：正文里提到"住房城乡建设部"的真条文绝不能被删。

        全语料扫描确认存在这样一行（公共美术馆建设标准），只有整行完全等于
        水印形态才删，所以它必须原样保留。
        """
        real = "2017 年国家发展改革委住房城乡建设部印发《关于规范…》"
        out, n_wm, n_pg = strip_page_furniture(real)
        self.assertEqual(out, real)
        self.assertEqual((n_wm, n_pg), (0, 0))

    def test_whitelist_contains_no_substring_of_real_text(self):
        """白名单任一形态都不能是"包含式"匹配 —— 用整行相等，故长正文安全。"""
        real = "由住房城乡建设部批准发布，自2022年1月1日起实施。"
        self.assertNotIn(real.strip(), WATERMARK_LINES)
        out, _, _ = strip_page_furniture(real)
        self.assertEqual(out, real)

    def test_truncated_watermark_fragments_removed(self):
        """OCR 把水印截断成残片（住房城乡建 / 部信息公开 / 信息公开）也要删。"""
        for frag in ("住房城乡建", "部信息公开", "信息公开", "住房城乡建设部"):
            out, n_wm, _ = strip_page_furniture(f"正文一\n{frag}\n正文二")
            self.assertEqual(out, "正文一\n正文二", f"未删残片 {frag}")
            self.assertEqual(n_wm, 1)

    def test_indentation_and_trailing_space_tolerated(self):
        """真实数据里水印行带前后空格（CJJ 193-2012）。"""
        out, n_wm, _ = strip_page_furniture("正文\n        住房城乡建设部信息公开 \n正文二")
        self.assertEqual(out, "正文\n正文二")
        self.assertEqual(n_wm, 1)

    def test_clean_text_unchanged(self):
        clean = "5.0.3 幼儿园服务半径不宜大于300m。\n1 规模宜为6~12班。"
        out, n_wm, n_pg = strip_page_furniture(clean)
        self.assertEqual(out, clean)
        self.assertEqual((n_wm, n_pg), (0, 0))

    def test_empty(self):
        out, n_wm, n_pg = strip_page_furniture("")
        self.assertEqual(out, "")
        self.assertEqual((n_wm, n_pg), (0, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
