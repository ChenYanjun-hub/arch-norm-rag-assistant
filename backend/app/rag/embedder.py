"""向量化：BGE-M3（CLAUDE.md 附录锁定，不可换 OpenAI embedding）。

依赖 FlagEmbedding 官方包。模型权重首次调用时从 HuggingFace 自动下载（约 2.3GB）。

接口设计：
  - 模块级单例 get_embedder() — 避免重复加载模型权重（加载约 30s）
  - embed_texts(list[str]) -> list[list[float]] — 同步批量编码
  - 输出维度固定 1024（BGE-M3 dense vector dim）

性能说明（CPU mode, M-series Mac）：
  - 加载模型：~30s（首次含下载更久）
  - 单条编码：~50-100ms
  - 批量 32 条：~1-2s
"""

from __future__ import annotations

import logging
import threading
from typing import Sequence

logger = logging.getLogger(__name__)

# BGE-M3 dense vector 维度（固定）
EMBED_DIM = 1024
MODEL_NAME = "BAAI/bge-m3"

_lock = threading.Lock()
_model_instance = None  # 延迟加载，避免 import 时就拉模型


def get_embedder():
    """返回 BGE-M3 模型单例。首次调用会下载/加载权重，可能耗时数十秒。"""
    global _model_instance
    if _model_instance is not None:
        return _model_instance

    with _lock:
        if _model_instance is not None:  # double-check
            return _model_instance

        logger.info(f"[embedder] 加载 BGE-M3 模型：{MODEL_NAME}（首次会下载约 2.3GB）")
        # 延迟 import 避免 chunker-only 模式时也拉 torch
        from FlagEmbedding import BGEM3FlagModel  # type: ignore

        # use_fp16=False 适配 CPU；GPU 时可设 True 加速
        _model_instance = BGEM3FlagModel(MODEL_NAME, use_fp16=False)
        logger.info("[embedder] 模型加载完成")
        return _model_instance


def embed_texts(
    texts: Sequence[str], *, batch_size: int = 32, max_length: int = 1024
) -> list[list[float]]:
    """批量编码文本为 dense vectors。

    Args:
        texts: 待编码文本列表
        batch_size: 每批大小（CPU 推荐 8-32）
        max_length: 单条文本最大 token 数（BGE-M3 上限 8192，本项目 chunk 远小于此）

    Returns:
        list[list[float]]，每个内部 list 长度 == EMBED_DIM (1024)

    Raises:
        ValueError: texts 为空
        RuntimeError: 模型加载/编码失败
    """
    if not texts:
        raise ValueError("embed_texts: texts 不能为空")

    model = get_embedder()
    try:
        result = model.encode(
            list(texts),
            batch_size=batch_size,
            max_length=max_length,
            return_dense=True,
            return_sparse=False,  # MVP 只用 dense
            return_colbert_vecs=False,
        )
    except Exception as e:
        raise RuntimeError(f"BGE-M3 编码失败: {e}") from e

    dense = result.get("dense_vecs")
    if dense is None:
        raise RuntimeError("BGE-M3 未返回 dense_vecs")

    # FlagEmbedding 返回 numpy ndarray，转 list[list[float]]
    return [vec.tolist() for vec in dense]


def embed_one(text: str) -> list[float]:
    """单条编码便捷封装（query 时常用）。"""
    return embed_texts([text])[0]
