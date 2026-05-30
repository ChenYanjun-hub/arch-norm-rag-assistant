"""重排：BGE-Reranker-v2-m3（CLAUDE.md 附录锁定，不可换 Cohere）。

输入：query + top-k 粗排 chunks
输出：按 cross-encoder 相关性降序的 top-N，且过滤低于 min_score 的项

策略：
- 模块级单例 + 延迟加载（首次调用才下载模型，实测约 2.3GB）
- 直接用 transformers 的 AutoModelForSequenceClassification（绕开 FlagEmbedding 1.4.0
  与 transformers 5.x 的不兼容：FlagReranker 内部调用了已移除的
  XLMRobertaTokenizer.prepare_for_model API，导致每次精排都崩。
  本实现就是 cross-encoder 的标准用法：
      sigmoid(model(tokenizer(query, passage)).logits)
- 自动选择设备：MPS（M 系列 Mac）> CUDA > CPU
- 与 retriever 配合：粗排 top-20 → 精排 top-5
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

MODEL_NAME = "BAAI/bge-reranker-v2-m3"
MAX_LENGTH = 512  # XLM-R 输入上限
BATCH_SIZE = 8  # 每批 pair 数（20 候选 → 3 批；M 系列 Mac 每批数百 ms）

_lock = threading.Lock()
_instance: "_Reranker | None" = None


@dataclass
class _Reranker:
    """持有 tokenizer + model 的轻量结构。"""

    tokenizer: Any
    model: Any
    device: str


def _pick_device() -> str:
    """自动选择推理设备。"""
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def get_reranker() -> _Reranker:
    """返回单例。首次调用下载/加载模型权重。"""
    global _instance
    if _instance is not None:
        return _instance

    with _lock:
        if _instance is not None:
            return _instance

        logger.info(f"[reranker] 加载 {MODEL_NAME}（实测约 2.3GB）")
        # 延迟 import 避免模块导入时硬性依赖
        import torch
        from transformers import (  # type: ignore
            AutoModelForSequenceClassification,
            AutoTokenizer,
        )

        device = _pick_device()
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
        model.to(device)
        model.eval()
        # 关闭 grad（推理路径不会反向，但显式关掉省内存）
        for p in model.parameters():
            p.requires_grad = False

        _instance = _Reranker(tokenizer=tokenizer, model=model, device=device)
        logger.info(
            f"[reranker] 模型加载完成 device={device} "
            f"({type(model).__name__})"
        )
        return _instance


def _compute_scores(
    tokenizer: Any,
    model: Any,
    device: str,
    pairs: list[tuple[str, str]],
    batch_size: int = BATCH_SIZE,
) -> list[float]:
    """对 (query, passage) 对计算相关性 score（sigmoid 后 0~1）。"""
    import torch

    all_scores: list[float] = []
    for i in range(0, len(pairs), batch_size):
        batch = pairs[i : i + batch_size]
        queries = [p[0] for p in batch]
        passages = [p[1] for p in batch]
        inputs = tokenizer(
            queries,
            passages,
            padding=True,
            truncation=True,
            max_length=MAX_LENGTH,
            return_tensors="pt",
        )
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            logits = model(**inputs).logits.view(-1).float()
            scores = torch.sigmoid(logits).cpu().tolist()
        all_scores.extend(scores)
    return all_scores


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
        min_score: 精排分数下限（sigmoid 后 0~1），低于此值过滤

    Returns:
        list[{"score": float, "rerank_score": float, "payload": dict}]
        按 rerank_score 降序，保留原 vector score 便于调试

    异常：
        失败回退到 candidates[:top_k]（向量顺序），由 pipeline 上层负责日志
    """
    if not candidates:
        return []

    rk = get_reranker()
    pairs = [(query, c["payload"].get("text", "")) for c in candidates]

    try:
        scores = _compute_scores(rk.tokenizer, rk.model, rk.device, pairs)
    except Exception as e:
        # 抛出去由 pipeline 决定是否走 fallback；pipeline 已有 try/except
        logger.error(f"[reranker] 精排失败: {e}", exc_info=True)
        raise

    enriched = [
        {
            "score": c["score"],
            "rerank_score": float(s),
            "payload": c["payload"],
        }
        for c, s in zip(candidates, scores)
    ]

    enriched.sort(key=lambda x: x["rerank_score"], reverse=True)
    kept = [e for e in enriched if e["rerank_score"] >= min_score][:top_k]

    if kept:
        logger.info(
            f"[reranker] {len(candidates)} → {len(kept)} "
            f"(top={kept[0]['rerank_score']:.3f}, "
            f"min_kept={kept[-1]['rerank_score']:.3f})"
        )
    else:
        logger.warning(
            f"[reranker] {len(candidates)} → 0（全部低于阈值 {min_score}）"
        )
    return kept
