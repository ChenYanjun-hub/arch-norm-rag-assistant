"""一次性脚本：扫描 data/specs/ 下规范 PDF → 分块 → 输出 chunks/{spec_code}.json。

当前阶段（W1-T1）：只跑分块 + 落地 JSON。
  - 不调用 embedder
  - 不写入 Qdrant
  - 不写入 SQLite

用法：
    cd backend
    .venv/bin/python -m scripts.ingest --file "GB50180-2018《城市居住区规划设计标准》_可搜索.pdf"
    .venv/bin/python -m scripts.ingest --all
    .venv/bin/python -m scripts.ingest --all --rebuild   # 删除旧 chunks/ 重跑

完整流水线（W1-T2 起）将追加：embed → upsert Qdrant → 写 SQLite metadata。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path

# 让脚本以 -m scripts.ingest 运行时能找到 app 包
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.rag.chunker import Chunk, chunk_pdf, parse_filename  # noqa: E402

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ingest")

SPECS_DIR = Path(settings.specs_dir)
CHUNKS_DIR = Path(settings.chunks_dir)

# 排除清单（docs/design/spec_domain_mapping.md §6）
INGEST_EXCLUDE_FILES: set[str] = {
    "JGJ39-2016《托儿所、幼儿园建筑设计规范》_可搜索.pdf",  # 2019 修订版已覆盖
}

# 文件名 → domain 映射（docs/design/spec_domain_mapping.md）
# key 用文件名前缀匹配，按更长前缀优先
DOMAIN_BY_FILENAME_PREFIX: dict[str, str] = {
    # ── 规划（17 部）──
    "CJJ:T199-2013": "规划",
    "CJJ:T314-2022": "规划",
    "DB31T+1557-2025": "规划",
    "GB 50180-2018": "规划",
    "GB50180-2018": "规划",
    "GB50318-2017": "规划",
    "GB50437-2007": "规划",
    "GB50442": "规划",
    "GB:T50298-2018": "规划",
    "GB:T50357-2018": "规划",
    "GB:T50546-2018": "规划",
    "GB:T51327-2018": "规划",
    "GB:T51328-2018": "规划",
    "GB:T51346-2019": "规划",
    "GB:T51402-2021": "规划",
    "GB:T51439-2021": "规划",
    "GBT+39972-2021": "规划",
    "GBT+43214-2023": "规划",
    "GBT+47131.1-2026": "规划",
    "上海市": "规划",
    # ── 建筑（14 部）──
    "GB 50368-2005": "建筑",
    "GB 55031-2022": "建筑",
    "GB50033-2013": "建筑",
    "GB50867-2013": "建筑",
    "GB51039-2014": "建筑",
    "GB:T50034-2024": "建筑",
    "GBT+21741-2021": "建筑",
    "JGJ39-2016《托儿所、幼儿园建筑设计规范》(2019年版)": "建筑",
    "JGJ76": "建筑",
    "JGJ286-2013": "建筑",
    "JGJ:T245-2024": "建筑",
    "建标 109": "建筑",
    "建标192": "建筑",
    # ── 景观（7 部）──
    "CJ:T24-2018": "景观",
    "CJJ:T75-2023": "景观",
    "CJJ:T91-2017": "景观",
    "CJJ:T287-2018": "景观",
    "CJJ:T308-2021": "景观",
    "DB5301:T 21": "景观",
    "GB 55014-2021": "景观",
    # ── 消防（3 部）──
    "GB 55037-2022": "消防",
    "DB31T+1695-2026": "消防",
    "WW:T 0125": "消防",
}


def resolve_domain(filename: str) -> str | None:
    """根据文件名前缀匹配 domain。匹配失败返回 None。"""
    # 按最长前缀优先
    for prefix in sorted(DOMAIN_BY_FILENAME_PREFIX, key=len, reverse=True):
        if filename.startswith(prefix):
            return DOMAIN_BY_FILENAME_PREFIX[prefix]
    return None


def list_spec_pdfs() -> list[Path]:
    """列出 specs_dir 下所有 PDF，按文件名排序。"""
    if not SPECS_DIR.exists():
        raise FileNotFoundError(f"specs 目录不存在: {SPECS_DIR}")
    pdfs = sorted(SPECS_DIR.glob("*.pdf"))
    return [p for p in pdfs if p.name not in INGEST_EXCLUDE_FILES]


def slugify_spec_code(spec_code: str) -> str:
    """把 spec_code 转为安全的文件名。
    例：'GB/T 50034-2024' → 'GBT_50034-2024'
    """
    return spec_code.replace("/", "").replace(" ", "_").replace(":", "")


def write_chunks_json(chunks: list[Chunk], out_path: Path) -> None:
    """落地 chunks 为 JSON 文件。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = [c.to_dict() for c in chunks]
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def process_one(pdf_path: Path, *, domain: str | None = None) -> dict:
    """处理单个 PDF，返回统计信息。"""
    t0 = time.time()
    domain_final = domain or resolve_domain(pdf_path.name)
    if not domain_final:
        raise ValueError(
            f"无法判定 domain：{pdf_path.name}。请在 ingest.py 的 DOMAIN_BY_FILENAME_PREFIX 补充映射"
        )

    chunks = chunk_pdf(pdf_path, domain=domain_final)
    if not chunks:
        logger.warning(f"[ingest] {pdf_path.name} 未产生任何 chunk")
        return {"file": pdf_path.name, "chunks": 0, "elapsed_s": time.time() - t0}

    spec_code = chunks[0].spec_code
    out_name = f"{slugify_spec_code(spec_code)}.json"
    out_path = CHUNKS_DIR / out_name
    write_chunks_json(chunks, out_path)

    # 统计
    types = Counter(c.type for c in chunks)
    mandatory_count = sum(1 for c in chunks if c.is_mandatory)
    sizes = [c.char_count for c in chunks]
    elapsed = time.time() - t0

    stats = {
        "file": pdf_path.name,
        "spec_code": spec_code,
        "domain": domain_final,
        "chunks_total": len(chunks),
        "by_type": dict(types),
        "mandatory_count": mandatory_count,
        "char_min": min(sizes),
        "char_max": max(sizes),
        "char_avg": round(sum(sizes) / len(sizes), 1),
        "out": str(out_path.relative_to(Path(settings.specs_dir).parent.parent)),
        "elapsed_s": round(elapsed, 2),
    }
    logger.info(
        f"[ingest] ✅ {pdf_path.name} → {len(chunks)} chunks "
        f"(clause={types.get('clause', 0)}, table={types.get('table', 0)}, "
        f"formula={types.get('formula', 0)}, appendix={types.get('appendix', 0)}, "
        f"mandatory={mandatory_count}) · {elapsed:.1f}s"
    )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="规范 PDF 分块入库（W1-T1：只跑分块到 JSON）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", help="处理单个 PDF（传文件名，不含路径）")
    group.add_argument("--all", action="store_true", help="处理 specs/ 下全部 PDF")
    parser.add_argument(
        "--rebuild", action="store_true", help="删除 chunks/ 旧文件后重跑"
    )
    parser.add_argument(
        "--report", default=str(CHUNKS_DIR / "_ingest_report.json"), help="统计报告输出路径"
    )
    args = parser.parse_args()

    if args.rebuild and CHUNKS_DIR.exists():
        logger.info(f"[ingest] --rebuild：清空 {CHUNKS_DIR}")
        for f in CHUNKS_DIR.glob("*.json"):
            f.unlink()

    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

    if args.file:
        pdf_path = SPECS_DIR / args.file
        if not pdf_path.exists():
            logger.error(f"文件不存在: {pdf_path}")
            return 2
        stats = process_one(pdf_path)
        all_stats = [stats]
    else:
        pdfs = list_spec_pdfs()
        logger.info(f"[ingest] 共发现 {len(pdfs)} 部 PDF（已排除 {len(INGEST_EXCLUDE_FILES)} 部）")
        all_stats = []
        for i, pdf in enumerate(pdfs, start=1):
            logger.info(f"[ingest] ─── ({i}/{len(pdfs)}) ───")
            try:
                all_stats.append(process_one(pdf))
            except Exception as e:
                logger.exception(f"[ingest] ❌ {pdf.name} 失败：{e}")
                all_stats.append({"file": pdf.name, "error": str(e)})

    # 汇总报告
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "total_files": len(all_stats),
                "succeeded": sum(1 for s in all_stats if "error" not in s),
                "failed": sum(1 for s in all_stats if "error" in s),
                "details": all_stats,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    logger.info(f"[ingest] 报告已写入：{report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
