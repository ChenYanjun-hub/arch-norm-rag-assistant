"""工具调用 Agent（agentic RAG · ReAct / function-calling · W7 agent 深化 ③）。

背景：精确条文定位 / 目录导航 / 现行状态这类"查表/元信息"查询，向量检索天生弱。
    给 agent 工具（spec_tools 的 3 个确定性函数），用 DeepSeek function-calling
    让它自己判断调哪个工具、拿结果后作答——比向量语义联想准。

流程（单轮 ReAct）：
    query → LLM(带 tools) → 若返回 tool_calls：执行工具 → 把结果喂回 → LLM 出最终答案。
    若 LLM 不调工具（非查表类问题）→ 返回 used_tool=False（调用方回退常规 RAG）。

设计契约：永不抛异常，任何错误降级到 {"used_tool": False, "answer": None, "error": ...}。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from openai import APIError, APITimeoutError

from app.core.config import TOOL_AGENT_TIMEOUT_SECONDS, settings
from app.core.prompts import SYSTEM_PROMPT_TOOL_AGENT
from app.rag.generator import get_client
from app.services.spec_tools import TOOL_FUNCTIONS, TOOL_SCHEMAS

logger = logging.getLogger(__name__)


def _exec_tool_call(tc: Any) -> dict[str, Any]:
    """执行单个 tool_call，返回 {tool_call_id, name, args, result}。"""
    name = tc.function.name
    try:
        args = json.loads(tc.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        result: Any = {"error": f"未知工具 {name}"}
    else:
        try:
            result = fn(**args)
        except Exception as e:  # 工具执行失败也不抛
            logger.warning(f"[tool_agent] 工具 {name} 执行失败: {e}")
            result = {"error": str(e)}
    return {"tool_call_id": tc.id, "name": name, "args": args, "result": result}


def run_tool_agent(query: str, *, timeout: float | None = None) -> dict[str, Any]:
    """用 function-calling 让 agent 判断并调用规范查询工具。

    Returns:
        {
          "used_tool": bool,          # 是否真的调了工具
          "tool_calls": list[dict],   # [{name, args, result}, ...]（可观测/透明度）
          "answer": str | None,       # 最终答案（未调工具或失败为 None）
        }
    """
    q = (query or "").strip()
    fallback = {"used_tool": False, "tool_calls": [], "answer": None}
    if not q:
        return fallback
    if timeout is None:
        timeout = TOOL_AGENT_TIMEOUT_SECONDS

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT_TOOL_AGENT},
        {"role": "user", "content": q},
    ]
    executed: list[dict[str, Any]] = []
    t0 = time.time()
    client = get_client()

    # 多轮 ReAct 循环：每轮都带 tools（避免二次调用无 tools 导致模型把 tool_call 当文本吐出）。
    # 循环直到模型不再调工具（给出最终答案）或达上限。
    MAX_ITERS = 3
    for _ in range(MAX_ITERS):
        try:
            resp = client.chat.completions.create(
                model=settings.deepseek_model,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.0,
                timeout=timeout,
                stream=False,
            )
        except (APITimeoutError, APIError) as e:
            logger.warning(f"[tool_agent] LLM 调用失败，回退常规 RAG: {e}")
            return fallback if not executed else {"used_tool": True, "tool_calls": executed, "answer": None}
        except Exception as e:  # pragma: no cover
            logger.exception(f"[tool_agent] 未预期异常，回退常规 RAG: {e}")
            return fallback

        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)

        if not tool_calls:
            # 不再调工具：给出最终答案。executed 为空 = 首轮就没调 → 非查表类，回退常规 RAG。
            if not executed:
                logger.info(f"[tool_agent] 未调工具（非查表类），回退常规 RAG: {q[:40]!r}")
                return fallback
            elapsed_ms = (time.time() - t0) * 1000
            logger.info(
                f"[tool_agent] 调了 {len(executed)} 个工具（{elapsed_ms:.0f}ms）: "
                f"{[e['name'] for e in executed]}"
            )
            return {"used_tool": True, "tool_calls": executed, "answer": msg.content or ""}

        # 有 tool_calls：登记 assistant 消息 + 执行工具 + 喂回结果，进入下一轮
        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ],
            }
        )
        for tc in tool_calls:
            r = _exec_tool_call(tc)
            executed.append({"name": r["name"], "args": r["args"], "result": r["result"]})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": r["tool_call_id"],
                    "content": json.dumps(r["result"], ensure_ascii=False),
                }
            )

    # 达到迭代上限仍未收敛 → 返回已执行工具但无最终答案（调用方兜底）
    logger.warning(f"[tool_agent] 达迭代上限 {MAX_ITERS}，未收敛: {q[:40]!r}")
    return {"used_tool": True, "tool_calls": executed, "answer": None}
