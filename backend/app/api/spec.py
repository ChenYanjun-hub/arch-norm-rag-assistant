"""GET /api/spec/{spec_code} ── 获取规范 PDF 文件（用于原文跳转）。

CitationCard 点击"查看原文" → 浏览器新窗口打开
`http://localhost:8000/api/spec/GB%2050180-2018#page=18`，
PDF 内置查看器自动跳转到锚点页码。

实现策略：
- 模块加载时扫描 data/specs/ 建立 spec_code → 文件路径 索引
- 同时尊重 ingest 的 INGEST_FILENAME_OVERRIDES（不规则命名）
- 返回 FileResponse，Content-Disposition: inline（浏览器内显示而非下载）

参数：
- spec_code：URL 编码后的 spec_code，例如 "GB%2050180-2018"
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.config import settings
from app.rag.chunker import parse_filename

logger = logging.getLogger(__name__)
router = APIRouter()

# 与 scripts/ingest.py 保持一致的不规则文件名映射
_OVERRIDES_FILE_TO_CODE: dict[str, str] = {
    "上海市“15分钟社区生活圈”行动工作导引》.pdf": "沪规划资源（2021）",
}


def _normalize_code(code: str) -> str:
    """归一化 spec_code 用于匹配，忽略空格 / 大小写差异。"""
    return re.sub(r"\s+", "", code).upper()


def _build_index() -> dict[str, Path]:
    """扫描 specs/ 建立 normalized spec_code → 文件路径 索引。"""
    specs_dir = Path(settings.specs_dir)
    if not specs_dir.exists():
        logger.warning(f"[spec] specs 目录不存在: {specs_dir}")
        return {}

    index: dict[str, Path] = {}
    for pdf in specs_dir.glob("*.pdf"):
        # 优先用 overrides
        if pdf.name in _OVERRIDES_FILE_TO_CODE:
            code = _OVERRIDES_FILE_TO_CODE[pdf.name]
            index[_normalize_code(code)] = pdf
            continue
        try:
            spec_code, _ = parse_filename(pdf.name)
            index[_normalize_code(spec_code)] = pdf
        except ValueError:
            logger.debug(f"[spec] 跳过无法解析的文件名: {pdf.name}")
    logger.info(f"[spec] 规范 PDF 索引建立完成: {len(index)} 部")
    return index


# 模块级缓存
_SPEC_INDEX: dict[str, Path] | None = None


def _get_index() -> dict[str, Path]:
    global _SPEC_INDEX
    if _SPEC_INDEX is None:
        _SPEC_INDEX = _build_index()
    return _SPEC_INDEX


@router.get("/spec/{spec_code:path}")
def get_spec_pdf(spec_code: str) -> FileResponse:
    """按 spec_code 返回 PDF 文件（inline 显示）。

    spec_code 包含斜杠时建议前端做 URL 编码或用空格替代；
    用 :path 转换器允许斜杠直传。
    """
    index = _get_index()
    norm = _normalize_code(spec_code)
    pdf_path = index.get(norm)

    if pdf_path is None:
        logger.warning(f"[spec] 未找到 spec_code={spec_code!r} (norm={norm!r})")
        raise HTTPException(
            status_code=404,
            detail=f"未找到规范 PDF：{spec_code}（可能未入库或文件名特殊）",
        )

    if not pdf_path.exists():
        # 软链接断裂等
        logger.error(f"[spec] PDF 文件不存在: {pdf_path}")
        raise HTTPException(status_code=500, detail="PDF 文件丢失")

    logger.info(f"[spec] 返回 {spec_code} → {pdf_path.name}")

    # 文件名含中文：HTTP header 用 latin-1 编码，需走 RFC 5987 filename*=
    # ASCII 兜底名取 spec_code 的"安全"形式
    ascii_fallback = re.sub(r"[^A-Za-z0-9._-]", "_", _normalize_code(spec_code)) + ".pdf"
    utf8_encoded = quote(pdf_path.name, safe="")
    disposition = (
        f'inline; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{utf8_encoded}"
    )

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/spec")
def list_specs() -> dict:
    """列出当前可查的所有规范（调试用）。"""
    index = _get_index()
    return {
        "total": len(index),
        "specs": sorted(
            [
                {"spec_code": k, "filename": v.name}
                for k, v in index.items()
            ],
            key=lambda x: x["spec_code"],
        ),
    }
