"""端到端检索冒烟测试（W1-T2 / W1-T3 验收）。

两组测试：
  - 单规范定向 query（GB 50180-2018 内 5 条）→ 验证 chunker 元数据有效
  - 跨规范开放 query（不限 spec_code，依赖 domain 过滤）→ 验证全量入库后的"跨规范"能力

不接 reranker、不接 LLM——只看"相关 chunk 是否进入 top-5"。

用法：
    cd backend
    .venv/bin/python -m scripts.smoke_retrieve            # 跑两组
    .venv/bin/python -m scripts.smoke_retrieve --single   # 只跑单规范定向
    .venv/bin/python -m scripts.smoke_retrieve --cross    # 只跑跨规范

输出：
  - 每条 query 的 top-5 chunks（chunk_id + score + 摘要）
  - 简易命中评估（与预期 clause / spec_code 对比）
"""

from __future__ import annotations

import argparse
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


# ── 组 1：单规范定向 query（限 spec_code）──
SINGLE_SPEC_QUERIES: list[dict] = [
    {
        "query": "居住区配套幼儿园的服务半径不应大于多少米？",
        "spec_code": "GB 50180-2018",
        "expect_clause_in_top5": ["5.0.3", "表5.0.3"],
        "note": "查具体数值类（服务半径 = 300m）",
    },
    {
        "query": "居住街坊的集中绿地面积有什么要求？",
        "spec_code": "GB 50180-2018",
        "expect_clause_in_top5": ["4.0.7"],
        "note": "查规定类条文",
    },
    {
        "query": "居住区规划设计应遵循什么原则？",
        "spec_code": "GB 50180-2018",
        "expect_clause_in_top5": ["3.0.1"],
        "note": "查原则性条文",
    },
    {
        "query": "住宅建筑间距怎么确定？",
        "spec_code": "GB 50180-2018",
        "expect_clause_in_top5": ["4.0.8"],
        "note": "查工程实操类",
    },
    {
        "query": "居住区道路边缘到建筑物的最小距离",
        "spec_code": "GB 50180-2018",
        "expect_clause_in_top5": ["6.0.5", "表6.0.5"],
        "note": "查表格类",
    },
]


# ── 组 2：跨规范开放 query（不限 spec_code，部分有 domain 过滤）──
CROSS_SPEC_QUERIES: list[dict] = [
    {
        "query": "幼儿园建筑的活动单元应该如何布置？",
        "domain": "建筑",
        "expect_spec_code_keywords": ["JGJ 39", "JGJ39"],
        "note": "应召回 JGJ39-2016《托儿所、幼儿园建筑设计规范》",
    },
    {
        "query": "城市道路绿化的种植设计有什么标准？",
        "domain": "景观",
        "expect_spec_code_keywords": ["CJJ/T 75", "CJJT 75", "CJJT75"],
        "note": "应召回 CJJ/T 75-2023《城市道路绿化设计标准》",
    },
    {
        "query": "建筑防火设计的耐火极限要求",
        "domain": "消防",
        "expect_spec_code_keywords": ["GB 55037", "GB55037"],
        "note": "应召回 GB 55037-2022《建筑防火通用规范》",
    },
    {
        "query": "城市综合交通规划的近期实施方案怎么编制",
        "domain": "规划",
        "expect_spec_code_keywords": ["GB/T 51328", "GBT 51328", "GBT51328"],
        "note": "应召回 GB/T 51328-2018《城市综合交通体系规划标准》",
    },
    {
        "query": "公共绿地的服务半径",
        "domain": None,  # 不加 domain 过滤
        "expect_spec_code_keywords": ["GB 50180", "GB50180", "GB/T 51346", "GBT 51346"],
        "note": "可能命中居住区规划 或 城市绿地规划标准",
    },
]


