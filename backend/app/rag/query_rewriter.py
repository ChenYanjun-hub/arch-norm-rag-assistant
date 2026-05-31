"""Query 改写（W3 D2 加 · 攻 BGE-M3 语义偏）。

背景：W3 D1 评测诊断发现 BGE-M3 在专业规范文本上有显著语义偏差。
例：Q010 "办公建筑的耐火等级最低要求？"（expected GB 55037-2022 5.1.3）
    → top-20 全是 5.2/5.3 章节，5.1 章节直到 rank 11 才出现
    → 因为 BGE-M3 把"耐火等级"匹配到"5.3 防火等级条款"，错过"5.1 耐火分类"

方案：用 DeepSeek 把单 query 扩展为 3 个语义变体，从 3 个角度召回，
再 RRF 融合（pipeline.py 负责融合，本模块只负责改写）。

设计取舍：
- non-streaming 调用（只要拿到完整 JSON 数组即可，无需流式）
- 短超时 3s（保 TTFT 不爆 3s SLA；超时直接降级单 query）
- temperature=0.4（鼓励一定多样性，但不能太发散偏题）
- 失败/解析错误都降级到 [原 query]（绝不让 query 改写阻塞主流程）

接口：
    rewrite_query(query) → list[str]
    返回 [原 query, 变体1, 变体2, 变体3]，长度 1~(1+MAX_VARIANTS)
"""

from __future__ import annotations

import json
import logging
import re
import time

from openai import APIError, APITimeoutError

from app.core.config import (
    MULTI_QUERY_MAX_VARIANTS,
    MULTI_QUERY_TIMEOUT_SECONDS,
    settings,
)
from app.core.prompts import build_query_rewrite_messages
from app.rag.generator import get_client

logger = logging.getLogger(__name__)


# LLM 偶尔会用 ```json 围栏包 JSON，或在 JSON 前后加解释；
# 这个正则抓第一个 [...] 数组结构。
_JSON_ARRAY_RE = re.compile(r"\[(?:[^\[\]]|\[[^\[\]]*\])*\]", re.DOTALL)

# 变体首尾如果被 LLM 用引号包起来要去掉；含 ASCII 和中文弯引号
_STRIP_QUOTE_CHARS = ''.join([
    '"', "'",            # ASCII 双/单引号
    '“', '”',  # 中文 " "
    '‘', '’',  # 中文 ' '
])


def _parse_variants(raw_content: str) -> list[str]:
    """从 LLM 输出里解析 JSON 数组，返回变体列表。

    容忍：
      - markdown 围栏 ```json ... ```
      - JSON 前后有解释文字
      - 多余引号 / 中英文标点混用

    解析失败返回空列表（调用方降级到 [原 query]）。
    """
    if not raw_content:
        return []

    # 1. 优先抓正则匹配的 JSON 数组
    m = _JSON_ARRAY_RE.search(raw_content)
    if not m:
        logger.warning(f"[query_rewriter] 未在输出中找到 JSON 数组: {raw_content[:200]!r}")
        return []

    candidate = m.group(0)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as e:
        logger.warning(
            f"[query_rewriter] JSON 解析失败: {e} / candidate={candidate[:200]!r}"
        )
        return []

    if not isinstance(data, list):
        return []

    # 只保留非空字符串，去掉前后空白和引号；裁剪到 MAX_VARIANTS 个
    out: list[str] = []
    for item in data:
        if not isinstance(item, str):
            continue
        s = item.strip().strip(_STRIP_QUOTE_CHARS).strip()
        if s:
            out.append(s)
    return out[:MULTI_QUERY_MAX_VARIANTS]


def rewrite_query(query: str, *, timeout: float | None = None) -> list[str]:
    """把单 query 扩展为多个语义变体。

    Args:
        query: 用户原始 query
        timeout: 单次 LLM 调用超时（秒）；默认 MULTI_QUERY_TIMEOUT_SECONDS

    Returns:
        list[str]，长度 1~(1+MULTI_QUERY_MAX_VARIANTS)
        - 第 0 项必为原 query（保底召回）
        - 后续为 LLM 生成的变体（按返回顺序）
        - 失败/超时时仅含原 query

    设计契约：本函数永不抛异常。任何错误都降级到 [原 query]。
    """
    q = (query or "").strip()
    if not q:
        return []

    if timeout is None:
        timeout = MULTI_QUERY_TIMEOUT_SECONDS

    t0 = time.time()
    messages = build_query_rewrite_messages(q)

    try:
        client = get_client()
        # non-streaming 调用，整段返回
        resp = client.chat.completions.create(
            model=settings.deepseek_model,
            messages=messages,
            temperature=0.4,  # 比主问答 0.1 高，鼓励多样性
            max_tokens=300,   # 3 个 30 字内变体 + JSON 结构开销
            timeout=timeout,
            stream=False,
        )
    except APITimeoutError:
        logger.warning(
            f"[query_rewriter] LLM 超时（{timeout}s），降级单 query: {q[:50]!r}"
        )
        return [q]
    except APIError as e:
        logger.warning(f"[query_rewriter] LLM API 错误，降级单 query: {e}")
        return [q]
    except Exception as e:  # pragma: no cover —— 兜底
        logger.exception(f"[query_rewriter] 未预期异常，降级单 query: {e}")
        return [q]

    elapsed_ms = (time.time() - t0) * 1000

    try:
        content = resp.choices[0].message.content or ""
    except (AttributeError, IndexError):
        logger.warning(f"[query_rewriter] 响应结构异常，降级单 query")
        return [q]

    variants = _parse_variants(content)
    if not variants:
        logger.warning(
            f"[query_rewriter] 解析变体为空（elapsed={elapsed_ms:.0f}ms），"
            f"降级单 query: q={q[:50]!r} raw={content[:200]!r}"
        )
        return [q]

    # 去重（变体可能跟原 query 重叠）
    seen = {q}
    unique_variants: list[str] = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            unique_variants.append(v)

    result = [q] + unique_variants
    logger.info(
        f"[query_rewriter] 改写完成 ({elapsed_ms:.0f}ms)：1 原 + {len(unique_variants)} 变体"
    )
    for i, v in enumerate(result):
        logger.debug(f"  q[{i}]={v!r}")
    return result
