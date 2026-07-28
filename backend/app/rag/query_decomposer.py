"""查询分解（agentic RAG · 攻复合/发散问题的召回覆盖）。

背景（2026-W7 A 层后续 · agent 深化）：
    评测显示综合域 strict 仅 33%（全域最差）。诊断发现复合题（"A 和 B 的要求"）单次检索
    的 embedding 会被一个子话题主导、漏掉另一个（Q098 期望条排第 8、Q143 完全召不回）。
    手动拆解验证：子问题各自检索后并集，期望条被捞回（Q098 8→1、Q143 None→候选内）。

方案：LLM 判断查询是否复合/发散，是则拆成 2~4 个自包含子问题，各自检索后 RRF 融合
    （融合 + 重排复用 pipeline 现成机制）。单一问题不拆，零额外检索开销。

与 query 改写（query_rewriter）的区别：
    - 改写：同一问题换 3 种说法 → 提**召回**（攻 embedding 语义偏）。
    - 分解：多问题各自检索 → 提**覆盖**（攻复合题漏召回子话题）。

设计取舍（同 query_rewriter）：
    - non-streaming，短超时（保 TTFT SLA），失败/超时降级到 [原 query]（绝不阻塞主流程）。
    - 契约：返回 [原 query]（单一/失败）或 [原 query, 子1, 子2...]（复合），
      结构与 rewrite_query 一致，可复用多路检索机制。

接口：
    decompose_query(query) → list[str]
"""

from __future__ import annotations

import json
import logging
import re
import time

from openai import APIError, APITimeoutError

from app.core.config import (
    QUERY_DECOMPOSE_MAX_SUBQ,
    QUERY_DECOMPOSE_TIMEOUT_SECONDS,
    settings,
)
from app.core.prompts import build_query_decompose_messages
from app.rag.generator import get_client

logger = logging.getLogger(__name__)

# 抓第一个 [...] JSON 数组（容忍 ```json 围栏 / 前后解释）
_JSON_ARRAY_RE = re.compile(r"\[(?:[^\[\]]|\[[^\[\]]*\])*\]", re.DOTALL)
_STRIP_QUOTE_CHARS = "".join(['"', "'", "“", "”", "‘", "’"])


def _parse_subqueries(raw_content: str) -> list[str]:
    """从 LLM 输出解析 JSON 数组，返回子问题列表；失败返回 []。"""
    if not raw_content:
        return []
    m = _JSON_ARRAY_RE.search(raw_content)
    if not m:
        logger.warning(f"[query_decomposer] 未找到 JSON 数组: {raw_content[:200]!r}")
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        logger.warning(f"[query_decomposer] JSON 解析失败: {e} / {m.group(0)[:200]!r}")
        return []
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for item in data:
        if not isinstance(item, str):
            continue
        s = item.strip().strip(_STRIP_QUOTE_CHARS).strip()
        if s:
            out.append(s)
    return out


def decompose_query(query: str, *, timeout: float | None = None) -> list[str]:
    """把复合/发散查询分解为多个自包含子问题。

    Returns:
        list[str]：
        - 单一问题 / 失败 / 超时 → [原 query]（不拆，零额外检索）
        - 复合问题 → [原 query, 子1, 子2, ...]（去重，子问题数 ≤ QUERY_DECOMPOSE_MAX_SUBQ）

    设计契约：本函数永不抛异常，任何错误都降级到 [原 query]。
    """
    q = (query or "").strip()
    if not q:
        return []
    if timeout is None:
        timeout = QUERY_DECOMPOSE_TIMEOUT_SECONDS

    t0 = time.time()
    messages = build_query_decompose_messages(q)
    try:
        client = get_client()
        resp = client.chat.completions.create(
            model=settings.deepseek_model,
            messages=messages,
            temperature=0.0,  # 分解要稳定确定，不需要多样性
            max_tokens=200,
            timeout=timeout,
            stream=False,
        )
    except APITimeoutError:
        logger.warning(f"[query_decomposer] LLM 超时（{timeout}s），不拆: {q[:50]!r}")
        return [q]
    except APIError as e:
        logger.warning(f"[query_decomposer] LLM API 错误，不拆: {e}")
        return [q]
    except Exception as e:  # pragma: no cover —— 兜底
        logger.exception(f"[query_decomposer] 未预期异常，不拆: {e}")
        return [q]

    elapsed_ms = (time.time() - t0) * 1000
    try:
        content = resp.choices[0].message.content or ""
    except (AttributeError, IndexError):
        logger.warning("[query_decomposer] 响应结构异常，不拆")
        return [q]

    subs = _parse_subqueries(content)
    # 单元素或空 → LLM 判定为单一问题，不拆
    if len(subs) <= 1:
        logger.info(f"[query_decomposer] 单一问题不拆（{elapsed_ms:.0f}ms）: {q[:40]!r}")
        return [q]

    # 复合：原 query + 子问题（去重，原 query 打头做锚点）
    seen = {q}
    result = [q]
    for s in subs:
        if s not in seen:
            seen.add(s)
            result.append(s)
        if len(result) >= QUERY_DECOMPOSE_MAX_SUBQ + 1:  # 原 + N 子
            break
    logger.info(
        f"[query_decomposer] 分解完成（{elapsed_ms:.0f}ms）: "
        f"1 原 + {len(result) - 1} 子问题 | {q[:40]!r}"
    )
    return result


def retrieve_decomposed_chunks(
    sub_queries: list[str],
    *,
    per_sub_top: int = 2,
    candidate_k: int = 20,
    domain_filter: str | None = None,
    spec_code_filter: list[str] | None = None,
) -> list[dict]:
    """分解检索：每个子问题各自 embed→search→**对该子问题重排**→取 top_n，合并去重。

    关键（对比 multi_query 的错误接法）：重排是对**子问题**打分，不是对原复合 query 打分。
    诊断实证：拿复合 query 重排 → 期望条仍排低位（Q098 9）；拿子问题各自重排 → rank 1。
    合并后覆盖各子话题（发散/复合题"答得全"的关键），喂给生成。

    Args:
        sub_queries: 分解出的子问题列表（不含原 query）。
        per_sub_top: 每个子问题保留几条（默认 2）。
        candidate_k: 每个子问题的粗排候选数。
    Returns:
        去重后的 chunk payload 列表（顺序：按子问题轮转，保覆盖）。
    """
    from app.core.config import RERANK_MIN_SCORE
    from app.rag.embedder import embed_one
    from app.rag.reranker import rerank
    from app.rag.retriever import dedup_results, search

    seen: set = set()
    merged: list[dict] = []
    for sq in sub_queries:
        try:
            qvec = embed_one(sq)
            vec = dedup_results(
                search(
                    qvec,
                    top_k=candidate_k,
                    domain_filter=domain_filter,
                    spec_code_filter=spec_code_filter,
                )
            )
            reranked = rerank(sq, vec, top_k=per_sub_top, min_score=RERANK_MIN_SCORE)
        except Exception as e:
            logger.warning(f"[query_decomposer] 子问题检索失败，跳过：{sq[:30]!r} / {e}")
            continue
        for r in reranked:
            p = r["payload"]
            key = (p.get("spec_code"), str(p.get("clause")), (p.get("text") or "")[:40])
            if key not in seen:
                seen.add(key)
                merged.append(p)
    return merged
