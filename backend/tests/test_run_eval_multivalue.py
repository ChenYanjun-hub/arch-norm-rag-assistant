"""W7：run_eval 多值 GT 匹配单元测试 — 锁定 also_accept 解析 + 最小 rank 语义。

评测口径升级（v6→v7）给「同主题多值」题加了 also_accept 列（备选出处，任一命中即命中）。
匹配逻辑是评测正确性的关键，必须锁住：
  - 解析：空/单个/多个/无 clause/列缺失
  - rank：主 GT 与备选取最小 rank；strict 用备选自己 clause（双向子串）；loose 只比 spec
  - 向后兼容：无 also_accept 时行为等价于原单值匹配
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from scripts.run_eval import _best_hit_rank, _parse_also_accept  # noqa: E402


def _chunks(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    """[(spec_code, clause), ...] → 检索结果 chunk 列表（按 rank 顺序）。"""
    return [{"spec_code": s, "clause": c} for s, c in pairs]


class TestParseAlsoAccept(unittest.TestCase):
    def test_empty_and_missing(self):
        self.assertEqual(_parse_also_accept({}), [])
        self.assertEqual(_parse_also_accept({"also_accept": ""}), [])
        self.assertEqual(_parse_also_accept({"also_accept": "   "}), [])

    def test_single(self):
        self.assertEqual(
            _parse_also_accept({"also_accept": "JGJ 39-2016|3.1.3"}),
            [("JGJ 39-2016", "3.1.3")],
        )

    def test_multiple(self):
        self.assertEqual(
            _parse_also_accept({"also_accept": "JGJ 39-2016|3.1.3; GB 50442|4.2.1"}),
            [("JGJ 39-2016", "3.1.3"), ("GB 50442", "4.2.1")],
        )

    def test_no_clause(self):
        self.assertEqual(
            _parse_also_accept({"also_accept": "GB 50442-2018"}),
            [("GB 50442-2018", "")],
        )


class TestBestHitRankSingleValue(unittest.TestCase):
    """无备选时等价于原单值匹配（向后兼容）。"""

    def test_primary_strict_hit(self):
        chunks = _chunks(("X", "1"), ("GB 50180-2018", "5.0.3"))
        r = _best_hit_rank(chunks, "GB 50180-2018", "5.0.3", [], strict=True)
        self.assertEqual(r, 2)

    def test_primary_miss(self):
        chunks = _chunks(("X", "1"), ("Y", "2"))
        self.assertIsNone(_best_hit_rank(chunks, "GB 50180-2018", "5.0.3", [], strict=True))

    def test_loose_ignores_clause(self):
        chunks = _chunks(("GB 50180-2018", "9.9.9"))
        # strict：clause 不符 → miss；loose：只比 spec → 命中
        self.assertIsNone(_best_hit_rank(chunks, "GB 50180-2018", "5.0.3", [], strict=True))
        self.assertEqual(_best_hit_rank(chunks, "GB 50180-2018", "5.0.3", [], strict=False), 1)


class TestBestHitRankMultiValue(unittest.TestCase):
    def test_alt_hits_when_primary_misses(self):
        # 主 GT GB50180 未召回，备选 JGJ39 在 rank1 → 命中 rank1
        chunks = _chunks(("JGJ 39-2016", "3.1.3+3.2.2"), ("Z", "1"))
        alt = [("JGJ 39-2016", "3.1.3")]
        r = _best_hit_rank(chunks, "GB 50180-2018", "表5.0.3", alt, strict=True)
        self.assertEqual(r, 1)

    def test_takes_min_rank(self):
        # 主 GT 在 rank3，备选在 rank1 → 取最小 1
        chunks = _chunks(("JGJ 39-2016", "3.1.3"), ("Z", "1"), ("GB 50180-2018", "表5.0.3"))
        alt = [("JGJ 39-2016", "3.1.3")]
        r = _best_hit_rank(chunks, "GB 50180-2018", "表5.0.3", alt, strict=True)
        self.assertEqual(r, 1)

    def test_alt_strict_clause_bidirectional(self):
        # 备选 clause '3.1.3' 应双向子串命中 chunk 的复合条 '3.1.3+3.2.2'
        chunks = _chunks(("JGJ 39-2016", "3.1.3+3.2.2"))
        alt = [("JGJ 39-2016", "3.1.3")]
        self.assertEqual(_best_hit_rank(chunks, "NONE", "0", alt, strict=True), 1)

    def test_alt_spec_norm(self):
        # spec_code 标准化：'GB 50442 - 20XX' 与 chunk 'GB50442-20XX' 应匹配
        chunks = _chunks(("GB 50442 - 20XX", "4.2.1"))
        alt = [("GB 50442 - 20XX", "4.2.1")]
        self.assertEqual(_best_hit_rank(chunks, "NONE", "0", alt, strict=True), 1)

    def test_none_when_neither(self):
        chunks = _chunks(("W", "1"), ("Z", "2"))
        alt = [("JGJ 39-2016", "3.1.3")]
        self.assertIsNone(_best_hit_rank(chunks, "GB 50180-2018", "5.0.3", alt, strict=True))


if __name__ == "__main__":
    unittest.main()
