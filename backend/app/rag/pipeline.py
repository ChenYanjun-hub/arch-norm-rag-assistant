"""RAG 端到端流程编排（W2 阶段 v0.1）。

当前实现（最简端到端）：
    1. 输入校验
    2. 向量化 query
    3. 检索 top-k (Qdrant)
    4. 过滤低相关性 chunks（< min_relevance）
    5. 若无结果 → 返回 NO_RESULT_REPLY 兜底
    6. 否则 → 注入 chunks 进 Prompt → DeepSeek 流式生成
    7. 流末追加 citations 事件 + done 事件

未实现（W2 后续 / V2）：
    - 场景识别（闲聊/模糊/超范围/敏感）
    - 8 类边界兜底
    - Rerank（top-20 → top-5）
    - 多轮对话历史

接口：
    run_rag_sync(query) → Iterator[dict] —— SSE 事件流（CLI / FastAPI 都用）
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from app.core.config import RERANK_ENABLED, RERANK_MIN_SCORE, RETRIEVAL_CONFIG
from app.core.prompts import (
    NO_RESULT_REPLY,
    SYSTEM_PROMPT_MAIN,
    build_user_prompt,
)
from app.rag.embedder import embed_one
from app.rag.generator import stream_chat_sync
from app.rag.retriever import search
from app.services.fallback import FALLBACK_CHITCHAT, FALLBACK_OUT_OF_SCOPE
from app.services.scenario import detect_scenario

logger = logging.getLogger(__name__)


def _select_relevant_chunks(
    raw: list[dict[str, Any]], min_relevance: float
) -> list[dict[str, Any]]:
    """按相关性阈值过滤检索结果，返回 payload 列表（不含 score）。"""
    return [r["payload"] for r in raw if r["score"] >= min_relevance]


def _build_citation(chunk_payload: dict[str, Any]) -> dict[str, Any]:
    """从 chunk payload 抽取引用元数据（对应 schemas.Citation）。"""
    return {
        "spec_name": chunk_payload.get("spec_name", ""),
        "spec_code": chunk_payload.get("spec_code", ""),
        "clause": chunk_payload.get("clause", ""),
        "page": chunk_payload.get("page_start") or chunk_payload.get("page"),
        "is_mandatory": bool(chunk_payload.get("is_mandatory", False)),
        "original_text": (chunk_payload.get("text") or "")[:200],
        "domain": chunk_payload.get("domain", ""),
    }


def run_rag_sync(
    query: str,
    *,
    domain_filter: str | None = None,
    spec_code_filter: str | None = None,
    top_k: int | None = None,
) -> Iterator[dict[str, Any]]:
    """端到端 RAG（同步流式）。

    Yields:
        {"type": "retrieval", "data": {"n_candidates": int, "n_kept": int}}
        {"type": "token", "data": "..."}
        ...
        {"type": "citations", "data": [Citation, ...]}
        {"type": "done", "data": {"ttft_ms": int, "total_ms": int, "tokens_out": int}}
        {"type": "error", "data": "..."}
        {"type": "fallback", "data": "no_result" | "...}}
    """
    query = (query or "").strip()
    if not query:
        yield {"type": "error", "data": "INPUT_EMPTY: query 不能为空"}
        return
    if len(query) > 500:
        yield {"type": "error", "data": "INPUT_TOO_LONG: query 超过 500 字符上限"}
        return

    logger.info(f"[pipeline] query={query[:60]!r} domain={domain_filter} spec={spec_code_filter}")

    # ── 场景识别短路（CLAUDE.md E.4 判定优先级）──
    scenario = detect_scenario(query)
    if scenario in ("chitchat", "out_of_scope"):
        reply = FALLBACK_CHITCHAT if scenario == "chitchat" else FALLBACK_OUT_OF_SCOPE
        for ch in reply:
            yield {"type": "token", "data": ch}
        yield {"type": "fallback", "data": scenario}
        yield {"type": "done", "data": {"ttft_ms": 0, "total_ms": 0, "tokens_out": len(reply)}}
        return

    # 检索
    top_k_rough = int(top_k or RETRIEVAL_CONFIG["top_k_rough"])
    min_relevance = float(RETRIEVAL_CONFIG["min_relevance"])

    try:
        qvec = embed_one(query)
    except Exception as e:
        logger.exception(f"[pipeline] embed 失败: {e}")
        yield {"type": "error", "data": f"RETRIEVAL_EMBED_FAILED: {e}"}
        return

    try:
        raw_results = search(
            qvec,
            top_k=top_k_rough,
            domain_filter=domain_filter,
            spec_code_filter=spec_code_filter,
        )
    except Exception as e:
        logger.exception(f"[pipeline] search 失败: {e}")
        yield {"type": "error", "data": f"RETRIEVAL_SEARCH_FAILED: {e}"}
        return

    top_k_use = int(RETRIEVAL_CONFIG["top_k_rerank"])

    # 决策点：是否走 Reranker 精排
    rerank_used = False  # ★ 本次实际是否成功走 rerank（非 flag 状态）
    if RERANK_ENABLED and raw_results:
        try:
            from app.rag.reranker import rerank
            reranked = rerank(
                query,
                raw_results,
                top_k=top_k_use,
                min_score=RERANK_MIN_SCORE,
            )
            # rerank 后用 reranker 自己的阈值；保留向量 score 作为 fallback 判定的元数据
            kept_payloads = [r["payload"] for r in reranked]
            rerank_used = True
        except Exception as e:
            logger.warning(f"[pipeline] rerank 失败，回退到 vector top-k：{e}")
            kept_payloads = _select_relevant_chunks(
                raw_results[:top_k_use], min_relevance
            )
    else:
        # 未启用 reranker：用向量相关性阈值过滤
        kept_payloads = _select_relevant_chunks(raw_results[:top_k_use], min_relevance)

    yield {
        "type": "retrieval",
        "data": {
            "n_candidates": len(raw_results),
            "n_kept": len(kept_payloads),
            "min_relevance": min_relevance,
            "reranked": rerank_used,  # ★ 实际状态，非 flag
        },
    }

    if not kept_payloads:
        logger.warning(f"[pipeline] 检索无结果（min_relevance={min_relevance}）→ 兜底")
        # 兜底回复直接 yield 为单条 token + done
        for ch in NO_RESULT_REPLY:
            yield {"type": "token", "data": ch}
        yield {"type": "fallback", "data": "no_result"}
        yield {"type": "done", "data": {"ttft_ms": 0, "total_ms": 0, "tokens_out": len(NO_RESULT_REPLY)}}
        return

    # 构造 LLM messages
    user_msg = build_user_prompt(query, kept_payloads)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_MAIN},
        {"role": "user", "content": user_msg},
    ]

    # 流式生成；done 事件之前补 citations
    done_event: dict[str, Any] | None = None
    for evt in stream_chat_sync(messages):
        if evt["type"] == "done":
            done_event = evt
            break
        yield evt

    # citations 在 done 之前下发，让前端可以"答案完→显示引用"
    yield {
        "type": "citations",
        "data": [_build_citation(p) for p in kept_payloads],
    }
    if done_event:
        yield done_event
    else:
        yield {"type": "done", "data": {"ttft_ms": 0, "total_ms": 0, "tokens_out": 0}}
