"""W7：引用核验 verifier 单元测试 — 锁定 verdict 解析 + 片段块拼接。

verify_grounding 依赖 LLM（不单测），但 verdict 解析 / 一致性是纯逻辑，必须锁住：
  - grounded/issues 解析、有 issues 则 grounded 必为 False
  - ```json 围栏 / 前后解释 / 非法输入降级
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.rag.verifier import _build_chunks_block, _parse_verdict  # noqa: E402


class TestParseVerdict(unittest.TestCase):
    def test_grounded_true(self):
        v = _parse_verdict('{"grounded": true, "issues": []}')
        self.assertEqual(v, {"grounded": True, "issues": []})

    def test_issues_force_grounded_false(self):
        # 即便 LLM 写 grounded=true，有 issues 就必须判 False（一致性）
        v = _parse_verdict('{"grounded": true, "issues": ["GB 99999 不存在"]}')
        self.assertFalse(v["grounded"])
        self.assertEqual(v["issues"], ["GB 99999 不存在"])

    def test_json_fence_and_prefix(self):
        raw = '核查结果如下：\n```json\n{"grounded": false, "issues": ["500m 与原文不符"]}\n```'
        v = _parse_verdict(raw)
        self.assertFalse(v["grounded"])
        self.assertEqual(v["issues"], ["500m 与原文不符"])

    def test_blank_issues_filtered(self):
        v = _parse_verdict('{"grounded": false, "issues": ["", "  ", "真问题"]}')
        self.assertEqual(v["issues"], ["真问题"])

    def test_garbage_returns_none(self):
        self.assertIsNone(_parse_verdict(""))
        self.assertIsNone(_parse_verdict("没有 json"))
        self.assertIsNone(_parse_verdict("[1,2,3]"))  # 数组不是对象


class TestBuildChunksBlock(unittest.TestCase):
    def test_numbered_with_meta(self):
        chunks = [
            {"spec_code": "GB 50180-2018", "spec_name": "居住区标准", "clause": "表5.0.3", "text": "服务半径不宜大于300m"},
        ]
        block = _build_chunks_block(chunks)
        self.assertIn("[1]", block)
        self.assertIn("GB 50180-2018", block)
        self.assertIn("表5.0.3", block)
        self.assertIn("300m", block)


if __name__ == "__main__":
    unittest.main()
