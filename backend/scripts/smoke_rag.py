"""端到端 RAG 冒烟（W2 验收）。

输入 query，跑完整流水线：embed → retrieve → DeepSeek 流式生成 → 引用 + 性能日志。

用法：
    cd backend
    # 默认跑 5 条预设 query
    .venv/bin/python -m scripts.smoke_rag

    # 单条 query
    .venv/bin/python -m scripts.smoke_rag --query "幼儿园服务半径是多少？"

    # 限定规范
    .venv/bin/python -m scripts.smoke_rag --query "..." --spec "GB 50180-2018"

    # 限定 domain
    .venv/bin/python -m scripts.smoke_rag --query "..." --domain 消防

退出码：
    0 全部 query 成功（done 事件正常）
    非 0 任一 query 报错
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("smoke_rag")


# 默认 query 集，覆盖不同类型
DEFAULT_QUERIES: list[dict] = [
    {
        "query": "居住区配套幼儿园的服务半径不应大于多少米？",
        "note": "数值类查询",
    },
    {
        "query": "住宅建筑间距怎么确定？",
        "note": "工程实操类",
    },
    {
        "query": "建筑防火设计的耐火极限要求",
        "domain": "消防",
        "note": "跨规范 · 限 domain",
    },
    {
        "query": "幼儿园建筑的活动单元如何布置？",
        "note": "跨规范 · 不限 domain",
    },
    {
        "query": "我家楼上邻居装修能违反规范吗",
        "note": "边界 · 应触发不编造",
    },
]


def _run_one(query: str, *, domain: str | None, spec: str | None) -> tuple[bool, str]:
    """跑单条 query，返回 (success, full_answer)。"""
    from app.rag.pipeline import run_rag_sync

    print(f"\n{'=' * 80}")
    print(f"  query: {query}")
    if domain:
        print(f"  domain: {domain}")
    if spec:
        print(f"  spec: {spec}")
    print("=" * 80)

    answer_parts: list[str] = []
    citations: list[dict] = []
    error_msg: str | None = None
    done_meta: dict | None = None
    retrieval_meta: dict | None = None

    t0 = time.time()
    print("\n  💬 回答：", end="", flush=True)
    for evt in run_rag_sync(query, domain_filter=domain, spec_code_filter=spec):
        et = evt["type"]
        if et == "token":
            print(evt["data"], end="", flush=True)
            answer_parts.append(evt["data"])
        elif et == "retrieval":
            retrieval_meta = evt["data"]
        elif et == "citations":
            citations = evt["data"]
        elif et == "done":
            done_meta = evt["data"]
        elif et == "error":
            error_msg = evt["data"]
            print(f"\n  ❌ ERROR: {error_msg}")
        elif et == "fallback":
            print(f"\n  ⚠ fallback: {evt['data']}")

    elapsed = time.time() - t0
    print()

    if retrieval_meta:
        print(
            f"\n  🔍 检索：候选 {retrieval_meta['n_candidates']} → "
            f"保留 {retrieval_meta['n_kept']}（阈值 {retrieval_meta['min_relevance']}）"
        )

    if citations:
        print(f"\n  📚 引用（{len(citations)} 条）：")
        for i, c in enumerate(citations, start=1):
            mandatory = " · 强制性" if c.get("is_mandatory") else ""
            print(
                f"    [{i}] 《{c['spec_name']}》{c['spec_code']} "
                f"{c['clause']}（第 {c['page']} 页{mandatory}）"
            )

    if done_meta:
        print(
            f"\n  ⏱  性能：TTFT={done_meta['ttft_ms']}ms · "
            f"总 {done_meta['total_ms']}ms · tokens={done_meta['tokens_out']} · "
            f"wall {elapsed:.1f}s"
        )

    success = error_msg is None
    return success, "".join(answer_parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="端到端 RAG 冒烟测试")
    parser.add_argument("--query", help="单条 query；不传则跑默认 5 条")
    parser.add_argument("--domain", help="可选 domain（规划/建筑/景观/消防）")
    parser.add_argument("--spec", help="可选 spec_code")
    args = parser.parse_args()

    if args.query:
        ok, _ = _run_one(args.query, domain=args.domain, spec=args.spec)
        return 0 if ok else 1

    # 跑默认套件
    n_ok = 0
    for i, tc in enumerate(DEFAULT_QUERIES, start=1):
        print(f"\n\n[{i}/{len(DEFAULT_QUERIES)}] note: {tc.get('note', '')}")
        ok, _ = _run_one(
            tc["query"],
            domain=tc.get("domain"),
            spec=tc.get("spec"),
        )
        n_ok += int(ok)

    print(f"\n\n{'=' * 80}")
    print(f"  汇总：{n_ok}/{len(DEFAULT_QUERIES)} 条 query 完成")
    print("=" * 80)
    return 0 if n_ok == len(DEFAULT_QUERIES) else 1


if __name__ == "__main__":
    sys.exit(main())
