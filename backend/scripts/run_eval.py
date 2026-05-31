"""评测集批跑脚本（W2 Day 3 检索层初版）。

用法（cwd = backend/）：
    .venv/bin/python -m scripts.run_eval                         # 跑全集
    .venv/bin/python -m scripts.run_eval --limit 20              # 小样本
    .venv/bin/python -m scripts.run_eval --no-rerank             # 关闭精排对比
    .venv/bin/python -m scripts.run_eval --top-k 10 --out custom.json

⚠️ 跑前请先停掉 backend（Qdrant 本地文件模式只允许一个进程访问）。

检索层指标（CLAUDE.md I.3）：
    Hit Rate@K = top-K 中是否有 chunk 匹配期望条文（0/1）
    MRR        = 1 / rank_of_first_hit，否则 0

匹配模式：
    strict : spec_code 标准化相等 AND clause 双向 substring
    loose  : 只要 spec_code 标准化相等（解决"同主题不同规范"误报）

边界兜底类 query（expected_spec 为空）不参与本次指标，单独统计。
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# 让 `python -m scripts.run_eval` 能找到 app/
_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

logger = logging.getLogger(__name__)

DEFAULT_CSV = _BACKEND / "data" / "eval" / "eval_set_v1_50.csv"
DEFAULT_OUT_DIR = _BACKEND / "data" / "eval" / "results"


# ── 匹配逻辑 ────────────────────────────────────────────────


def _norm_code(code: str) -> str:
    """spec_code 标准化：去全部空格 + 大写。'GB 50180-2018' → 'GB50180-2018'。"""
    return (code or "").replace(" ", "").replace("　", "").upper()


def _clause_match(expected: str, actual: str) -> bool:
    """clause 双向 substring 包含。
    expected='5.0.3' 命中 actual='5.0.3+5.0.4'；
    expected='表 5.0.3' 命中 actual='表 5.0.3'。
    """
    e = (expected or "").strip()
    a = (actual or "").strip()
    if not e or not a:
        return False
    return e in a or a in e


def _first_hit_rank(
    chunks: list[dict[str, Any]],
    expected_spec: str,
    expected_clause: str,
    *,
    strict: bool,
) -> int | None:
    """返回 1-based rank，若无命中返回 None。"""
    es = _norm_code(expected_spec)
    for i, c in enumerate(chunks, start=1):
        if _norm_code(c.get("spec_code", "")) != es:
            continue
        if strict and not _clause_match(expected_clause, c.get("clause", "")):
            continue
        return i
    return None


# ── 数据类 ──────────────────────────────────────────────────


@dataclass
class RowResult:
    """单条 query 的评测结果。"""

    id: str
    scenario: str
    difficulty: str
    spec_domain: str
    query: str
    expected_spec: str
    expected_clause: str
    rank_strict: int | None  # 严格匹配（spec_code+clause）的最佳 rank
    rank_loose: int | None  # 宽松匹配（只 spec_code）的最佳 rank
    top1_spec: str
    top1_clause: str
    top1_score: float
    rerank_used: bool
    elapsed_ms: int

    @property
    def hit5_strict(self) -> bool:
        return self.rank_strict is not None and self.rank_strict <= 5

    @property
    def hit10_strict(self) -> bool:
        return self.rank_strict is not None and self.rank_strict <= 10

    @property
    def hit5_loose(self) -> bool:
        return self.rank_loose is not None and self.rank_loose <= 5

    @property
    def hit10_loose(self) -> bool:
        return self.rank_loose is not None and self.rank_loose <= 10

    @property
    def mrr_strict(self) -> float:
        return 1.0 / self.rank_strict if self.rank_strict else 0.0

    @property
    def mrr_loose(self) -> float:
        return 1.0 / self.rank_loose if self.rank_loose else 0.0


@dataclass
class Summary:
    n: int
    hit5_strict: float
    hit10_strict: float
    mrr_strict: float
    hit5_loose: float
    hit10_loose: float
    mrr_loose: float


def _aggregate(rows: list[RowResult]) -> Summary:
    if not rows:
        return Summary(0, 0, 0, 0, 0, 0, 0)
    n = len(rows)
    return Summary(
        n=n,
        hit5_strict=sum(r.hit5_strict for r in rows) / n,
        hit10_strict=sum(r.hit10_strict for r in rows) / n,
        mrr_strict=sum(r.mrr_strict for r in rows) / n,
        hit5_loose=sum(r.hit5_loose for r in rows) / n,
        hit10_loose=sum(r.hit10_loose for r in rows) / n,
        mrr_loose=sum(r.mrr_loose for r in rows) / n,
    )


# ── 主流程 ──────────────────────────────────────────────────


def _load_csv(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _run_one(
    row: dict[str, str],
    *,
    top_k_retrieve: int,
    use_rerank: bool,
    rerank_top_k: int,
    use_dedup: bool,
    use_multi_query: bool,
    use_hybrid: bool,
    rerank_candidate_k: int = 30,
    passage_format: str = "clause_text",
    rrf_k: int = 60,
) -> RowResult | None:
    """跑单条 query。失败返回 None。"""
    from app.rag.embedder import embed_one
    from app.rag.query_rewriter import rewrite_query
    from app.rag.retriever import dedup_results, rrf_fuse, search

    query = row["query"].strip()
    expected_spec = row.get("expected_spec", "").strip()
    expected_clause = row.get("expected_clause", "").strip()

    t0 = time.time()
    try:
        # W3 D2：query 改写（攻 BGE-M3 语义偏）
        if use_multi_query:
            queries = rewrite_query(query)  # 失败时仅含原 query
        else:
            queries = [query]

        # W3 D1：dedup 时粗排放大 2× 补偿损耗
        rough_factor = 2 if use_dedup else 1

        # 顺序 embed + search（Qdrant 本地文件锁不能并发）
        # W3 D3：hybrid 时只让原 query (i=0) 也走 BM25，避免变体污染 + BM25 权重过大
        results_per_path: list[list[dict[str, Any]]] = []
        bm25_search_fn = None
        if use_hybrid:
            try:
                from app.rag.bm25_indexer import bm25_search as _bs
                bm25_search_fn = _bs
            except ImportError:
                pass

        for i, q in enumerate(queries):
            qvec = embed_one(q)
            vec_r = search(qvec, top_k=top_k_retrieve * rough_factor)
            results_per_path.append(vec_r)
            if i == 0 and bm25_search_fn is not None:
                bm25_r = bm25_search_fn(q, top_k=top_k_retrieve * rough_factor)
                results_per_path.append(bm25_r)

        # 多路 → RRF 融合；单路 → 直接用
        if len(results_per_path) > 1:
            raw = rrf_fuse(
                results_per_path,
                k=rrf_k,
                top_k=top_k_retrieve * rough_factor,
            )
        else:
            raw = results_per_path[0] if results_per_path else []

        if use_dedup:
            # W3 D4：candidate 保留 rerank_candidate_k 条进 reranker（默认 30）
            raw = dedup_results(raw)[:rerank_candidate_k]
    except Exception as e:
        logger.error(f"[{row['id']}] retrieval failed: {e}")
        return None

    rerank_used = False
    if use_rerank and raw:
        try:
            from app.rag.reranker import rerank

            # W3 D4：评测时显式传 passage_format，方便对比 3 种格式
            reranked = rerank(
                query,
                raw,
                top_k=rerank_top_k,
                min_score=0.0,
                passage_format=passage_format,
            )
            chunks = [r["payload"] for r in reranked]
            top1_score = reranked[0]["rerank_score"] if reranked else 0.0
            rerank_used = True
        except Exception as e:
            logger.warning(f"[{row['id']}] rerank failed → vector top-k: {e}")
            chunks = [r["payload"] for r in raw[:rerank_top_k]]
            top1_score = raw[0]["score"] if raw else 0.0
    else:
        chunks = [r["payload"] for r in raw[:rerank_top_k]]
        top1_score = raw[0]["score"] if raw else 0.0

    elapsed_ms = int((time.time() - t0) * 1000)

    if not chunks:
        return RowResult(
            id=row["id"],
            scenario=row.get("scenario", ""),
            difficulty=row.get("difficulty", ""),
            spec_domain=row.get("spec_domain", ""),
            query=query,
            expected_spec=expected_spec,
            expected_clause=expected_clause,
            rank_strict=None,
            rank_loose=None,
            top1_spec="",
            top1_clause="",
            top1_score=0.0,
            rerank_used=rerank_used,
            elapsed_ms=elapsed_ms,
        )

    rank_strict = _first_hit_rank(
        chunks, expected_spec, expected_clause, strict=True
    )
    rank_loose = _first_hit_rank(
        chunks, expected_spec, expected_clause, strict=False
    )

    return RowResult(
        id=row["id"],
        scenario=row.get("scenario", ""),
        difficulty=row.get("difficulty", ""),
        spec_domain=row.get("spec_domain", ""),
        query=query,
        expected_spec=expected_spec,
        expected_clause=expected_clause,
        rank_strict=rank_strict,
        rank_loose=rank_loose,
        top1_spec=chunks[0].get("spec_code", ""),
        top1_clause=chunks[0].get("clause", ""),
        top1_score=float(top1_score),
        rerank_used=rerank_used,
        elapsed_ms=elapsed_ms,
    )


def _print_summary(label: str, s: Summary) -> None:
    """控制台 markdown 表格。"""
    if s.n == 0:
        print(f"\n## {label}\n（无样本）")
        return
    print(f"\n## {label}（n={s.n}）\n")
    print("| 指标 | strict | loose |")
    print("|---|---|---|")
    print(f"| Hit Rate@5  | **{s.hit5_strict:.1%}** | **{s.hit5_loose:.1%}** |")
    print(f"| Hit Rate@10 | {s.hit10_strict:.1%} | {s.hit10_loose:.1%} |")
    print(f"| MRR         | {s.mrr_strict:.3f} | {s.mrr_loose:.3f} |")


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 检索层评测")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--limit", type=int, default=0, help="0=全集")
    parser.add_argument(
        "--top-k-retrieve", type=int, default=20, help="粗排召回数"
    )
    parser.add_argument(
        "--rerank-top-k", type=int, default=10, help="评测时保留 top-N"
    )
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--no-dedup", action="store_true", help="关闭 chunker _dN 内容级去重，方便对比")
    parser.add_argument(
        "--no-multi-query",
        action="store_true",
        help="关闭 query 改写（多 query + RRF），方便对比",
    )
    parser.add_argument(
        "--no-hybrid",
        action="store_true",
        help="关闭 hybrid 检索（BM25 + 向量 RRF 融合），方便对比",
    )
    parser.add_argument(
        "--rerank-candidate-k",
        type=int,
        default=20,
        help="W3 D4：dedup 后保留 N 条给 reranker（默认 20=baseline 最优）",
    )
    parser.add_argument(
        "--passage-format",
        type=str,
        default="text_only",
        choices=["text_only", "clause_text", "rich"],
        help="W3 D4：reranker passage 拼接方式（默认 text_only=baseline 最优）",
    )
    parser.add_argument("--rrf-k", type=int, default=60, help="RRF 融合常数")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,  # 评测输出尽量干净
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    use_rerank = not args.no_rerank
    use_dedup = not args.no_dedup
    use_multi_query = not args.no_multi_query
    use_hybrid = not args.no_hybrid
    label = (
        f"rerank_{'on' if use_rerank else 'off'}"
        f"_dedup_{'on' if use_dedup else 'off'}"
        f"_mq_{'on' if use_multi_query else 'off'}"
        f"_hyb_{'on' if use_hybrid else 'off'}"
        f"_ck{args.rerank_candidate_k}"
        f"_pf-{args.passage_format}"
    )

    if not args.csv.exists():
        print(f"❌ 评测集 CSV 不存在：{args.csv}", file=sys.stderr)
        sys.exit(1)

    all_rows = _load_csv(args.csv)
    # 过滤：本次只评有 expected_spec 的（边界兜底 12 条单独统计）
    eval_rows = [r for r in all_rows if r.get("expected_spec", "").strip()]
    fallback_rows = [r for r in all_rows if not r.get("expected_spec", "").strip()]

    if args.limit > 0:
        eval_rows = eval_rows[: args.limit]

    print(
        f"\n🎯 评测开始：{label} | 总集 {len(all_rows)} 条 "
        f"| 本次评 {len(eval_rows)} 条 | 边界兜底 {len(fallback_rows)} 条（不评指标）"
    )
    print(
        f"   参数：top_k_retrieve={args.top_k_retrieve} "
        f"rerank_top_k={args.rerank_top_k} "
        f"dedup={use_dedup} "
        f"multi_query={use_multi_query} "
        f"hybrid={use_hybrid} "
        f"candidate_k={args.rerank_candidate_k} "
        f"passage_format={args.passage_format} "
        f"(rrf_k={args.rrf_k})\n"
    )

    results: list[RowResult] = []
    t_start = time.time()
    for i, row in enumerate(eval_rows, start=1):
        res = _run_one(
            row,
            top_k_retrieve=args.top_k_retrieve,
            use_rerank=use_rerank,
            rerank_top_k=args.rerank_top_k,
            use_dedup=use_dedup,
            use_multi_query=use_multi_query,
            use_hybrid=use_hybrid,
            rerank_candidate_k=args.rerank_candidate_k,
            passage_format=args.passage_format,
            rrf_k=args.rrf_k,
        )
        if res is None:
            continue
        results.append(res)
        flag = "✓" if res.hit5_loose else " "
        print(
            f"  [{flag}] {res.id} | rank_strict={res.rank_strict} "
            f"rank_loose={res.rank_loose} | "
            f"top1={res.top1_spec} {res.top1_clause} | {res.elapsed_ms}ms"
        )

    total_s = int(time.time() - t_start)
    print(f"\n⏱ 共 {len(results)} 条，耗时 {total_s}s（{total_s/max(len(results),1):.1f}s/条）")

    # ── 聚合 ──
    overall = _aggregate(results)
    _print_summary("总体", overall)

    by_domain: dict[str, list[RowResult]] = defaultdict(list)
    for r in results:
        by_domain[r.spec_domain].append(r)
    print("\n## 按规范域拆分\n")
    print("| 规范域 | n | Hit@5 (strict) | Hit@5 (loose) | MRR (loose) |")
    print("|---|---|---|---|---|")
    for dom in sorted(by_domain.keys()):
        s = _aggregate(by_domain[dom])
        print(
            f"| {dom} | {s.n} | {s.hit5_strict:.1%} "
            f"| {s.hit5_loose:.1%} | {s.mrr_loose:.3f} |"
        )

    by_diff: dict[str, list[RowResult]] = defaultdict(list)
    for r in results:
        by_diff[r.difficulty].append(r)
    print("\n## 按难度拆分\n")
    print("| 难度 | n | Hit@5 (strict) | Hit@5 (loose) | MRR (loose) |")
    print("|---|---|---|---|---|")
    for diff in sorted(by_diff.keys()):
        s = _aggregate(by_diff[diff])
        print(
            f"| {diff} | {s.n} | {s.hit5_strict:.1%} "
            f"| {s.hit5_loose:.1%} | {s.mrr_loose:.3f} |"
        )

    # ── 错例（strict miss 但 loose hit + 完全 miss）──
    print("\n## 错例（strict 未命中）\n")
    bad = [r for r in results if not r.hit5_strict]
    for r in bad[:10]:
        kind = "🟡同主题异规范" if r.hit5_loose else "🔴完全未命中"
        print(
            f"- {kind} {r.id} [{r.spec_domain}/{r.difficulty}] "
            f'"{r.query[:35]}…" → 期望 {r.expected_spec} {r.expected_clause}, '
            f"实际 top1 {r.top1_spec} {r.top1_clause}"
        )
    if len(bad) > 10:
        print(f"\n（还有 {len(bad)-10} 条未列出）")

    # ── 输出 JSON ──
    out_dir = args.out.parent if args.out else DEFAULT_OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = args.out or out_dir / f"eval_v1_50_{label}_{ts}.json"
    out_path.write_text(
        json.dumps(
            {
                "config": {
                    "csv": str(args.csv),
                    "use_rerank": use_rerank,
                    "use_dedup": use_dedup,
                    "use_multi_query": use_multi_query,
                    "use_hybrid": use_hybrid,
                    "rerank_candidate_k": args.rerank_candidate_k,
                    "passage_format": args.passage_format,
                    "rrf_k": args.rrf_k,
                    "top_k_retrieve": args.top_k_retrieve,
                    "rerank_top_k": args.rerank_top_k,
                    "n_eval": len(eval_rows),
                    "n_results": len(results),
                    "elapsed_s": total_s,
                    "timestamp": ts,
                },
                "overall": asdict(overall),
                "by_domain": {
                    k: asdict(_aggregate(v)) for k, v in by_domain.items()
                },
                "by_difficulty": {
                    k: asdict(_aggregate(v)) for k, v in by_diff.items()
                },
                "rows": [
                    {**asdict(r), "hit5_loose": r.hit5_loose,
                     "hit5_strict": r.hit5_strict,
                     "mrr_loose": r.mrr_loose,
                     "mrr_strict": r.mrr_strict}
                    for r in results
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n💾 JSON 报告已写入：{out_path}")


if __name__ == "__main__":
    main()
