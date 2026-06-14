"""增量分块：只为 specs/ 中尚未生成 chunks 的 PDF 生成 chunks（不 embed）。

区别于 `ingest --all`（会重切已入库 PDF，覆盖已做的 OCR 修复）——本工具
只碰"缺失"的 PDF，保护既有 chunks。生成后用 reindex_from_chunks 统一 embed。

用法：
    python -m scripts.ingest_missing --dry     # 只列出缺哪些，不写
    python -m scripts.ingest_missing           # 实际分块（不 embed）
    # 之后： python -m scripts.reindex_from_chunks --rebuild   # 统一向量化
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from scripts.ingest import (
    CHUNKS_DIR,
    INGEST_FILENAME_OVERRIDES,
    SPECS_DIR,
    process_one,
    resolve_domain,
    slugify_spec_code,
)
from app.rag.chunker import parse_filename


def _spec_code_of(name: str) -> str | None:
    """取文件名的 spec_code（优先 override，再 parse_filename）。"""
    if name in INGEST_FILENAME_OVERRIDES:
        return INGEST_FILENAME_OVERRIDES[name][0]
    try:
        code, _ = parse_filename(name)
        return code
    except Exception:
        return None


def find_missing() -> list[Path]:
    """specs/ 中尚未生成 chunks JSON 的 PDF。"""
    missing: list[Path] = []
    for pdf in sorted(SPECS_DIR.glob("*.pdf")):
        code = _spec_code_of(pdf.name)
        if code is None:
            continue  # 无法解析的留给 overrides 配置；这里跳过
        if not (CHUNKS_DIR / f"{slugify_spec_code(code)}.json").exists():
            missing.append(pdf)
    return missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true", help="只列出缺失，不分块")
    args = parser.parse_args()

    missing = find_missing()
    print(f"📋 待入库（未生成 chunks）：{len(missing)} 部\n")
    for p in missing:
        dom = resolve_domain(p.name) or "?未映射"
        print(f"  [{dom}] {p.name[:55]}")

    if args.dry:
        print("\n💡 dry 模式：未写入。去掉 --dry 实际分块。")
        return 0
    if not missing:
        print("\n✅ 无缺失，全部已入库。")
        return 0

    print(f"\n🔧 开始分块（不 embed）...\n")
    ok, fail = 0, []
    t0 = time.time()
    for i, pdf in enumerate(missing, 1):
        try:
            stat = process_one(pdf, embed=False)
            ok += 1
            print(f"  [{i}/{len(missing)}] ✅ {pdf.name[:42]} → {stat.get('chunks')} chunks")
        except Exception as e:  # 单个失败不中断整批
            fail.append((pdf.name, str(e)))
            print(f"  [{i}/{len(missing)}] ❌ {pdf.name[:42]}: {e}")

    print(f"\n📊 完成：成功 {ok} / 失败 {len(fail)} / 用时 {(time.time()-t0)/60:.1f}min")
    for n, e in fail:
        print(f"  FAIL {n[:45]} :: {e}")
    if ok:
        print("\n⚠️  下一步必须： python -m scripts.reindex_from_chunks --rebuild  # 统一向量化")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
