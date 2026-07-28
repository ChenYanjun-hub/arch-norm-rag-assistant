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

from app.core.config import (
    HYBRID_BM25_TOP_K,
    HYBRID_ENABLED,
    MULTI_QUERY_ENABLED,
    MULTI_QUERY_RRF_K,
    QUERY_DECOMPOSE_ENABLED,
    RERANK_CANDIDATE_K,
    RERANK_ENABLED,
    RERANK_MIN_SCORE,
    RETRIEVAL_CONFIG,
)
from app.core.prompts import (
    NO_RESULT_REPLY,
    SYSTEM_PROMPT_MAIN,
    build_user_prompt,
)
from app.rag.embedder import embed_one
from app.rag.generator import stream_chat_sync
from app.rag.query_rewriter import rewrite_query
from app.rag.retriever import dedup_results, rrf_fuse, search
from app.services.fallback import (
    FALLBACK_AMBIGUOUS,
    FALLBACK_CHITCHAT,
    FALLBACK_INPUT_EMPTY,
    FALLBACK_INPUT_TOO_LONG,
    FALLBACK_OUT_OF_SCOPE,
    FALLBACK_SENSITIVE,
    build_fallback_deprecated,
)
from app.services.scenario import _detect_deprecated, detect_scenario
from app.services.spec_status import get_spec_status

logger = logging.getLogger(__name__)


def _select_relevant_chunks(
    raw: list[dict[str, Any]], min_relevance: float
) -> list[dict[str, Any]]:
    """按相关性阈值过滤检索结果，返回 payload 列表（不含 score）。"""
    return [r["payload"] for r in raw if r["score"] >= min_relevance]


def _build_citation(chunk_payload: dict[str, Any]) -> dict[str, Any]:
    """从 chunk payload 抽取引用元数据（对应 schemas.Citation）。"""
    spec_code = chunk_payload.get("spec_code", "")
    return {
        "spec_name": chunk_payload.get("spec_name", ""),
        "spec_code": spec_code,
        "clause": chunk_payload.get("clause", ""),
        "page": chunk_payload.get("page_start") or chunk_payload.get("page"),
        "is_mandatory": bool(chunk_payload.get("is_mandatory", False)),
        "original_text": (chunk_payload.get("text") or "")[:200],
        "domain": chunk_payload.get("domain", ""),
        # 规范现行状态（默认现行，例外见 services/spec_status）→ status/replaced_by/status_note
        **get_spec_status(spec_code),
    }


