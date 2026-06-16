"""GET /api/stats ── 规范库语料统计（前端动态展示覆盖范围）。

前端 Sidebar 的域计数、顶栏的"X 部规范 · X 条条文 · X 类"从此接口读取，
不再硬编码。以后加规范只需重 ingest + 重启后端，前端自动反映新数字。

数据源：data/chunks/*.json（= 入库到 Qdrant 的同一份语料）。
模块级缓存：语料在后端运行期间不变，首次计算后缓存（与 spec.py 同模式）。
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.models.schemas import CorpusStats, DomainStat, SpecBrief
from app.services.spec_status import get_spec_status

logger = logging.getLogger(__name__)
router = APIRouter()

# 模块级缓存（语料运行期间不变）
_STATS_CACHE: CorpusStats | None = None


def _compute_stats() -> CorpusStats:
    """扫描 chunks/*.json 聚合 domain → (规范部数, chunk 数)。"""
    chunks_dir = Path(settings.chunks_dir)
    if not chunks_dir.exists():
        raise FileNotFoundError(f"chunks 目录不存在: {chunks_dir}")

    # domain → {spec_code: spec_name}（spec_name 取自入库元数据，干净，可直接展示）
    names_by_domain: dict[str, dict[str, str]] = defaultdict(dict)
    chunks_by_domain: dict[str, int] = defaultdict(int)

    for jf in chunks_dir.glob("*.json"):
        if jf.name.startswith("_"):
            continue  # 跳过 _ingest_report.json 等非语料文件
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"[stats] 跳过无法读取的 chunks 文件 {jf.name}: {e}")
            continue
        if not isinstance(data, list):
            continue
        for ck in data:
            if not isinstance(ck, dict):
                continue
            domain = ck.get("domain") or "未分类"
            spec_code = ck.get("spec_code") or jf.stem
            # 首见即记名（同一规范各 chunk 的 spec_name 一致）
            names_by_domain[domain].setdefault(spec_code, ck.get("spec_name") or spec_code)
            chunks_by_domain[domain] += 1

    domains = []
    for d, code_names in names_by_domain.items():
        specs = sorted(
            (
                SpecBrief(
                    spec_code=code,
                    spec_name=name,
                    status=get_spec_status(code)["status"],
                )
                for code, name in code_names.items()
            ),
            key=lambda s: s.spec_code,
        )
        domains.append(
            DomainStat(
                domain=d,
                spec_count=len(code_names),
                chunk_count=chunks_by_domain[d],
                specs=specs,
            )
        )
    # 按 chunk 数降序：规划 > 建筑 > 景观 > 消防（与前端展示顺序一致）
    domains.sort(key=lambda x: x.chunk_count, reverse=True)

    return CorpusStats(
        total_specs=sum(d.spec_count for d in domains),
        total_chunks=sum(d.chunk_count for d in domains),
        domain_count=len(domains),
        domains=domains,
    )


def get_corpus_stats() -> CorpusStats:
    """返回语料统计（模块级缓存，首次计算后复用）。"""
    global _STATS_CACHE
    if _STATS_CACHE is None:
        _STATS_CACHE = _compute_stats()
        logger.info(
            f"[stats] 语料统计: {_STATS_CACHE.total_specs} 部 / "
            f"{_STATS_CACHE.total_chunks} 条 / {_STATS_CACHE.domain_count} 类"
        )
    return _STATS_CACHE


@router.get("/stats", response_model=CorpusStats)
def stats() -> CorpusStats:
    """规范库语料统计（部数 / 条数 / 分类 / 各域计数）。"""
    try:
        return get_corpus_stats()
    except Exception as e:  # 转统一错误，避免裸 500（不用裸 except）
        logger.error(f"[stats] 计算失败: {e}")
        raise HTTPException(status_code=500, detail="语料统计暂不可用") from e
