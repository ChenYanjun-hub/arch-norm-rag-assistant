"""W7：Agent Router 单元测试 — 锁定路由规则行为。

路由决定每条 query 是否付 agent 的 LLM 成本，规则错了要么白花钱、要么该拆的不拆，
必须锁住三类信号 + 两条关键取舍（复合优先、具体指标名词判单点）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.agent_router import route  # noqa: E402


class TestToolRoute(unittest.TestCase):
    def test_catalog(self):
        for q in ["你收录了哪些消防规范？", "规范库里有哪些景观类规范？", "给我看下规范清单"]:
            self.assertEqual(route(q)["route"], "tool", q)

    def test_clause_lookup(self):
        for q in ["GB 50180-2018 第5.0.3条的原文是什么？", "GB 55037-2022 4.3.16 讲了什么？"]:
            self.assertEqual(route(q)["route"], "tool", q)

    def test_status(self):
        for q in ["GB 50016-2014 还是现行有效的吗？", "GB 50180-2018 作废了吗？"]:
            self.assertEqual(route(q)["route"], "tool", q)

    def test_spec_code_alone_is_not_tool(self):
        # 只提规范号但问内容 → 该走常规 RAG，不该去查表
        self.assertEqual(route("GB 50180-2018 里对绿地率是怎么规定的")["route"], "plain")


class TestDecomposeRoute(unittest.TestCase):
    def test_broad(self):
        for q in ["城市新区的道路建设有什么规范要求？", "城市地下道路设计要满足哪些基本要求？"]:
            self.assertEqual(route(q)["route"], "decompose", q)

    def test_compound(self):
        for q in [
            "高层办公建筑的耐火等级和防火分区面积要求？",
            "新建医院的建筑密度上限和容积率要求？",
            "建筑安全疏散出口的数量、位置和宽度应考虑哪些因素？",
        ]:
            self.assertEqual(route(q)["route"], "decompose", q)

    def test_compound_beats_metric_guard(self):
        # "净宽和净高"含具体指标名词，但并列结构是强信号 → 仍该拆
        r = route("消防车道净宽和净高要求？")
        self.assertEqual(r["route"], "decompose")
        self.assertEqual(r["matched"], "compound")


class TestPlainRoute(unittest.TestCase):
    def test_single_point(self):
        for q in ["防火墙的耐火极限要求是多少？", "住宅卧室的最小使用面积是多少？", "什么是公园绿地？"]:
            self.assertEqual(route(q)["route"], "plain", q)

    def test_broad_wording_but_specific_metric(self):
        # 措辞像发散、但落在具体量上 → 判单点（治误触发，省 LLM 成本）
        for q in [
            "幼儿园园址选择对服务半径有什么要求？",
            "填方路基对填料的最大粒径有什么要求？",
        ]:
            r = route(q)
            self.assertEqual(r["route"], "plain", q)
            self.assertEqual(r["matched"], "broad_but_specific", q)

    def test_empty(self):
        self.assertEqual(route("")["route"], "plain")
        self.assertEqual(route("   ")["route"], "plain")


class TestContract(unittest.TestCase):
    def test_always_returns_valid_route(self):
        for q in ["", "?", "你好", "GB", "和要求", "哪些", "aaa bbb ccc"]:
            self.assertIn(route(q)["route"], ("tool", "decompose", "plain"), q)


if __name__ == "__main__":
    unittest.main()
