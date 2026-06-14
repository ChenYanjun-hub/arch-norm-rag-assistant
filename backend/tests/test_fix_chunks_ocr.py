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

from scripts.fix_chunks_ocr import fix_units  # noqa: E402


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
