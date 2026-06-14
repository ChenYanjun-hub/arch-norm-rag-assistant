"""一次性脚本：扫描 data/specs/ 下规范 PDF → 分块 → 向量化 → 入 Qdrant。

阶段：
  - W1-T1：分块 → JSON
  - W1-T2（当前）：+ embed → Qdrant upsert
  - W2 起：+ SQLite metadata 表

用法：
    cd backend
    # 完整链路（分块 + embed + upsert）
    .venv/bin/python -m scripts.ingest --file "GB50180-2018《城市居住区规划设计标准》_可搜索.pdf"
    .venv/bin/python -m scripts.ingest --all

    # 仅分块，不入 Qdrant（W1-T1 模式，跳过 ML 依赖）
    .venv/bin/python -m scripts.ingest --file "..." --no-embed

    # 清空 Qdrant collection 重建
    .venv/bin/python -m scripts.ingest --all --rebuild
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

    # ══════════ W7 D8 批量新增 50 部（用户确认归类；新增 结构/市政 2 域）══════════
    # ── 规划（+11）──
    "CJ:T553-2024": "规划", "CJJ:T87—2020": "规划", "GB 55028-2022": "规划",
    "GB50442-2008": "规划", "GB:T51329-2018": "规划", "GB:T51358—2019": "规划",
    "建标[2012]192号": "规划", "JGJ:T30-2015": "规划",
    "GB51287-2018": "规划", "GB51411—2020": "规划",
    "《历史文化名城名镇名村保护条例》(2017年修正_可搜索.pdf": "规划",
    # ── 建筑（+9）──
    "建标 109—2008": "建筑", "CJJ14-2016": "建筑", "GB50763-2012": "建筑",
    "GB:T50948-2013": "建筑", "JGJ:T280-2012": "建筑", "JGJ:T41-2014": "建筑",
    "建标192—2018号": "建筑",
    "《公共美术馆建设标准》_可搜索.pdf": "建筑",
    "《城市普通中小学校校舍建设标准》_可搜索.pdf": "建筑",
    # ── 景观（+5）──
    "CJJ:T171-2012": "景观", "CJJ:T237-2016": "景观", "CJJ:T292-2018": "景观",
    "GB:T51163-2016": "景观", "GB:T51168-2016": "景观",
    # ── 消防（+3）──
    "GB 55036-2022": "消防", "GB50067-2014": "消防", "建标[2015]273号": "消防",
    # ── 结构（新域 +4）──
    "CJJ:T301-2020": "结构", "JGJ99-2015": "结构",
    "JGJ:T259-2012": "结构", "JGJ:T415-2017": "结构",
    # ── 市政（新域 +18）──
    "CJJ193-2012": "市政", "CJJ194-2013": "市政", "CJJ221-2015": "市政",
    "CJJ36-2016": "市政", "CJJ45-2015": "市政", "CJJ52-2014": "市政",
    "CJJ:T100-2017": "市政", "CJJ:T149-2021": "市政", "CJJ:T307-2019": "市政",
    "GB50838-2015": "市政", "GB51354-2019": "市政", "GB55011-2021": "市政",
    "GB:T50293-2014": "市政", "GB:T51074-2015": "市政", "GB:T51293-2018": "市政",
    "GB:T51357-2019": "市政", "建标函[2004]43号": "市政",
    "GB51222-2017城镇内涝防治技术规范》_可搜索.pdf": "市政",
}


def resolve_domain(filename: str) -> str | None:
    """根据文件名前缀匹配 domain。匹配失败返回 None。

    自动 strip 前导/末尾空白，以兼容文件名前导空格的边角情况。
    """
    name = filename.strip()
    # 按最长前缀优先
    for prefix in sorted(DOMAIN_BY_FILENAME_PREFIX, key=len, reverse=True):
        if name.startswith(prefix):
            return DOMAIN_BY_FILENAME_PREFIX[prefix]
    return None


# 不规则文件名手动 override：(spec_code, spec_name)
# 当 chunker.parse_filename 解析失败时用作回退
INGEST_FILENAME_OVERRIDES: dict[str, tuple[str, str]] = {
    "上海市“15分钟社区生活圈”行动工作导引》.pdf": (
        "沪规划资源（2021）",
        "上海市15分钟社区生活圈行动工作导引",
    ),
    # W7 D8：文件名无标准号 / 解析失败的 4 部
    "GB51222-2017城镇内涝防治技术规范》_可搜索.pdf": (
        "GB 51222-2017", "城镇内涝防治技术规范"),
    "《公共美术馆建设标准》_可搜索.pdf": (
        "公共美术馆建设标准", "公共美术馆建设标准"),
    "《历史文化名城名镇名村保护条例》(2017年修正_可搜索.pdf": (
        "历史文化名城名镇名村保护条例(2017修正)", "历史文化名城名镇名村保护条例"),
    "《城市普通中小学校校舍建设标准》_可搜索.pdf": (
        "城市普通中小学校校舍建设标准", "城市普通中小学校校舍建设标准"),
}


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


def process_one(
    pdf_path: Path,
    *,
    domain: str | None = None,
    embed: bool = True,
) -> dict:
    """处理单个 PDF：分块 → (可选) embed → (可选) upsert，返回统计信息。"""
    t0 = time.time()
    domain_final = domain or resolve_domain(pdf_path.name)
    if not domain_final:
        raise ValueError(
            f"无法判定 domain：{pdf_path.name}。请在 ingest.py 的 DOMAIN_BY_FILENAME_PREFIX 补充映射"
        )

    override = INGEST_FILENAME_OVERRIDES.get(pdf_path.name) or INGEST_FILENAME_OVERRIDES.get(
        pdf_path.name.strip()
    )
    if override:
        spec_code_o, spec_name_o = override
        chunks = chunk_pdf(
            pdf_path,
            domain=domain_final,
            spec_code_override=spec_code_o,
            spec_name_override=spec_name_o,
        )
    else:
        chunks = chunk_pdf(pdf_path, domain=domain_final)
    if not chunks:
        logger.warning(f"[ingest] {pdf_path.name} 未产生任何 chunk")
        return {"file": pdf_path.name, "chunks": 0, "elapsed_s": time.time() - t0}

    spec_code = chunks[0].spec_code
    out_name = f"{slugify_spec_code(spec_code)}.json"
    out_path = CHUNKS_DIR / out_name
    write_chunks_json(chunks, out_path)
    t_chunk = time.time()

    # ── 向量化 + 入 Qdrant ──
    embed_seconds = 0.0
    upsert_seconds = 0.0
    if embed:
        # 延迟 import，仅在需要时拉重型依赖
        from app.rag.embedder import embed_texts
        from app.rag.retriever import ensure_collection, upsert_chunks

        ensure_collection()

        texts = [c.text for c in chunks]
        logger.info(f"[ingest] BGE-M3 编码 {len(texts)} 条 chunks...")
        t_embed_start = time.time()
        vectors = embed_texts(texts, batch_size=16)
        embed_seconds = time.time() - t_embed_start

        t_upsert_start = time.time()
        upsert_chunks(chunks, vectors)
        upsert_seconds = time.time() - t_upsert_start

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
        "chunk_seconds": round(t_chunk - t0, 2),
        "embed_seconds": round(embed_seconds, 2),
        "upsert_seconds": round(upsert_seconds, 2),
        "embedded": embed,
    }
    logger.info(
        f"[ingest] ✅ {pdf_path.name} → {len(chunks)} chunks "
        f"(clause={types.get('clause', 0)}, table={types.get('table', 0)}, "
        f"formula={types.get('formula', 0)}, appendix={types.get('appendix', 0)}, "
        f"mandatory={mandatory_count}) · 总 {elapsed:.1f}s "
        f"[chunk {t_chunk-t0:.1f}s + embed {embed_seconds:.1f}s + upsert {upsert_seconds:.1f}s]"
    )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="规范 PDF 分块 + 向量化入库（W1-T2 完整链路）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", help="处理单个 PDF（传文件名，不含路径）")
    group.add_argument("--all", action="store_true", help="处理 specs/ 下全部 PDF")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="清空 chunks/ JSON + 重建 Qdrant collection 后重跑",
    )
    parser.add_argument(
        "--no-embed", action="store_true", help="只分块，不调 BGE-M3 / 不写 Qdrant"
    )
    parser.add_argument(
        "--report", default=str(CHUNKS_DIR / "_ingest_report.json"), help="统计报告输出路径"
    )
    args = parser.parse_args()

    embed = not args.no_embed

    if args.rebuild:
        if CHUNKS_DIR.exists():
            logger.info(f"[ingest] --rebuild：清空 {CHUNKS_DIR}")
            for f in CHUNKS_DIR.glob("*.json"):
                f.unlink()
        if embed:
            # 重建 Qdrant collection
            from app.rag.retriever import ensure_collection
            logger.info("[ingest] --rebuild：重建 Qdrant collection")
            ensure_collection(recreate=True)

    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

    if args.file:
        pdf_path = SPECS_DIR / args.file
        if not pdf_path.exists():
            logger.error(f"文件不存在: {pdf_path}")
            return 2
        stats = process_one(pdf_path, embed=embed)
        all_stats = [stats]
    else:
        pdfs = list_spec_pdfs()
        logger.info(
            f"[ingest] 共发现 {len(pdfs)} 部 PDF（已排除 {len(INGEST_EXCLUDE_FILES)} 部）"
            f"，embed={'ON' if embed else 'OFF'}"
        )
        all_stats = []
        for i, pdf in enumerate(pdfs, start=1):
            logger.info(f"[ingest] ─── ({i}/{len(pdfs)}) ───")
            try:
                all_stats.append(process_one(pdf, embed=embed))
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
