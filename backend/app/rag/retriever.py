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
    MatchAny,
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
    spec_code_filter: list[str] | None = None,
) -> list[dict[str, Any]]:
    """向量检索。

    Args:
        query_vector: 已编码的 query 向量
        top_k: 召回数量（CLAUDE.md E.2 默认 20 粗排）
        domain_filter: 可选 domain 限定（规划/建筑/景观/消防）
        spec_code_filter: 可选 spec_code 列表限定（多选，命中任一即可）

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
        # 多选：spec_code 命中列表中任一即可（每个 chunk 仅一个 spec_code）
        must_conds.append(
            FieldCondition(key="spec_code", match=MatchAny(any=list(spec_code_filter)))
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


# ── chunk 内容级去重（W3 D1 加） ──────────────────────────────
#
# 背景：chunker 的 _dN 后缀机制让"同 clause 号被切多次"——chunk_id 唯一但
# text 内容完全相同。GB 55037-2022 实测 422 chunks / 228 独立 clause，
# 1.85 倍重复率。直接导致：
#   - 向量检索 top-K 名额被同义内容连续占据（实测 rank 1+2 完全同 score）
#   - 真正不同 clause 的相关 chunk 被挤出 top-K
#
# 修复（短期）：在 pipeline 拿到 search 结果后调本函数去重，按
# (spec_code, normalized_text_prefix) 作为 key，保留最高 score 那条。
# 长期方案见 docs/design/chunker_v2.md。


def _norm_text_for_dedup(text: str, prefix_len: int = 200) -> str:
    """对 text 做轻量归一化，用于 dedup key。
    去全部空白 + 取前 prefix_len 字符。
    """
    return "".join((text or "").split())[:prefix_len]


# ── 多 query 检索融合（W3 D2 加） ───────────────────────────
#
# 背景：W3 D1 诊断发现 BGE-M3 在专业规范文本上有语义偏。query_rewriter
# 把 1 个 query 扩成多个变体后，每个变体独立 search 得到 top-K，需要
# 一种"互不冲突的合理融合"。RRF（Reciprocal Rank Fusion）是业界标准方法：
#
#   score(d) = Σ_q  1 / (k + rank_q(d))
#
# k 默认 60 是论文经验值。RRF 优点：
#   - 不依赖原始 score 的绝对量纲（不同 query 的 cosine 分布可能差很多）
#   - 对 rank 单调递减，多次出现的文档分数累加
#   - 实现 5 行内


def rrf_fuse(
    results_per_query: list[list[dict[str, Any]]],
    *,
    k: int = 60,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    """RRF 融合多路检索结果。

    Args:
        results_per_query: 每路 search 返回的 list[{score, payload}]，
                           顺序即排名（已按 score 降序）
        k: RRF 常数（业界标准 60）
        top_k: 融合后返回前 N 条；None 表示返回全部

    Returns:
        融合后的列表，按 RRF 分数降序；每项含
        {"score": rrf_score (float), "payload": payload, "_rrf_contrib": int}
        其中 _rrf_contrib 是该文档被多少路命中（用于可观测性）

    唯一标识：优先用 payload["chunk_id"]，缺失时退化用文本前缀 hash。
    """
    if not results_per_query:
        return []

    accum: dict[str, dict[str, Any]] = {}
    for results in results_per_query:
        for rank, r in enumerate(results, start=1):
            p = r.get("payload") or {}
            doc_id = p.get("chunk_id")
            if not doc_id:
                # 退化方案：spec_code + 文本前缀
                doc_id = (p.get("spec_code") or "") + "#" + (p.get("text") or "")[:100]

            entry = accum.get(doc_id)
            if entry is None:
                entry = {"score": 0.0, "payload": p, "_rrf_contrib": 0}
                accum[doc_id] = entry
            entry["score"] += 1.0 / (k + rank)
            entry["_rrf_contrib"] += 1

    fused = sorted(accum.values(), key=lambda x: x["score"], reverse=True)
    if top_k is not None:
        fused = fused[:top_k]
    logger.info(
        f"[retriever] rrf_fuse: {len(results_per_query)} 路 "
        f"→ {len(fused)} 唯一文档（k={k}）"
    )
    return fused


def dedup_results(
    results: list[dict[str, Any]],
    *,
    prefix_len: int = 200,
) -> list[dict[str, Any]]:
    """按 (spec_code, normalized_text_prefix) 对 search 结果去重。

    Args:
        results: search() 返回值，按 score 降序
        prefix_len: 文本前缀长度用于比对

    Returns:
        去重后的列表，保持 score 降序；同 key 保留 score 最高的那条
        （即第一次出现的，因为输入已按 score 降序）

    日志：去重前后数量
    """
    if not results:
        return results
    seen: set[tuple[str, str]] = set()
    kept: list[dict[str, Any]] = []
    for r in results:
        p = r.get("payload") or {}
        key = (
            (p.get("spec_code") or "").strip(),
            _norm_text_for_dedup(p.get("text") or "", prefix_len),
        )
        if key in seen:
            continue
        seen.add(key)
        kept.append(r)
    if len(kept) < len(results):
        logger.info(
            f"[retriever] dedup: {len(results)} → {len(kept)} "
            f"（去掉 {len(results)-len(kept)} 个 chunker _dN 重复）"
        )
    return kept
