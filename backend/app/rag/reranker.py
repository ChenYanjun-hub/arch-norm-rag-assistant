"""重排：BGE-Reranker-v2-m3（CLAUDE.md 附录锁定，不可换 Cohere）。

输入：query + top-k 粗排 chunks
输出：按 cross-encoder 相关性降序的 top-N，且过滤低于 min_score 的项

策略：
- 模块级单例 + 延迟加载（首次调用才下载模型，约 600MB）
- 支持 fp32 CPU 推理（M 系列 Mac 数百 ms / 20 个 pair）
- 与 retriever 配合：粗排 top-20 → 精排 top-5
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

MODEL_NAME = "BAAI/bge-reranker-v2-m3"

_lock = threading.Lock()
_model_instance = None


def get_reranker():
    """返回 BGE-Reranker-v2 单例。首次调用下载/加载模型权重。"""
    global _model_instance
    if _model_instance is not None:
        return _model_instance

    with _lock:
        if _model_instance is not None:
            return _model_instance

        logger.info(f"[reranker] 加载 {MODEL_NAME}（首次下载约 600MB）")
        from FlagEmbedding import FlagReranker  # type: ignore

        _model_instance = FlagReranker(MODEL_NAME, use_fp16=False)
        logger.info("[reranker] 模型加载完成")
        return _model_instance


def rerank(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    top_k: int = 5,
    min_score: float = 0.0,
) -> list[dict[str, Any]]:
    """对 retriever 召回的 candidates 做精排。

    Args:
        query: 用户原始 query
        candidates: list of {"score": float, "payload": dict}（retriever.search 输出）
        top_k: 保留前 N 个
        min_score: 精排分数下限，低于此值过滤

    Returns:
        list[{"score": float, "rerank_score": float, "payload": dict}]
        按 rerank_score 降序，保留原 vector score 便于调试
    """
    if not candidates:
        return []

    model = get_reranker()
    pairs = [(query, c["payload"].get("text", "")) for c in candidates]

    try:
        # FlagReranker.compute_score 返回 list[float] 或单个 float
        scores = model.compute_score(pairs, normalize=True)
        if not isinstance(scores, list):
            scores = [scores]
    except Exception as e:
        logger.error(f"[reranker] 精排失败，回退到原顺序: {e}")
        return candidates[:top_k]

    enriched = []
    for c, s in zip(candidates, scores):
        enriched.append(
            {
                "score": c["score"],
                "rerank_score": float(s),
                "payload": c["payload"],
            }
        )

    enriched.sort(key=lambda x: x["rerank_score"], reverse=True)
    kept = [e for e in enriched if e["rerank_score"] >= min_score][:top_k]
    logger.info(
        f"[reranker] {len(candidates)} → {len(kept)} "
        f"(top score={kept[0]['rerank_score']:.3f} if any)"
        if kept
        else f"[reranker] {len(candidates)} → 0（全部低于阈值 {min_score}）"
    )
    return kept
