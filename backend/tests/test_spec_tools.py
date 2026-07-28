"""W7：规范查询工具集单测 — 锁定 tool-agent 三个工具的确定性行为。

工具是 agent 的"手"，必须可靠：查得到要返回原文，查不到要老实说没有（不能让 agent 编）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.spec_tools import (  # noqa: E402
    TOOL_FUNCTIONS,
    TOOL_SCHEMAS,
    check_spec_status,
    list_specs,
    lookup_clause,
)


class TestListSpecs(unittest.TestCase):
    def test_all(self):
        r = list_specs()
        self.assertGreater(r["count"], 0)
        self.assertEqual(r["count"], len(r["specs"]))
        self.assertIn("spec_code", r["specs"][0])

    def test_domain_filter(self):
        r = list_specs("消防")
        self.assertGreater(r["count"], 0)
        self.assertTrue(all(s["domain"] == "消防" for s in r["specs"]))
        # 过滤后应少于全部
        self.assertLess(r["count"], list_specs()["count"])

    def test_unknown_domain_empty(self):
        r = list_specs("不存在的域")
        self.assertEqual(r["count"], 0)


class TestLookupClause(unittest.TestCase):
    def test_found_returns_text(self):
        r = lookup_clause("GB 50180-2018", "5.0.3")
        self.assertTrue(r["found"])
        self.assertTrue(r["text"])

    def test_spec_code_normalized(self):
        # 空格/大小写差异应能命中
        self.assertTrue(lookup_clause("gb50180-2018", "5.0.3")["found"])

    def test_not_found_gives_hint_not_fabrication(self):
        r = lookup_clause("GB 50180-2018", "99.99.99")
        self.assertFalse(r["found"])
        self.assertIn("hint", r)  # 给相近条文号，而不是编内容
        self.assertNotIn("text", r)

    def test_unknown_spec(self):
        r = lookup_clause("GB 99999-2099", "1.1.1")
        self.assertFalse(r["found"])


class TestCheckSpecStatus(unittest.TestCase):
    def test_in_corpus(self):
        r = check_spec_status("GB 50180-2018")
        self.assertTrue(r["in_corpus"])
        self.assertIn("status", r)

    def test_not_in_corpus(self):
        r = check_spec_status("GB 99999-2099")
        self.assertFalse(r["in_corpus"])


class TestToolSchemas(unittest.TestCase):
    def test_schema_matches_functions(self):
        names = {s["function"]["name"] for s in TOOL_SCHEMAS}
        self.assertEqual(names, set(TOOL_FUNCTIONS.keys()))

    def test_schema_shape(self):
        for s in TOOL_SCHEMAS:
            self.assertEqual(s["type"], "function")
            self.assertIn("description", s["function"])
            self.assertIn("parameters", s["function"])


if __name__ == "__main__":
    unittest.main()
