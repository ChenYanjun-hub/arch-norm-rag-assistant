"""Pydantic 数据模型：所有 API 请求/响应的统一定义（CLAUDE.md D.2）。

骨架阶段先定义核心 schema，后续 W2-W3 随 API 实现完善字段约束。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────
# 问答接口
# ──────────────────────────────────────────────
class ChatRequest(BaseModel):
    """POST /api/chat 请求体。"""

    query: str = Field(..., min_length=1, max_length=500, description="用户问题")
    session_id: str | None = Field(None, description="会话 ID（V2 多轮用）")
    domain: str | None = Field(
        None, description="可选 domain 限定（规划/建筑/景观/消防）"
    )
    spec_code: str | None = Field(None, description="可选 spec_code 限定")


class Citation(BaseModel):
    """引用结构化数据。任何引用元数据错误都是 P0 bug（CLAUDE.md 红线 2）。"""

    spec_name: str = Field(..., description="规范全称，如《城市居住区规划设计标准》")
    spec_code: str = Field(..., description="标准号含年份，如 GB 50180-2018")
    clause: str = Field(..., description="条文号，如 表 5.0.3 或 第 4.2.3 条")
    page: int | None = Field(None, description="PDF 页码（用于跳转）")
    is_mandatory: bool = Field(False, description="是否强制性条文")
    original_text: str = Field(..., max_length=200, description="原文摘引，建议 ≤ 50 字")


ChatChunkType = Literal["token", "citations", "follow_ups", "done", "error"]


class ChatChunk(BaseModel):
    """SSE 流式输出的单条事件。"""

    type: ChatChunkType
    data: str | list[Citation] | list[str] | dict | None = None


# ──────────────────────────────────────────────
# 错误响应（CLAUDE.md D.3）
# ──────────────────────────────────────────────
class ErrorDetail(BaseModel):
    code: str  # 形如 RETRIEVAL_FAILED / INPUT_TOO_LONG
    message: str
    details: dict | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


# ──────────────────────────────────────────────
# 语料统计（GET /api/stats）— 前端动态展示规范库覆盖
# ──────────────────────────────────────────────
class DomainStat(BaseModel):
    """单个规范域的统计。"""

    domain: str = Field(..., description="规范域，如 规划/建筑/景观/消防")
    spec_count: int = Field(..., description="该域规范部数")
    chunk_count: int = Field(..., description="该域条文 chunk 数")


class CorpusStats(BaseModel):
    """规范库整体统计。前端 Sidebar / 顶栏的部数/条数/分类从此读取。"""

    total_specs: int = Field(..., description="规范总部数")
    total_chunks: int = Field(..., description="条文 chunk 总数")
    domain_count: int = Field(..., description="规范域类别数")
    domains: list[DomainStat] = Field(..., description="各域统计，按 chunk 数降序")
