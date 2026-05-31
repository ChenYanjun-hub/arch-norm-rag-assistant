"""BM25 关键词检索索引（W3 D3 加 · Hybrid 检索补 BGE-M3 语义偏）。

背景：W3 D2 评测发现，BGE-M3 在专业术语精确匹配上有偏差。
例：Q009 "高层民用建筑分类标准？" → expected GB 55037-2022 5.1.1
    BGE-M3 把它语义匹到 "5.2/5.3 防火等级"，错过 5.1 章节
    但 BM25 对 "高层民用建筑" "分类" 这类专有关键词的精确召回很强

方案：内存 BM25Okapi + jieba 分词。启动时一次性建索引（4773 chunks ~10MB）。

接口：
    bm25_search(query, top_k=20) → list[{score, payload}]
    返回结构与 retriever.search() 一致，方便后续 RRF 融合

设计取舍：
- 数据源用 chunks JSON 目录（跟 ingest 数据源一致，不依赖 Qdrant）
- jieba 默认精确模式（HMM 关闭，确保分词稳定）
- 启动 lazy load，首次调用时建索引；进程内常驻
- 不入 Qdrant：避免重新 ingest 全库
"""

from __future__ import annotations

import glob
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import jieba
from rank_bm25 import BM25Okapi

from app.core.config import settings

logger = logging.getLogger(__name__)

# 关闭 jieba 启动信息（保持评测/服务日志干净）
jieba.setLogLevel(logging.WARNING)


# ── 索引数据结构 ────────────────────────────────────────────
# 全部常驻内存，单例

_bm25: BM25Okapi | None = None
_payloads: list[dict[str, Any]] = []   # 与 BM25 corpus 同序的 payload
_index_built_at_ms: float = 0.0


def _tokenize(text: str) -> list[str]:
    """jieba 分词，过滤空白和单字标点。

    专业术语保留：jieba 自带词典对"高层""耐火""建筑"等都有覆盖。
    """
    if not text:
        return []
    tokens = [
        t.strip()
        for t in jieba.cut(text, HMM=False)  # HMM=False 稳定可复现
    ]
    # 过滤纯空白和长度 < 1
    return [t for t in tokens if t and len(t) >= 1 and not t.isspace()]


def _load_chunks() -> list[dict[str, Any]]:
    """从 chunks JSON 目录加载所有 chunk payload。

    跟 ingest 数据源完全一致（避免 Qdrant 锁 + 简化依赖）。
    """
    chunks_dir = Path(settings.chunks_dir)
    if not chunks_dir.exists():
        logger.warning(f"[bm25] chunks 目录不存在: {chunks_dir}")
        return []

    out: list[dict[str, Any]] = []
    for fp in sorted(glob.glob(str(chunks_dir / "*.json"))):
        if fp.endswith("_ingest_report.json"):
            continue
        try:
            data = json.load(open(fp, encoding="utf-8"))
        except Exception as e:
            logger.warning(f"[bm25] 跳过损坏 chunks 文件 {fp}: {e}")
            continue
        if isinstance(data, list):
            for c in data:
                if isinstance(c, dict) and c.get("text"):
                    out.append(c)
    return out


def build_index() -> int:
    """构建（或重建）BM25 索引。返回索引的 chunk 数。

    线程不安全（首次构建后只读，无并发问题）。
    """
    global _bm25, _payloads, _index_built_at_ms

    t0 = time.time()
    payloads = _load_chunks()
    if not payloads:
        logger.warning("[bm25] 没有 chunks 可索引")
        _bm25 = None
        _payloads = []
        return 0

    # 分词
    corpus_tokens: list[list[str]] = []
    for p in payloads:
        tokens = _tokenize(p.get("text", ""))
        corpus_tokens.append(tokens)

    # 建 BM25Okapi（默认参数 k1=1.5, b=0.75，业界标准）
    _bm25 = BM25Okapi(corpus_tokens)
    _payloads = payloads
    elapsed_ms = (time.time() - t0) * 1000
    _index_built_at_ms = elapsed_ms

    logger.info(
        f"[bm25] 索引完成：{len(payloads)} chunks，"
        f"耗时 {elapsed_ms:.0f}ms（含分词）"
    )
    return len(payloads)


def get_index() -> tuple[BM25Okapi | None, list[dict[str, Any]]]:
    """返回索引单例。首次调用时 lazy build。"""
    global _bm25, _payloads
    if _bm25 is None:
        build_index()
    return _bm25, _payloads


def bm25_search(
    query: str,
    *,
    top_k: int = 20,
    domain_filter: str | None = None,
    spec_code_filter: str | None = None,
) -> list[dict[str, Any]]:
    """BM25 关键词检索。

    Args:
        query: 用户原始 query
        top_k: 返回前 N 条
        domain_filter: 可选 domain 限定
        spec_code_filter: 可选 spec_code 限定

    Returns:
        list[{"score": float, "payload": dict}]
        score 是 BM25 原始分数（非归一化），仅用于排序；
        RRF 融合时只用 rank，不依赖 score 量纲。
    """
    bm25, payloads = get_index()
    if bm25 is None or not payloads:
        return []

    q_tokens = _tokenize(query)
    if not q_tokens:
        return []

    # 全库 BM25 打分
    scores = bm25.get_scores(q_tokens)

    # 取 top_k * 4 候选（留余量给后续 filter）；如果有 filter 才放大
    extract_k = top_k * 4 if (domain_filter or spec_code_filter) else top_k

    # 按 score 降序拿候选 index
    # （len(payloads) 可能很大，但 4773 在 numpy 里 argpartition 极快）
    import numpy as np
    arr = np.asarray(scores)
    if extract_k >= len(arr):
        top_idx = np.argsort(-arr)
    else:
        top_idx = np.argpartition(-arr, extract_k - 1)[:extract_k]
        top_idx = top_idx[np.argsort(-arr[top_idx])]

    out: list[dict[str, Any]] = []
    for i in top_idx:
        s = float(arr[i])
        if s <= 0:
            # BM25 0 分意味着 query token 完全无匹配，跳过
            continue
        p = payloads[int(i)]
        if domain_filter and p.get("domain") != domain_filter:
            continue
        if spec_code_filter and p.get("spec_code") != spec_code_filter:
            continue
        out.append({"score": s, "payload": p})
        if len(out) >= top_k:
            break

    return out


def index_stats() -> dict[str, Any]:
    """返回索引状态（调试 / 观测用）。"""
    return {
        "built": _bm25 is not None,
        "n_chunks": len(_payloads),
        "build_ms": int(_index_built_at_ms),
    }
