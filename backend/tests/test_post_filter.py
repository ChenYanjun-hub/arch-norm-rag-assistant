"""W6 D0：post_filter 单元测试 — 验证补充说明节剥离的正确性 + 边界 case。

用法：
    cd backend && .venv/bin/python -m pytest tests/test_post_filter.py -v
    或：cd backend && .venv/bin/python -m unittest tests.test_post_filter -v

关键覆盖：
  1. 标题节剥离（## 补充说明 / ### 备注 等）
  2. 粗体段落标签剥离（**补充说明**：...）
  3. 行内括注剥离（**另注**：...）
  4. 不误伤合规提示（"涉及合规判断..."必须保留）
  5. 不误伤"依据"/"结论"等核心节
  6. 多个补充节同时剥离
  7. 空字符串 / 无补充内容 / 仅补充内容
  8. detect_supplementary_sections 返回值
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.rag.post_filter import (
    detect_supplementary_sections,
    strip_supplementary_sections,
)


class TestStripHeading(unittest.TestCase):
    """模式 1 · ## 标题节剥离"""

    def test_heading_section_stripped(self):
        ans = """**结论：** 服务半径 ≤ 300m。

**依据**：《GB 50180-2018》第 5.0.3 条 [1]。

## 补充说明

本助手补充：该条文适用于新建居住区，旧城改造可酌情调整。"""
        cleaned, n = strip_supplementary_sections(ans)
        self.assertNotIn("补充说明", cleaned)
        self.assertNotIn("本助手补充", cleaned)
        self.assertNotIn("旧城改造", cleaned)
        self.assertIn("结论", cleaned)
        self.assertIn("依据", cleaned)
        self.assertIn("[1]", cleaned)
        self.assertGreater(n, 30)

    def test_h3_备注_stripped(self):
        ans = """主答案。

### 备注
这部分是 chunks 之外的内容。"""
        cleaned, n = strip_supplementary_sections(ans)
        self.assertNotIn("备注", cleaned)
        self.assertNotIn("chunks 之外", cleaned)
        self.assertIn("主答案", cleaned)

    def test_heading_stops_at_next_same_level(self):
        """补充说明节后面有下一个 ## 标题时，应只剥离补充节，下一节保留"""
        ans = """## 结论
答案核心。

## 补充说明
本节应被删除。

## 依据
[1] 规范引用 — 这节必须保留。"""
        cleaned, n = strip_supplementary_sections(ans)
        self.assertIn("结论", cleaned)
        self.assertIn("答案核心", cleaned)
        self.assertNotIn("补充说明", cleaned)
        self.assertNotIn("本节应被删除", cleaned)
        self.assertIn("依据", cleaned)
        self.assertIn("规范引用", cleaned)


class TestStripBoldLabel(unittest.TestCase):
    """模式 2 · 粗体标签剥离"""

    def test_bold_补充说明_stripped(self):
        ans = """主答案。

**补充说明**：该数据为 chunks 外的经验补充值。"""
        cleaned, n = strip_supplementary_sections(ans)
        self.assertNotIn("补充说明", cleaned)
        self.assertNotIn("经验补充值", cleaned)
        self.assertIn("主答案", cleaned)
        self.assertGreater(n, 10)

    def test_bold_关于X的补充_stripped(self):
        ans = """主答案。

**关于成人扶手的补充**：成人扶手高度通常为 0.9m。"""
        cleaned, n = strip_supplementary_sections(ans)
        self.assertNotIn("关于成人扶手的补充", cleaned)
        self.assertNotIn("0.9m", cleaned)


