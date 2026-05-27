"""检索：Qdrant 向量库（CLAUDE.md 附录锁定，不可换 Chroma / Milvus / Pinecone）。

部署模式（按环境变量 QDRANT_URL 自动切换）：
  - 本地文件模式：QDRANT_URL 为空或 file://...，使用 QdrantClient(path=...) 嵌入式持久化
                  适合开发期，零依赖，进程间共享数据
  - 远程服务模式：QDRANT_URL=http://localhost:6333，连接 Docker / 二进制 Qdrant
                  生产/团队协作模式

两种模式 API 完全一致，切换无需改业务代码（CLAUDE.md G.1 锁定栈不变）。

主要接口：
  - ensure_collection() — 启动时确保 collection 存在
  - upsert_chunks(chunks, vectors) — 批量入库
  - search(query_vec, top_k=20, domain_filter=None) — 向量检索（含可选 domain 过滤）
  - count() — 当前 collection 条目数
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Sequence

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import settings
from app.rag.chunker import Chunk
from app.rag.embedder import EMBED_DIM

logger = logging.getLogger(__name__)

# Qdrant collection 配置
COLLECTION_NAME = settings.qdrant_collection
DISTANCE_METRIC = Distance.COSINE  # CLAUDE.md E.2 指定 cosine


# ── 客户端单例 ──────────────────────────────────────────
_client: QdrantClient | None = None


def get_client() -> QdrantClient:
    """返回 Qdrant 客户端单例。

    模式选择：
      - 若 QDRANT_URL 以 http:// 或 https:// 开头 → 远程服务模式
      - 否则 → 本地文件嵌入模式，路径用 QDRANT_LOCAL_PATH
    """
    global _client
    if _client is not None:
        return _client

    url = settings.qdrant_url.strip()
    if url.startswith(("http://", "https://")):
        logger.info(f"[retriever] Qdrant 远程模式：url={url}")
        _client = QdrantClient(url=url, api_key=settings.qdrant_api_key or None)
    else:
        logger.info(f"[retriever] Qdrant 本地文件模式：path={settings.qdrant_local_path}")
        _client = QdrantClient(path=settings.qdrant_local_path)
    return _client


def ensure_collection(*, recreate: bool = False) -> None:
    """确保 collection 存在。recreate=True 时会先删除重建（清空数据）。"""
    client = get_client()
    existing = {c.name for c in client.get_collections().collections}

    if recreate and COLLECTION_NAME in existing:
        logger.warning(f"[retriever] 删除已有 collection: {COLLECTION_NAME}")
        client.delete_collection(COLLECTION_NAME)
        existing.discard(COLLECTION_NAME)

    if COLLECTION_NAME not in existing:
        logger.info(
            f"[retriever] 创建 collection: {COLLECTION_NAME} "
            f"(dim={EMBED_DIM}, distance={DISTANCE_METRIC})"
        )
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=EMBED_DIM, distance=DISTANCE_METRIC),
        )


def _chunk_id_to_uuid(chunk_id: str) -> str:
    """把可读的 chunk_id（如 'GB 50180-2018#5.0.3'）映射为 UUID5。

    Qdrant 要求 point id 是 unsigned int 或 UUID 字符串。
    用 NAMESPACE_OID + chunk_id 生成稳定 UUID，方便后续重跑去重。
    """
    return str(uuid.uuid5(uuid.NAMESPACE_OID, chunk_id))


def upsert_chunks(
    chunks: Sequence[Chunk],
    vectors: Sequence[Sequence[float]],
    *,
    batch_size: int = 64,
) -> int:
    """批量写入 chunks + 向量到 Qdrant。

    Args:
        chunks: list[Chunk]
        vectors: 对应顺序的向量列表，长度需等于 chunks
        batch_size: 单次 upsert 的 point 数

    Returns:
        实际写入的 point 数
    """
    if len(chunks) != len(vectors):
        raise ValueError(
            f"chunks/vectors 长度不匹配：{len(chunks)} vs {len(vectors)}"
        )
    if not chunks:
        return 0

    client = get_client()
    total = 0
    for start in range(0, len(chunks), batch_size):
        batch_chunks = chunks[start : start + batch_size]
        batch_vecs = vectors[start : start + batch_size]
        points = [
            PointStruct(
                id=_chunk_id_to_uuid(c.chunk_id),
                vector=list(v),
                payload=c.to_dict(),
            )
            for c, v in zip(batch_chunks, batch_vecs)
        ]
        client.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)
        total += len(points)
    logger.info(f"[retriever] upsert 完成：{total} 个 points")
    return total


def search(
    query_vector: Sequence[float],
    *,
    top_k: int = 20,
    domain_filter: str | None = None,
    spec_code_filter: str | None = None,
) -> list[dict[str, Any]]:
    """向量检索。

    Args:
        query_vector: 已编码的 query 向量
        top_k: 召回数量（CLAUDE.md E.2 默认 20 粗排）
        domain_filter: 可选 domain 限定（规划/建筑/景观/消防）
        spec_code_filter: 可选 spec_code 限定（如 "GB 50180-2018"）

    Returns:
        list[dict]，每项含 {score, payload}
    """
    client = get_client()

    must_conds: list[FieldCondition] = []
    if domain_filter:
        must_conds.append(
            FieldCondition(key="domain", match=MatchValue(value=domain_filter))
        )
    if spec_code_filter:
        must_conds.append(
            FieldCondition(key="spec_code", match=MatchValue(value=spec_code_filter))
        )

    query_filter = Filter(must=must_conds) if must_conds else None

    # qdrant-client 1.18 推荐用 query_points
    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=list(query_vector),
        limit=top_k,
        query_filter=query_filter,
        with_payload=True,
    ).points

    return [{"score": p.score, "payload": p.payload} for p in results]


def count() -> int:
    """返回当前 collection 内 point 数。"""
    client = get_client()
    try:
        return client.count(collection_name=COLLECTION_NAME).count
    except Exception:
        return 0
