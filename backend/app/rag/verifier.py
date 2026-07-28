"""引用核验（agentic RAG · verifier/reflection · 守红线 1 不编造）。

背景（2026-W7 agent 深化 · ②）：
    现有规则式治理（post_filter）覆盖：剥"补充说明"节、校量词（align_modal_verbs）、
    查 [N] 角标越界（dangling）。但**规范号 / 条文号 / 数字是否真在 chunks 里有据**，
    规则不做全局核验——LLM 若引一个"看着对但 chunks 没有"的规范号/数字，规则抓不到。

方案：生成 + 后处理后，LLM verifier 逐项核对答案里的四类硬事实（规范号/条文号/数字/强条用语）
    是否被 chunks 支持，列出无据项（编造）。第一版**只检测不改写**（自动改写答案有风险，
    见 align_numbers 回滚 · 启示 62），把 issues 交给 pipeline 走 metadata + 可见提示。

设计取舍（同 decomposer / rewriter）：
    - non-streaming，短超时；失败/超时降级到"未核验"（grounded=True, verified=False），绝不阻塞主流程。
    - 保守：prompt 要求"宁可漏报不误报"，避免把有据的误判为编造。

接口：
    verify_grounding(answer, chunks) → {"grounded": bool, "issues": list[str], "verified": bool}
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from openai import APIError, APITimeoutError

from app.core.config import ANSWER_VERIFY_TIMEOUT_SECONDS, settings
from app.core.prompts import build_verify_messages
from app.rag.generator import get_client

logger = logging.getLogger(__name__)

_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _build_chunks_block(chunks: list[dict[str, Any]]) -> str:
    """把 kept_payloads 拼成核验用的编号片段块（规范号 + 条文号 + 原文）。"""
    lines: list[str] = []
    for i, p in enumerate(chunks, start=1):
        spec_code = p.get("spec_code", "")
        spec_name = p.get("spec_name", "")
        clause = p.get("clause", "")
        text = (p.get("text") or "").replace("\n", " ")[:300]
        lines.append(f"[{i}] 《{spec_name}》{spec_code} {clause}\n{text}")
    return "\n\n".join(lines)


def _parse_verdict(raw: str) -> dict[str, Any] | None:
    """解析 verifier 的 JSON verdict；失败返回 None。"""
    if not raw:
        return None
    m = _JSON_OBJ_RE.search(raw)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    grounded = bool(data.get("grounded", True))
    issues_raw = data.get("issues", [])
    issues = [str(x).strip() for x in issues_raw if isinstance(x, (str, int, float)) and str(x).strip()] if isinstance(issues_raw, list) else []
    # 一致性：有 issues 则 grounded 必为 False
    if issues:
        grounded = False
    return {"grounded": grounded, "issues": issues}


def verify_grounding(
    answer: str,
    chunks: list[dict[str, Any]],
    *,
    timeout: float | None = None,
) -> dict[str, Any]:
    """核验答案里的规范号/条文号/数字/强条用语是否被 chunks 支持。

    Returns:
        {
          "grounded": bool,      # 是否全部有据（未核验/失败时为 True，不误伤）
          "issues": list[str],   # 无据（编造）项摘录
          "verified": bool,      # verifier 是否真的成功跑了（失败/超时为 False）
        }

    设计契约：永不抛异常。任何错误降级到 {"grounded": True, "issues": [], "verified": False}。
    """
    fallback = {"grounded": True, "issues": [], "verified": False}
    a = (answer or "").strip()
    if not a or not chunks:
        return fallback
    if timeout is None:
        timeout = ANSWER_VERIFY_TIMEOUT_SECONDS

    t0 = time.time()
    messages = build_verify_messages(a, _build_chunks_block(chunks))
    try:
        client = get_client()
        resp = client.chat.completions.create(
            model=settings.deepseek_model,
            messages=messages,
            temperature=0.0,  # 核验要稳定确定
            max_tokens=400,
            timeout=timeout,
            stream=False,
        )
    except APITimeoutError:
        logger.warning(f"[verifier] 超时（{timeout}s），降级未核验")
        return fallback
    except APIError as e:
        logger.warning(f"[verifier] LLM API 错误，降级未核验: {e}")
        return fallback
    except Exception as e:  # pragma: no cover
        logger.exception(f"[verifier] 未预期异常，降级未核验: {e}")
        return fallback

    elapsed_ms = (time.time() - t0) * 1000
    try:
        content = resp.choices[0].message.content or ""
    except (AttributeError, IndexError):
        return fallback

    verdict = _parse_verdict(content)
    if verdict is None:
        logger.warning(f"[verifier] verdict 解析失败（{elapsed_ms:.0f}ms），降级未核验")
        return fallback

    verdict["verified"] = True
    if verdict["issues"]:
        logger.warning(
            f"[verifier] 发现 {len(verdict['issues'])} 处疑似无据引用（{elapsed_ms:.0f}ms）: "
            f"{verdict['issues']}"
        )
    else:
        logger.info(f"[verifier] 核验通过，全部有据（{elapsed_ms:.0f}ms）")
    return verdict
