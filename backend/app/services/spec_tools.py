"""规范查询工具集（agentic RAG · tool-use · 给 tool_agent 调用）。

背景（2026-W7 agent 深化 · ③）：
    有些查询向量检索天生弱——精确条文号定位（"GB 50180-2018 表5.0.3 是什么"）、
    目录导航（"你收录了哪些消防规范"）、现行状态（"GB 50016-2014 还有效吗"）。
    这些不是"语义相似"问题，是"精确查表 / 元信息"问题。给 agent 工具去查，比向量联想准。

本模块提供 3 个确定性工具（不依赖 LLM，可单测）+ function-calling schema。
数据源：chunks JSON（Qdrant-free，模块级缓存）+ spec_status 服务。
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
from typing import Any

from app.core.config import settings
from app.services.spec_status import get_spec_status

logger = logging.getLogger(__name__)

# 模块级缓存：{spec_code_norm: {"spec_code","spec_name","domain"}} + {(spec_code_norm, clause): text}
_SPEC_INDEX: dict[str, dict[str, str]] | None = None
_CLAUSE_INDEX: dict[tuple[str, str], str] | None = None


def _norm(code: str) -> str:
    return (code or "").replace(" ", "").replace("　", "").upper()


def _load_indexes() -> None:
    """从 chunks JSON 建规范索引 + 条文索引（首次调用时，之后缓存）。"""
    global _SPEC_INDEX, _CLAUSE_INDEX
    if _SPEC_INDEX is not None:
        return
    spec_index: dict[str, dict[str, str]] = {}
    clause_index: dict[tuple[str, str], str] = {}
    pattern = os.path.join(settings.chunks_dir, "*.json")
    for fp in glob.glob(pattern):
        try:
            data = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        items = data if isinstance(data, list) else data.get("chunks", [])
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            sc = it.get("spec_code")
            if not sc:
                continue
            key = _norm(sc)
            if key not in spec_index:
                spec_index[key] = {
                    "spec_code": sc,
                    "spec_name": it.get("spec_name", ""),
                    "domain": it.get("domain", ""),
                }
            clause = str(it.get("clause", "")).strip()
            if clause:
                clause_index[(key, clause)] = it.get("text", "")
    _SPEC_INDEX = spec_index
    _CLAUSE_INDEX = clause_index
    logger.info(
        f"[spec_tools] 索引就绪：{len(spec_index)} 部规范 / {len(clause_index)} 条条文"
    )


def list_specs(domain: str | None = None) -> dict[str, Any]:
    """列出收录的规范（可按域过滤）。用于目录导航类查询。

    Args:
        domain: 规范域（规划/建筑/景观/消防/市政/结构），None=全部。
    Returns:
        {"domain": ..., "count": int, "specs": [{"spec_code","spec_name","domain"}, ...]}
    """
    _load_indexes()
    assert _SPEC_INDEX is not None
    specs = list(_SPEC_INDEX.values())
    if domain:
        d = domain.strip()
        specs = [s for s in specs if s.get("domain") == d]
    specs = sorted(specs, key=lambda s: s["spec_code"])
    return {"domain": domain or "全部", "count": len(specs), "specs": specs}


def lookup_clause(spec_code: str, clause: str) -> dict[str, Any]:
    """按规范号 + 条文号精确定位条文原文。用于精确引用类查询。

    Args:
        spec_code: 规范号，如 "GB 50180-2018"。
        clause: 条文号 / 表号，如 "5.0.3" / "表5.0.3"。
    Returns:
        命中 → {"found": True, "spec_code","clause","text"}
        未命中 → {"found": False, "hint": 该规范下相近条文号}
    """
    _load_indexes()
    assert _CLAUSE_INDEX is not None
    key = _norm(spec_code)
    c = (clause or "").strip()
    # 精确 + 双向子串（容忍复合条 "5.0.2+5.0.3" 与 "表5.0.3" 前缀）
    for (sk, cl), text in _CLAUSE_INDEX.items():
        if sk == key and (cl == c or c in cl or cl in c):
            return {"found": True, "spec_code": spec_code, "clause": cl, "text": text}
    # 未命中：给该规范下的相近条文号做提示
    prefix = c.split(".")[0] if "." in c else c[:2]
    near = sorted(
        {cl for (sk, cl) in _CLAUSE_INDEX if sk == key and cl.startswith(prefix)}
    )[:8]
    return {"found": False, "spec_code": spec_code, "clause": c, "hint": near}


def check_spec_status(spec_code: str) -> dict[str, Any]:
    """查规范现行/作废状态。用于时效性类查询。"""
    _load_indexes()
    assert _SPEC_INDEX is not None
    key = _norm(spec_code)
    known = _SPEC_INDEX.get(key)
    status = get_spec_status(spec_code)
    return {
        "spec_code": spec_code,
        "in_corpus": known is not None,
        "spec_name": known.get("spec_name") if known else None,
        **status,  # status / replaced_by / status_note
    }


# ── function-calling schema（给 DeepSeek tools 参数）──────────────
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_specs",
            "description": "列出规范库收录的规范，可按域过滤。用于'你收录了哪些X规范'这类目录导航查询。",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "规范域：规划/建筑/景观/消防/市政/结构；不传=全部",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_clause",
            "description": "按规范号+条文号精确定位条文原文。用于'GB 50180-2018 第5.0.3条是什么'这类精确引用查询。",
            "parameters": {
                "type": "object",
                "properties": {
                    "spec_code": {"type": "string", "description": "规范号，如 GB 50180-2018"},
                    "clause": {"type": "string", "description": "条文号/表号，如 5.0.3 或 表5.0.3"},
                },
                "required": ["spec_code", "clause"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_spec_status",
            "description": "查规范的现行/作废状态。用于'GB 50016-2014 还有效吗'这类时效性查询。",
            "parameters": {
                "type": "object",
                "properties": {
                    "spec_code": {"type": "string", "description": "规范号，如 GB 50016-2014"},
                },
                "required": ["spec_code"],
            },
        },
    },
]

# 名字 → 可调用函数（tool_agent 执行 tool_calls 时用）
TOOL_FUNCTIONS = {
    "list_specs": list_specs,
    "lookup_clause": lookup_clause,
    "check_spec_status": check_spec_status,
}