class TestPreservation(unittest.TestCase):
    """不应误伤的内容"""

    def test_compliance_hint_preserved(self):
        """合规提示（CLAUDE.md 规则 5 必须保留）不应被剥离"""
        ans = """**结论**：280m 小于规范下限 300m。

具体合规判定建议咨询规划主管部门或专业审图机构。"""
        cleaned, n = strip_supplementary_sections(ans)
        self.assertIn("咨询规划主管部门", cleaned)
        self.assertIn("专业审图机构", cleaned)

    def test_evidence_section_preserved(self):
        """"依据" / "结论" / "引用" 等核心节必须保留"""
        ans = """## 结论
服务半径 ≤ 300m。

## 依据
[1] GB 50180-2018 第 5.0.3 条。

## 引用列表
- [1] 《城市居住区规划设计标准》"""
        cleaned, n = strip_supplementary_sections(ans)
        self.assertIn("结论", cleaned)
        self.assertIn("依据", cleaned)
        self.assertIn("引用列表", cleaned)
        self.assertEqual(n, 0)

    def test_normal_note_in_text_preserved(self):
        """正文中含"说明"二字但非节首的不应误伤"""
        ans = "条文说明了服务半径的最低要求。"
        cleaned, n = strip_supplementary_sections(ans)
        self.assertIn("条文说明", cleaned)
        self.assertEqual(n, 0)


class TestEdgeCases(unittest.TestCase):
    """边界 case"""

    def test_empty_string(self):
        cleaned, n = strip_supplementary_sections("")
        self.assertEqual(cleaned, "")
        self.assertEqual(n, 0)

    def test_only_main_content(self):
        ans = "**结论**：答案。\n\n**依据**：[1] 规范。"
        cleaned, n = strip_supplementary_sections(ans)
        self.assertEqual(cleaned, ans.strip())
        self.assertEqual(n, 0)

    def test_only_supplementary(self):
        """全是补充说明 — 剥离后应几乎为空"""
        ans = "## 补充说明\n全是 chunks 外内容。"
        cleaned, n = strip_supplementary_sections(ans)
        self.assertNotIn("chunks 外内容", cleaned)
        self.assertGreater(n, 10)


class TestMultipleSections(unittest.TestCase):
    """多个补充节同时剥离"""

    def test_multiple_supplementary_sections(self):
        ans = """## 结论
主答案。

## 补充说明
节 1 内容。

## 依据
[1] 规范引用 — 必须保留。

**另注**：节 2 内容。"""
        cleaned, n = strip_supplementary_sections(ans)
        self.assertNotIn("节 1 内容", cleaned)
        self.assertNotIn("节 2 内容", cleaned)
        self.assertIn("结论", cleaned)
        self.assertIn("依据", cleaned)
        self.assertIn("规范引用", cleaned)
        self.assertGreater(n, 20)


class TestDetectOnly(unittest.TestCase):
    """detect_supplementary_sections — 检测但不剥离"""

    def test_detect_returns_matches(self):
        ans = """## 结论
答案。

## 补充说明
内容。"""
        matches = detect_supplementary_sections(ans)
        self.assertEqual(len(matches), 1)
        self.assertTrue(matches[0].startswith("heading"))

    def test_detect_no_match(self):
        ans = "**结论**：仅主答案。"
        matches = detect_supplementary_sections(ans)
        self.assertEqual(matches, [])


class TestRealWorldVeto(unittest.TestCase):
    """基于 W5 D3-D5 真实 veto 案例的回归测试"""

    def test_Q065_成人扶手编造(self):
        """Q065 D3 veto：编造成人扶手高度建议"""
        ans = """**结论：** 幼儿园楼梯应设置成人扶手，并宜在成人扶手中间增设高度为 0.60m 的幼儿专用扶手。

**依据：**

1. **幼儿扶手高度：** JGJ 39-2016 第 4.1.11 条（强制性条文）规定：[1]

**关于成人扶手的补充**：该条文未直接规定成人扶手的具体高度，但通常为 0.9m。"""
        cleaned, n = strip_supplementary_sections(ans)
        self.assertNotIn("通常为 0.9m", cleaned)
        self.assertNotIn("关于成人扶手的补充", cleaned)
        self.assertIn("幼儿扶手高度", cleaned)
        self.assertIn("[1]", cleaned)

    def test_Q034_服务半径编造(self):
        """Q034 D3 veto：[2] 处编造服务半径依据说明"""
        ans = """**结论**：上限 500m。

**依据**：JGJ 39-2016 第 3.1.3 条 [1]。

**补充说明**：服务半径的确定依据了《城市居住区规划设计标准》。"""
        cleaned, n = strip_supplementary_sections(ans)
        self.assertNotIn("服务半径的确定依据", cleaned)
        self.assertIn("上限 500m", cleaned)
        self.assertIn("[1]", cleaned)


if __name__ == "__main__":
    unittest.main(verbosity=2)