def _run_single_spec(embed_one, search) -> int:
    """组 1：单规范定向 query。返回命中数。"""
    print()
    print("=" * 80)
    print(f"  组 1：单规范定向 query（限 spec_code）· {len(SINGLE_SPEC_QUERIES)} 条 × top-5")
    print("=" * 80)

    hit_total = 0
    for i, tc in enumerate(SINGLE_SPEC_QUERIES, start=1):
        qvec = embed_one(tc["query"])
        results = search(
            qvec, top_k=5, spec_code_filter=tc["spec_code"]
        )

        top_clauses = [r["payload"].get("clause", "") for r in results]
        hit = any(any(exp in c for c in top_clauses) for exp in tc["expect_clause_in_top5"])
        hit_total += int(hit)

        print(f"\n[{i}/{len(SINGLE_SPEC_QUERIES)}] {tc['query']}")
        print(f"    note: {tc['note']}")
        print(f"    expect clause: {tc['expect_clause_in_top5']}")
        print(f"    {'✅ HIT' if hit else '❌ MISS'}")
        for rank, r in enumerate(results, start=1):
            p = r["payload"]
            print(
                f"      #{rank} score={r['score']:.3f} | "
                f"[{p.get('type', '?')}] clause={p.get('clause', '?')} | "
                f"page={p.get('page_start')}"
            )
    print(f"\n  组 1 汇总：Hit Rate@5 = {hit_total}/{len(SINGLE_SPEC_QUERIES)}")
    return hit_total


def _run_cross_spec(embed_one, search) -> int:
    """组 2：跨规范开放 query。返回命中数。"""
    print()
    print("=" * 80)
    print(f"  组 2：跨规范开放 query · {len(CROSS_SPEC_QUERIES)} 条 × top-5")
    print("=" * 80)

    hit_total = 0
    for i, tc in enumerate(CROSS_SPEC_QUERIES, start=1):
        qvec = embed_one(tc["query"])
        results = search(qvec, top_k=5, domain_filter=tc.get("domain"))

        top_specs = [r["payload"].get("spec_code", "") for r in results]
        hit = any(
            any(kw in code for code in top_specs)
            for kw in tc["expect_spec_code_keywords"]
        )
        hit_total += int(hit)

        print(f"\n[{i}/{len(CROSS_SPEC_QUERIES)}] {tc['query']}")
        print(f"    note: {tc['note']}")
        print(f"    domain={tc.get('domain', '∅')} | expect: {tc['expect_spec_code_keywords']}")
        print(f"    {'✅ HIT' if hit else '❌ MISS'}")
        for rank, r in enumerate(results, start=1):
            p = r["payload"]
            print(
                f"      #{rank} score={r['score']:.3f} | "
                f"{p.get('spec_code', '?')} {p.get('clause', '?')} "
                f"(domain={p.get('domain', '?')})"
            )
            print(f"          text: {p.get('text', '')[:60]}...")
    print(f"\n  组 2 汇总：Hit Rate@5 = {hit_total}/{len(CROSS_SPEC_QUERIES)}")
    return hit_total


def main() -> int:
    parser = argparse.ArgumentParser(description="端到端检索冒烟测试")
    parser.add_argument("--single", action="store_true", help="只跑单规范定向")
    parser.add_argument("--cross", action="store_true", help="只跑跨规范开放")
    args = parser.parse_args()
    run_single = args.single or (not args.single and not args.cross)
    run_cross = args.cross or (not args.single and not args.cross)

    from app.rag.embedder import embed_one
    from app.rag.retriever import count, search

    n = count()
    logger.info(f"[smoke] Qdrant collection 当前条目数: {n}")
    if n == 0:
        logger.error("[smoke] collection 为空，先跑 ingest.py")
        return 2

    hit_single = _run_single_spec(embed_one, search) if run_single else 0
    hit_cross = _run_cross_spec(embed_one, search) if run_cross else 0

    total_queries = (
        (len(SINGLE_SPEC_QUERIES) if run_single else 0)
        + (len(CROSS_SPEC_QUERIES) if run_cross else 0)
    )
    total_hits = hit_single + hit_cross
    print()
    print("=" * 80)
    print(f"  总汇总：Hit Rate@5 = {total_hits}/{total_queries} = "
          f"{total_hits/total_queries:.0%}")
    print("=" * 80)
    print()
    # ≥ 80% 视为通过
    return 0 if total_hits / total_queries >= 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())
