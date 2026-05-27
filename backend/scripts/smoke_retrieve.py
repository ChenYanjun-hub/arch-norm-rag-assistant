"""端到端检索冒烟测试（W1-T2 验收）。

跑一组针对 GB 50180-2018 的典型 query，看 top-5 召回是否准确。
不接 reranker、不接 LLM、不验严格排序——只看"相关 chunk 是否进入 top-5"。

用法：
    cd backend
    .venv/bin/python -m scripts.smoke_retrieve

输出：
  - 每条 query 的 top-5 chunks（chunk_id + score + 摘要）
  - 简易命中评估（与预期 clause 对比）
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("smoke_retrieve")


# 典型 query + 预期命中的 clause（用于人工评估，非自动 assert）
TEST_QUERIES: list[dict] = [
    {
        "query": "居住区配套幼儿园的服务半径不应大于多少米？",
        "expect_clause_in_top5": ["5.0.3", "表5.0.3"],
        "note": "查具体数值类（服务半径 = 300m）",
    },
    {
        "query": "居住街坊的集中绿地面积有什么要求？",
        "expect_clause_in_top5": ["4.0.7"],
        "note": "查规定类条文",
    },
    {
        "query": "居住区规划设计应遵循什么原则？",
        "expect_clause_in_top5": ["3.0.1"],
        "note": "查原则性条文",
    },
    {
        "query": "住宅建筑间距怎么确定？",
        "expect_clause_in_top5": ["4.0.8"],
        "note": "查工程实操类",
    },
    {
        "query": "居住区道路边缘到建筑物的最小距离",
        "expect_clause_in_top5": ["6.0.5", "表6.0.5"],
        "note": "查表格类",
    },
]


def main() -> int:
    from app.rag.embedder import embed_one
    from app.rag.retriever import count, search

    n = count()
    logger.info(f"[smoke] Qdrant collection 当前条目数: {n}")
    if n == 0:
        logger.error("[smoke] collection 为空，先跑 ingest.py")
        return 2

    print()
    print("=" * 80)
    print("  端到端检索冒烟测试 · 5 条典型 query × top-5")
    print("=" * 80)

    hit_total = 0
    for i, tc in enumerate(TEST_QUERIES, start=1):
        query = tc["query"]
        expected: list[str] = tc["expect_clause_in_top5"]

        qvec = embed_one(query)
        results = search(qvec, top_k=5, spec_code_filter="GB 50180-2018")

        # 命中判定
        top_clauses = [r["payload"].get("clause", "") for r in results]
        hit = any(any(exp in c for c in top_clauses) for exp in expected)
        hit_total += int(hit)

        print(f"\n[{i}/{len(TEST_QUERIES)}] query: {query}")
        print(f"    note: {tc['note']}")
        print(f"    expect clause in top-5: {expected}")
        print(f"    {'✅ HIT' if hit else '❌ MISS'}")
        for rank, r in enumerate(results, start=1):
            p = r["payload"]
            print(
                f"      #{rank} score={r['score']:.3f} | "
                f"[{p.get('type', '?')}] clause={p.get('clause', '?')} | "
                f"mandatory={p.get('is_mandatory')} | page={p.get('page_start')}"
            )
            print(f"          text: {p.get('text', '')[:60]}...")

    print()
    print("=" * 80)
    print(f"  汇总：Hit Rate@5 = {hit_total}/{len(TEST_QUERIES)} = "
          f"{hit_total/len(TEST_QUERIES):.0%}")
    print("=" * 80)
    print()
    return 0 if hit_total >= 4 else 1  # ≥80% 视为通过


if __name__ == "__main__":
    sys.exit(main())
