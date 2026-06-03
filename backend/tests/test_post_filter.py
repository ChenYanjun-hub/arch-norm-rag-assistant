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
    align_modal_verbs,
    detect_modal_verb_diffs,
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


# ──────────────────────────────────────────────
# W6 D4 · align_modal_verbs 单测（治 dim4 用词错训练惯性）
# ──────────────────────────────────────────────


class TestAlignModalVerbsBasic(unittest.TestCase):
    """基础校正 case"""

    def test_yi_to_ying_correction(self):
        """Q077 类型：'宜→应' 标准化错误（最常见 dim4 错）"""
        chunks = ["3.1.3 托儿所、幼儿园的服务半径宜为 300m~500m。"]
        answer = "幼儿园的服务半径应为 300m~500m，符合规范要求。"
        aligned, n = align_modal_verbs(answer, chunks)
        self.assertEqual(n, 1)
        self.assertIn("宜为 300m", aligned)
        self.assertNotIn("应为 300m", aligned)

    def test_bu_ying_to_bi_xu_correction(self):
        """Q125 类型：'不应→必须/不得' 误升级"""
        chunks = ["4.1.1 卧室使用面积不应小于 5m²。"]
        answer = "卧室使用面积不得小于 5m²。"
        aligned, n = align_modal_verbs(answer, chunks)
        self.assertEqual(n, 1)
        self.assertIn("不应小于", aligned)
        self.assertNotIn("不得小于", aligned)

    def test_semantic_flip_skipped_保守(self):
        """Q109 类型：'宜大于' vs '不应小于' 是语义翻转 — 算法保守跳过。

        理由：简单替换量词会产出 '宜小于 35%' 荒谬词。
        宁可不改（dim4 仍标错），也不要改坏（产出错的中文）。
        语义翻转 case 留待 W7+ 更复杂算法（需结合方向词反转）。
        """
        chunks = ["4.4.1 居住区绿地率宜大于 35%。"]
        answer = "居住区绿地率不应小于 35%。"
        aligned, n = align_modal_verbs(answer, chunks)
        self.assertEqual(n, 0, "方向词翻转 case 应保守跳过")
        self.assertEqual(aligned, answer, "answer 不应被改")


class TestAlignModalVerbsPreservation(unittest.TestCase):
    """不该改的场景"""

    def test_no_modal_in_chunks_no_correction(self):
        """chunks 没有量词，LLM 用 '应' 是自由表达，不应改"""
        chunks = ["3.2.1 表 3.2.1 居住区分类。"]
        answer = "居住区应按用地范围分类。"
        aligned, n = align_modal_verbs(answer, chunks)
        self.assertEqual(n, 0)
        self.assertEqual(aligned, answer)

    def test_matching_verbs_no_correction(self):
        """量词已一致，不该改"""
        chunks = ["卧室使用面积不应小于 5m²。"]
        answer = "卧室使用面积不应小于 5m²。"
        aligned, n = align_modal_verbs(answer, chunks)
        self.assertEqual(n, 0)
        self.assertEqual(aligned, answer)

    def test_unrelated_modal_not_changed(self):
        """LLM 在 chunks 无关上下文用 '应'，不该被强行改"""
        chunks = ["服务半径宜为 300m。"]
        answer = "另外，本助手应当提示用户咨询主管部门。"
        aligned, n = align_modal_verbs(answer, chunks)
        # "本助手应当提示" 在 chunks 中没匹配 anchor，不应改
        self.assertEqual(n, 0)

    def test_empty_inputs(self):
        self.assertEqual(align_modal_verbs("", ["x"]), ("", 0))
        self.assertEqual(align_modal_verbs("x", []), ("x", 0))
        self.assertEqual(align_modal_verbs("", []), ("", 0))


class TestAlignModalVerbsMultiple(unittest.TestCase):
    """多个 chunks / 多个错误"""

    def test_multiple_corrections_saved_only_safe_ones(self):
        """多个 case 时算法保守：方向词翻转 case 跳过，简单 case 改。

        chunks: '不应小于 5m²' / '不应小于 9m²'（量词=不应，方向=小于）
        answer: '必须大于 5m²' / '应大于 9m²'（量词=必须/应，方向=大于）

        因为方向词都翻转了，算法保守跳过两个 — 不会变 "不应大于" 这种荒谬词。
        """
        chunks = [
            "卧室使用面积不应小于 5m²。",
            "兼起居室的卧室使用面积不应小于 9m²。",
        ]
        answer = "卧室使用面积必须大于 5m²；兼起居室卧室面积应大于 9m²。"
        aligned, n = align_modal_verbs(answer, chunks)
        # 两个都方向翻转，保守跳过 → n=0
        self.assertEqual(n, 0)
        self.assertEqual(aligned, answer)

    def test_picks_best_match_among_chunks(self):
        """多个 chunks 含同一量词模板，应选匹配度最高的"""
        chunks = [
            "服务半径宜为 300m~500m。",
            "建筑高度宜小于 24m。",
        ]
        answer = "服务半径应为 300m~500m。"
        aligned, n = align_modal_verbs(answer, chunks)
        # 应该匹配第一个 chunk（服务半径...）而不是高度的
        self.assertEqual(n, 1)
        self.assertIn("服务半径宜为 300m", aligned)


class TestAlignModalVerbsRealCases(unittest.TestCase):
    """基于 W6 D3 真顽疾的 8 条 dim4 错回归测试"""

    def test_Q077_yi_to_ying(self):
        """Q077: 采光与照明控制 '宜→应'"""
        chunks = ["对于有天然采光的场所，宜采用与采光相关联的照明控制系统。"]
        answer = "对于有天然采光的场所，应采用与采光相关联的照明控制系统。"
        aligned, n = align_modal_verbs(answer, chunks)
        self.assertEqual(n, 1)
        self.assertIn("宜采用与采光", aligned)

    def test_Q139_yi_to_ying(self):
        """Q139: 特殊教育 '宜→应'"""
        chunks = ["7.2.1 教室宜布置在地面较低楼层。"]
        answer = "教室应布置在地面较低楼层。"
        aligned, n = align_modal_verbs(answer, chunks)
        self.assertEqual(n, 1)
        self.assertIn("宜布置在", aligned)


class TestDetectModalVerbDiffs(unittest.TestCase):
    """detect 模式（不修改，仅报告）"""

    def test_detect_returns_diffs(self):
        chunks = ["服务半径宜为 300m。"]
        answer = "服务半径应为 300m。"
        diffs = detect_modal_verb_diffs(answer, chunks)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0]["answer_verb"], "应")
        self.assertEqual(diffs[0]["chunks_verb"], "宜")

    def test_detect_no_diff_when_aligned(self):
        chunks = ["服务半径宜为 300m。"]
        answer = "服务半径宜为 300m。"
        diffs = detect_modal_verb_diffs(answer, chunks)
        self.assertEqual(diffs, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
