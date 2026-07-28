"""W7：查询分解 _parse_subqueries 单元测试 — 锁定 LLM 输出解析的容错。

decompose_query 本身依赖 LLM（不单测），但 JSON 解析是纯逻辑，必须锁住：
  - 裸数组 / ```json 围栏 / 前后有解释文字
  - 引号清洗（中英文）
  - 非法输入降级到 []
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.rag.query_decomposer import _parse_subqueries  # noqa: E402


class TestParseSubqueries(unittest.TestCase):
    def test_plain_array(self):
        self.assertEqual(
            _parse_subqueries('["子问题A", "子问题B"]'),
            ["子问题A", "子问题B"],
        )

    def test_single_element(self):
        self.assertEqual(_parse_subqueries('["原问题"]'), ["原问题"])

    def test_json_fence(self):
        raw = "```json\n[\"A\", \"B\"]\n```"
        self.assertEqual(_parse_subqueries(raw), ["A", "B"])

    def test_explanation_prefix(self):
        raw = '这是一个复合问题，拆解如下：["耐火等级要求", "防火分区面积"]'
        self.assertEqual(_parse_subqueries(raw), ["耐火等级要求", "防火分区面积"])

    def test_strips_quotes_and_blanks(self):
        # 元素含中文弯引号 / 空串应被清洗
        self.assertEqual(
            _parse_subqueries('["“带引号的”", "", "   ", "正常"]'),
            ["带引号的", "正常"],
        )

    def test_empty_and_garbage(self):
        self.assertEqual(_parse_subqueries(""), [])
        self.assertEqual(_parse_subqueries("没有任何数组"), [])
        self.assertEqual(_parse_subqueries("[坏的 json"), [])

    def test_non_list_json(self):
        self.assertEqual(_parse_subqueries('{"a": 1}'), [])


if __name__ == "__main__":
    unittest.main()
