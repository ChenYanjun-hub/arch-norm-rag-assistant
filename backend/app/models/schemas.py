"""Pydantic 数据模型：所有 API 请求/响应的统一定义（CLAUDE.md D.2）。

骨架阶段先定义核心 schema，后续 W2-W3 随 API 实现完善字段约束。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────
# 问答接口
# ──────────────────────────────────────────────
class Turn(BaseModel):
    """V2 多轮对话的单轮（前端传最近 N 轮历史）。"""

    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=2000)


class ChatRequest(BaseModel):
    """POST /api/chat 请求体。"""

    query: str = Field(..., min_length=1, max_length=4000, description="用户问题")
    session_id: str | None = Field(None, description="会话 ID（V2 多轮用）")
    domain: str | None = Field(
        None, description="可选 domain 限定（规划/建筑/景观/消防）"
    )
    spec_codes: list[str] | None = Field(
        None, description="可选 spec_code 列表限定（多选，命中任一即可）"
    )
    history: list[Turn] | None = Field(
        None, description="V2 多轮：最近 N 轮对话历史（用于指代消解）"
    )


class Citation(BaseModel):
    """引用结构化数据。任何引用元数据错误都是 P0 bug（CLAUDE.md 红线 2）。"""

    spec_name: str = Field(..., description="规范全称，如《城市居住区规划设计标准》")
    spec_code: str = Field(..., description="标准号含年份，如 GB 50180-2018")
    clause: str = Field(..., description="条文号，如 表 5.0.3 或 第 4.2.3 条")
    page: int | None = Field(None, description="PDF 页码（用于跳转）")
    is_mandatory: bool = Field(False, description="是否强制性条文")
    has_formula: bool = Field(False, description="本条含计算公式，前端提示以原文 PDF 为准")
    original_text: str = Field(..., max_length=200, description="原文摘引，建议 ≤ 50 字")
    domain: str = Field("", description="规范类别，如 规划/建筑/景观/消防/结构/市政")
    # 规范现行状态（默认"现行"，例外登记在 services/spec_status.py；🔴 状态不臆断）
    status: Literal["现行", "已废止", "局部废止", "即将实施"] = Field(
        "现行", description="规范现行状态"
    )
    replaced_by: str | None = Field(None, description="若已废止/被替代，现行替代标准号")
    status_note: str | None = Field(None, description="状态补充说明，如废止/施行日期")


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
class SpecBrief(BaseModel):
    """规范清单项（侧栏分类展开 / 点选导航用）。"""

    spec_code: str = Field(..., description="标准号，如 GB 50180-2018")
    spec_name: str = Field(..., description="规范全称（取自入库元数据，非 OCR 正文，干净）")
    status: Literal["现行", "已废止", "局部废止", "即将实施"] = Field(
        "现行", description="规范现行状态（复用 spec_status）"
    )


class DomainStat(BaseModel):
    """单个规范域的统计。"""

    domain: str = Field(..., description="规范域，如 规划/建筑/景观/消防")
    spec_count: int = Field(..., description="该域规范部数")
    chunk_count: int = Field(..., description="该域条文 chunk 数")
    specs: list[SpecBrief] = Field(
        default_factory=list, description="该域规范清单（按标准号排序）"
    )


class CorpusStats(BaseModel):
    """规范库整体统计。前端 Sidebar / 顶栏的部数/条数/分类从此读取。"""

    total_specs: int = Field(..., description="规范总部数")
    total_chunks: int = Field(..., description="条文 chunk 总数")
    domain_count: int = Field(..., description="规范域类别数")
    domains: list[DomainStat] = Field(..., description="各域统计，按 chunk 数降序")