def run_rag_sync(
    query: str,
    *,
    domain_filter: str | None = None,
    spec_code_filter: list[str] | None = None,
    top_k: int | None = None,
    history: list[dict[str, str]] | None = None,
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
    # W3 D5：不再硬编码 INPUT_EMPTY/TOO_LONG 走 error；统一交给 scenario 走 fallback
    raw_query = query or ""
    query = raw_query.strip()
    logger.info(
        f"[pipeline] query={query[:60]!r} "
        f"domain={domain_filter} spec={spec_code_filter} turns={len(history) if history else 0}"
    )

    # ── V2-2 多轮指代消解：有历史时把 follow-up 改写成独立 query，再走后续全流程 ──
    # 放在场景识别前：让"那消防呢"这类片段先解析成完整问题，避免被误判为模糊。
    # RED LINE：rewrite 只补指代不增信息，失败回退原 query（generator 内已兜底）。
    if history:
        from app.rag.generator import rewrite_with_context
        hist_text = "\n".join(
            f"{'用户' if t.get('role') == 'user' else '助手'}：{(t.get('content') or '')[:200]}"
            for t in history[-6:]  # 最近 3 轮（6 条消息）
        )
        rewritten = rewrite_with_context(hist_text, query)
        if rewritten and rewritten != query:
            logger.info(f"[pipeline] 多轮重写: {query!r} → {rewritten!r}")
            query = rewritten
            raw_query = rewritten  # 场景识别也基于重写后的独立问题

    # ── 场景识别短路（CLAUDE.md E.4 判定优先级，8 类全覆盖）──
    scenario = detect_scenario(raw_query)
    if scenario != "normal":
        # 按 scenario 选 fallback 文案
        if scenario == "input_empty":
            reply = FALLBACK_INPUT_EMPTY
        elif scenario == "input_too_long":
            reply = FALLBACK_INPUT_TOO_LONG
        elif scenario == "sensitive":
            reply = FALLBACK_SENSITIVE
        elif scenario == "deprecated":
            deprecated_code = _detect_deprecated(query) or ""
            reply = build_fallback_deprecated(deprecated_code)
        elif scenario == "chitchat":
            reply = FALLBACK_CHITCHAT
        elif scenario == "out_of_scope":
            reply = FALLBACK_OUT_OF_SCOPE
        elif scenario == "ambiguous":
            reply = FALLBACK_AMBIGUOUS
        else:
            # 兜底防御：未知 scenario 走通用文案
            reply = FALLBACK_AMBIGUOUS

        for ch in reply:
            yield {"type": "token", "data": ch}
        yield {"type": "fallback", "data": scenario}
        yield {
            "type": "done",
            "data": {"ttft_ms": 0, "total_ms": 0, "tokens_out": len(reply)},
        }
        return

    # 检索
    top_k_rough = int(top_k or RETRIEVAL_CONFIG["top_k_rough"])
    min_relevance = float(RETRIEVAL_CONFIG["min_relevance"])

    # ── W3 D2：query 改写（多 query 攻 BGE-M3 语义偏）──────────────
    multi_query_used = False  # 本次实际是否走多 query 路径
    if MULTI_QUERY_ENABLED:
        try:
            queries = rewrite_query(query)  # [原 q, 变体1..N]，失败时仅含原 q
            multi_query_used = len(queries) > 1
        except Exception as e:
            logger.warning(f"[pipeline] query 改写异常，降级单 query: {e}")
            queries = [query]
    else:
        queries = [query]

    # ── W7 agent：查询分解（复合/发散题拆子问题各自检索再合并覆盖）──────
    # 优先级：分解 > 改写。命中时走独立分解路径（子问题各自重排），跳过下方标准 RRF+重排。
    # 价值在生成侧「答得全」：发散题单次检索只覆盖一个子话题，分解后覆盖全（实证见 devlog）。
    decompose_used = False
    decompose_subs: list[str] = []
    if QUERY_DECOMPOSE_ENABLED:
        try:
            from app.rag.query_decomposer import decompose_query
            _dq = decompose_query(query)
            if len(_dq) > 1:
                decompose_used = True
                decompose_subs = _dq[1:]  # 去掉原 query，留子问题
                logger.info(f"[pipeline] 查询分解: {len(decompose_subs)} 子问题")
        except Exception as e:
            logger.warning(f"[pipeline] 查询分解异常，降级不拆: {e}")

    # W3 D3：决定是否走 hybrid（BM25 + 向量）
    hybrid_used = False
    bm25_search_fn = None
    if HYBRID_ENABLED:
        try:
            from app.rag.bm25_indexer import bm25_search as _bs
            bm25_search_fn = _bs
            hybrid_used = True
        except ImportError as e:
            logger.warning(f"[pipeline] BM25 不可用，降级纯向量：{e}")

    if decompose_used:
        # W7 分解路径：子问题各自 embed→search→**对子问题重排**→合并（覆盖各子话题）
        # 关键：重排对子问题打分，不是对原复合 query（否则期望条仍排低位，实证见 devlog）
        from app.rag.query_decomposer import retrieve_decomposed_chunks
        try:
            kept_payloads = retrieve_decomposed_chunks(
                decompose_subs,
                per_sub_top=2,
                candidate_k=RERANK_CANDIDATE_K,
                domain_filter=domain_filter,
                spec_code_filter=spec_code_filter,
            )
        except Exception as e:
            logger.exception(f"[pipeline] 分解检索失败: {e}")
            yield {"type": "error", "data": f"RETRIEVAL_FAILED: {e}"}
            return
        rerank_used = True
        yield {
            "type": "retrieval",
            "data": {
                "n_candidates": len(kept_payloads),
                "n_kept": len(kept_payloads),
                "n_before_dedup": len(kept_payloads),
                "min_relevance": min_relevance,
                "reranked": True,
                "multi_query": False,
                "n_queries": len(decompose_subs) + 1,
                "hybrid": False,
                "n_paths": len(decompose_subs),
                "rerank_candidate_k": RERANK_CANDIDATE_K,
                "decomposed": True,  # ★ W7 分解透明度
            },
        }
    else:
        # 多 query 顺序 embed/search + 可选 BM25（Qdrant 锁不能并发）
        # W3 D3 评测发现：BM25 跟 4 个变体都走（8 路融合）反而降 -2.6pp
        # 根因：BM25 短语精确但相关性弱于 BGE-M3，等权重融合时挤掉好结果
        # 修复：BM25 只跟原始 query 走 1 路（权重从 50% 降到 20%）
        try:
            results_per_path: list[list[dict[str, Any]]] = []
            for i, q in enumerate(queries):
                qvec = embed_one(q)
                vec_r = search(
                    qvec,
                    top_k=top_k_rough * 2,  # 粗排放大 2× 补偿后续 dedup 损耗
                    domain_filter=domain_filter,
                    spec_code_filter=spec_code_filter,
                )
                results_per_path.append(vec_r)

                # BM25 只对原始 query (i=0) 走一次，避免被 LLM 变体污染 + 权重过大
                if i == 0 and bm25_search_fn is not None:
                    try:
                        bm25_r = bm25_search_fn(
                            q,
                            top_k=HYBRID_BM25_TOP_K * 2,
                            domain_filter=domain_filter,
                            spec_code_filter=spec_code_filter,
                        )
                        results_per_path.append(bm25_r)
                    except Exception as e:
                        logger.warning(f"[pipeline] BM25 search 失败，跳过本路：{e}")
        except Exception as e:
            logger.exception(f"[pipeline] embed/search 失败: {e}")
            yield {"type": "error", "data": f"RETRIEVAL_FAILED: {e}"}
            return

        # RRF 融合（多路时走，单路直接用）
        if len(results_per_path) > 1:
            raw_results = rrf_fuse(
                results_per_path,
                k=MULTI_QUERY_RRF_K,
                top_k=top_k_rough * 2,  # 留余量给 dedup
            )
        else:
            raw_results = results_per_path[0] if results_per_path else []

        # W3 D1：去掉 chunker _dN 后缀产生的 text 重复（同 spec_code + 同文本前缀）
        # W3 D4：dedup 后保留 RERANK_CANDIDATE_K 条给 reranker（默认 30，原 20）
        n_before_dedup = len(raw_results)
        raw_results = dedup_results(raw_results)[:RERANK_CANDIDATE_K]

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
                "n_before_dedup": n_before_dedup,  # ★ W3 D1 dedup 透明度
                "min_relevance": min_relevance,
                "reranked": rerank_used,  # ★ 实际状态，非 flag
                "multi_query": multi_query_used,  # ★ W3 D2 multi-query 透明度
                "n_queries": len(queries),
                "hybrid": hybrid_used,  # ★ W3 D3 hybrid 透明度
                "n_paths": len(results_per_path),  # 实际走了多少路（含 BM25）
                "rerank_candidate_k": RERANK_CANDIDATE_K,  # ★ W3 D4 候选范围透明度
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
    # W5 D4：边流边收 token，用于流末计算 dangling_count（防编造 [N] 监控）
    done_event: dict[str, Any] | None = None
    answer_chunks: list[str] = []
    for evt in stream_chat_sync(messages):
        if evt["type"] == "done":
            done_event = evt
            break
        if evt["type"] == "token":
            answer_chunks.append(evt["data"])
        yield evt

    # W5 D4/D5：扫描完整 answer 的 [N]，N > len(kept_payloads) 视为 dangling（编造引用号）
    # D5 修订：regex 收紧为 \[(\d{1,2})\] —— 仅匹配 1-2 位脚标号，避免误匹配 [2010] 这种年号
    full_answer = "".join(answer_chunks)
    n_chunks = len(kept_payloads)
    import re as _re
    citation_refs = [int(m.group(1)) for m in _re.finditer(r'\[(\d{1,2})\]', full_answer)]
    dangling_refs = [n for n in citation_refs if n < 1 or n > n_chunks]
    dangling_count = len(dangling_refs)
    if dangling_count > 0:
        logger.warning(
            f"[pipeline] dangling_citations: {dangling_count} 个越界引用号 "
            f"(refs={dangling_refs}, n_chunks={n_chunks})"
        )

    # W6 D2：post_filter 剥离"补充说明"节，治 LLM 训练惯性导致的 dim7 编造（启示 52+54）
    # W6 D4：链式叠加 align_modal_verbs，治 dim4 用词错训练惯性（启示 58）
    # W7 D1：尝试链式叠加 align_numbers 治 dim5 — 实测综合 -6.7 / dim5 -19.9pp
    #        按 CLAUDE.md F.2 已回滚集成（函数 + 单测保留，但 pipeline 不调用）。
    #        启示 62：后处理矩阵叠加不是无条件 — 数字类比量词更危险。详见 W7_D1.md。
    from app.rag.post_filter import (
        align_modal_verbs,
        strip_supplementary_sections,
    )
    cleaned_answer, n_stripped_chars = strip_supplementary_sections(full_answer)
    if n_stripped_chars > 0:
        logger.info(
            f"[pipeline] post_filter stripped {n_stripped_chars} 字（"
            f"原 {len(full_answer)} → 净 {len(cleaned_answer)}）"
        )

    # W6 D4：在 strip 后继续 align modal verbs（"宜/应/不应/不宜" 等量词与 chunks 对齐）
    chunks_texts = [(p.get("text") or "") for p in kept_payloads]
    aligned_answer, n_modal_corrections = align_modal_verbs(cleaned_answer, chunks_texts)
    if n_modal_corrections > 0:
        logger.info(
            f"[pipeline] align_modal_verbs corrected {n_modal_corrections} 个量词（"
            f"按 chunks 原词校正）"
        )

    # W7 D1 回滚：n_number_corrections 永远 0（保字段兼容前端 metadata）
    n_number_corrections = 0

    # 是否触发任何后处理（strip / align_modal）
    post_filter_touched = (
        n_stripped_chars > 0
        or n_modal_corrections > 0
    )

    # citations 在 done 之前下发，让前端可以"答案完→显示引用"
    yield {
        "type": "citations",
        "data": [_build_citation(p) for p in kept_payloads],
    }
    # W5 D4 + W6 D2 + W6 D4 + W7 D1：metadata 事件携带 dangling + post_filter 全链路信息
    yield {
        "type": "metadata",
        "data": {
            "dangling_count": dangling_count,
            "n_citations_in_answer": len(citation_refs),
            "n_chunks_available": n_chunks,
            "post_filter_stripped_chars": n_stripped_chars,
            "post_filter_applied": post_filter_touched,
            "modal_verb_corrections": n_modal_corrections,
            "number_corrections": n_number_corrections,  # W7 D1 新增
        },
    }
    # W6 D2 + D4：revised_answer 事件 — 任何后处理生效时下发最终版（前端覆盖 / 评测优先消费）
    if post_filter_touched:
        yield {
            "type": "revised_answer",
            "data": aligned_answer,
        }

    # V2-1 智能追问：据问答生成 2-3 个相关追问，在 done 前下发（失败静默返回 []）
    final_answer = aligned_answer if post_filter_touched else full_answer
    from app.rag.generator import generate_followups
    follow_ups = generate_followups(query, final_answer)
    if follow_ups:
        yield {"type": "follow_ups", "data": follow_ups}

    if done_event:
        yield done_event
    else:
        yield {"type": "done", "data": {"ttft_ms": 0, "total_ms": 0, "tokens_out": 0}}
