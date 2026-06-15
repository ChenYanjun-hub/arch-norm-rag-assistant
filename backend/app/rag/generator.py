"""LLM 生成：DeepSeek V3（CLAUDE.md 附录锁定，不可换 GPT-4/Claude）。

使用 openai SDK 兼容协议调用 DeepSeek（base_url 指向 api.deepseek.com）。

性能要求（CLAUDE.md E.5）：
  - TTFT P95 ≤ 3s（首字 ≤ 3 秒）
  - 总响应时长 P95 ≤ 15s
  - 必须流式输出
  - LLM 调用 30s 超时
  - 失败重试 1 次（CLAUDE.md E.5）

接口：
  - stream_chat(messages) → AsyncIterator[str]，逐 token 输出
  - stream_chat_sync(messages) → Iterator[str]，同步版（CLI 用）
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

from openai import APIError, APITimeoutError, OpenAI, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import LLM_MAX_RETRIES, LLM_TIMEOUT_SECONDS, settings

logger = logging.getLogger(__name__)


# 模块级 client 单例（避免每次请求重建 httpx pool）
_client: OpenAI | None = None


def get_client() -> OpenAI:
    """返回 DeepSeek 客户端单例。"""
    global _client
    if _client is not None:
        return _client

    if not settings.deepseek_api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY 未配置。请在 backend/.env 设置真实 key。"
        )

    _client = OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        timeout=LLM_TIMEOUT_SECONDS,
    )
    logger.info(
        f"[generator] DeepSeek client 已初始化 (model={settings.deepseek_model}, "
        f"timeout={LLM_TIMEOUT_SECONDS}s)"
    )
    return _client


# 可重试异常：超时、网络抖动、限流；不重试 4xx 业务错误
_retryable = (APITimeoutError, RateLimitError)


@retry(
    stop=stop_after_attempt(LLM_MAX_RETRIES + 1),  # 总共 +1（首次 + N 次重试）
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(_retryable),
    reraise=True,
)
def _create_stream(messages: list[dict[str, str]], **kwargs: Any) -> Any:
    """内部：创建流式 chat completion，含重试。"""
    client = get_client()
    return client.chat.completions.create(
        model=settings.deepseek_model,
        messages=messages,
        stream=True,
        **kwargs,
    )


@retry(
    stop=stop_after_attempt(LLM_MAX_RETRIES + 1),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(_retryable),
    reraise=True,
)
def _complete_once(messages: list[dict[str, str]], **kwargs: Any) -> str:
    """内部：非流式单次 completion（追问/重写等短任务用），含重试。"""
    client = get_client()
    resp = client.chat.completions.create(
        model=settings.deepseek_model, messages=messages, stream=False, **kwargs
    )
    return resp.choices[0].message.content or ""


def generate_followups(query: str, answer: str) -> list[str]:
    """V2-1：据问答生成 2-3 个相关追问。任何失败返回 []（绝不影响主流程）。"""
    import json as _json

    from app.core.prompts import build_followup_messages

    try:
        out = _complete_once(
            build_followup_messages(query, answer), temperature=0.5, max_tokens=200
        )
        out = out.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        arr = _json.loads(out)
        if isinstance(arr, list):
            qs = [str(q).strip() for q in arr if str(q).strip()]
            return qs[:3]
    except Exception as e:  # 追问是增强功能，失败静默降级
        logger.warning(f"[generator] 追问生成失败（忽略）：{e}")
    return []


def rewrite_with_context(history: str, query: str) -> str:
    """V2-2：多轮指代消解，把 follow-up 改写成独立 query。失败/异常返回原 query。"""
    from app.core.prompts import build_context_rewrite_messages

    try:
        out = _complete_once(
            build_context_rewrite_messages(history, query),
            temperature=0.0, max_tokens=120,
        )
        out = out.strip().strip('"“” 　')
        # 防御：重写结果异常长/空时回退原 query（RED LINE：不引入幻觉问题）
        if out and len(out) <= 200:
            return out
    except Exception as e:
        logger.warning(f"[generator] 上下文重写失败（用原 query）：{e}")
    return query


def stream_chat_sync(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,  # 规范查询要稳定，不要发散
    max_tokens: int = 2048,
) -> Iterator[dict[str, Any]]:
    """同步流式生成。每次 yield 一个 dict：

        {"type": "token", "data": "..."}       # 逐 token 文本
        {"type": "done",  "data": {            # 流结束时的总结
            "ttft_ms": ...,
            "total_ms": ...,
            "tokens_out": ...,
        }}
        {"type": "error", "data": "..."}       # 异常

    Args:
        messages: openai 格式 [{"role": "system"/"user"/"assistant", "content": "..."}]
        temperature: 默认 0.1（规范查询要确定性高）
        max_tokens: 单次回复最大 tokens

    设计取舍：返回 dict 而非纯 str token，便于后续 pipeline 同时处理 token 与元数据。
    """
    t0 = time.time()
    ttft_ms: float | None = None
    tokens_out = 0

    try:
        stream = _create_stream(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                if ttft_ms is None:
                    ttft_ms = (time.time() - t0) * 1000
                    logger.info(f"[generator] ttft={ttft_ms:.0f}ms")
                tokens_out += 1
                yield {"type": "token", "data": content}

    except APIError as e:
        logger.error(f"[generator] DeepSeek API 错误: {e}")
        yield {"type": "error", "data": f"LLM_API_ERROR: {e}"}
        return
    except Exception as e:  # pragma: no cover —— 保护性兜底
        logger.exception(f"[generator] 未预期异常: {e}")
        yield {"type": "error", "data": f"LLM_UNEXPECTED: {e}"}
        return

    total_ms = (time.time() - t0) * 1000
    logger.info(
        f"[generator] stream done: ttft={ttft_ms or 0:.0f}ms, "
        f"total={total_ms:.0f}ms, tokens={tokens_out}"
    )
    yield {
        "type": "done",
        "data": {
            "ttft_ms": int(ttft_ms or 0),
            "total_ms": int(total_ms),
            "tokens_out": tokens_out,
        },
    }


async def stream_chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,
    max_tokens: int = 2048,
) -> AsyncIterator[dict[str, Any]]:
    """async 流式封装（FastAPI SSE 端点会用到）。

    暂用同步版包一层；W2 接 FastAPI 时若性能不够可换 AsyncOpenAI。
    """
    import asyncio

    def _gen() -> Iterator[dict[str, Any]]:
        yield from stream_chat_sync(
            messages, temperature=temperature, max_tokens=max_tokens
        )

    # 把同步迭代器跑在 thread pool 中以不阻塞事件循环
    loop = asyncio.get_event_loop()
    it = await loop.run_in_executor(None, _gen)
    for item in it:
        yield item
