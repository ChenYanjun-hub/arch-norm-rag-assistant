"""W6 D1：从 chunks/*.json 重 embed + upsert 到 Qdrant（不重新分块）。

与 ingest.py 的区别：
  - ingest.py：从 PDF 开始 → 分块 → embed → upsert（会覆盖修过的 chunks）
  - reindex：直接读现有 chunks/*.json（保留 OCR 修复）→ embed → upsert

用法：
    python -m scripts.reindex_from_chunks            # 不清 Qdrant，覆盖 upsert
    python -m scripts.reindex_from_chunks --rebuild  # 清空 Qdrant collection 重建

注意：
  - 默认 upsert（按 chunk_id 覆盖），不删除 Qdrant 中已有但本次缺失的 point
  - --rebuild 会清空 collection，确保 1:1 一致
  - 重 ingest 大约 39 部规范 + ~6000 chunks，耗时 ~3-5 分钟（取决于 BGE-M3 速度）
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from app.core.config import settings  # noqa: E402
from app.rag.chunker import Chunk  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

CHUNKS_DIR = _BACKEND / "data" / "chunks"


def load_chunks_from_json() -> list[Chunk]:
    """从 chunks/*.json 读所有 chunks 并重建 Chunk dataclass。"""
    chunks: list[Chunk] = []
    for jf in sorted(CHUNKS_DIR.glob("*.json")):
        if jf.name.startswith("_"):
            continue
        data = json.loads(jf.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            continue
        for d in data:
            if not isinstance(d, dict):
                continue
            try:
                # 仅取 Chunk dataclass 字段，丢掉 ocr_fixed_v1 等扩展元数据
                chunk = Chunk(
                    chunk_id=d["chunk_id"],
                    spec_code=d["spec_code"],
                    spec_name=d["spec_name"],
                    chapter=d.get("chapter"),
                    section=d.get("section"),
                    clause=d["clause"],
                    type=d["type"],
                    text=d["text"],
                    page_start=d["page_start"],
                    page_end=d["page_end"],
                    is_mandatory=d["is_mandatory"],
                    domain=d["domain"],
                    source_pdf=d["source_pdf"],
                    char_count=d["char_count"],
                )
                chunks.append(chunk)
            except (KeyError, TypeError) as e:
                logger.warning(f"[reindex] 跳过 {d.get('chunk_id','?')}: {e}")
    return chunks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true",
                        help="清空 Qdrant collection 重建（推荐 OCR 修后用）")
    parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()

    t0 = time.time()

    logger.info("[reindex] 读取 chunks JSON ...")
    chunks = load_chunks_from_json()
    logger.info(f"[reindex] 共 {len(chunks)} 条 chunks")

    if not chunks:
        logger.error("[reindex] 没有 chunks，退出")
        return 1

    from app.rag.embedder import embed_texts
    from app.rag.retriever import ensure_collection, upsert_chunks

    if args.rebuild:
        logger.info("[reindex] --rebuild：清空 Qdrant collection")
        ensure_collection(recreate=True)
    else:
        ensure_collection(recreate=False)

    # 1. Embed
    logger.info(f"[reindex] 1/2 向量化 {len(chunks)} 条 chunks (batch={args.batch_size}) ...")
    t_embed = time.time()
    texts = [c.text for c in chunks]
    vectors = embed_texts(texts, batch_size=args.batch_size)
    logger.info(f"[reindex] embed 完成，{time.time()-t_embed:.1f}s")

    # 2. Upsert
    logger.info(f"[reindex] 2/2 upsert 到 Qdrant ...")
    t_upsert = time.time()
    n = upsert_chunks(chunks, vectors)
    logger.info(f"[reindex] upsert 完成，{n} 个 point，{time.time()-t_upsert:.1f}s")

    elapsed = time.time() - t0
    logger.info(f"[reindex] ✅ 全部完成，总耗时 {elapsed:.1f}s")

    # 验证：随便查一个 chunk（纯 sanity log，失败绝不影响 reindex 退出码）
    # search() 返回 list[dict]，每项 {score, payload}（非 ScoredPoint 对象）
    try:
        from app.rag.retriever import search
        test_q = "为发挥道路绿化在改善城市生态环境"
        test_vec = embed_texts([test_q], batch_size=1)[0]
        results = search(test_vec, top_k=3)
        if results:
            payload = results[0].get("payload", {})
            logger.info(f"[reindex] 验证检索 top1: {payload.get('chunk_id')}")
            text_preview = (payload.get("text") or "")[:80]
            logger.info(f"[reindex] top1 text: {text_preview}...")
    except Exception as e:  # 验证失败不致命：upsert 已成功
        logger.warning(f"[reindex] 收尾验证跳过（非致命）：{e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
