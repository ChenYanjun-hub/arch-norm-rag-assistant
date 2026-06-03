"""W6 D1：批量修 chunks 里的 OCR 系统性错字（启示 49 落地修复）。

W5 D5 check_chunks_quality.py 扫到 27 处错字，4 类系统性 OCR 误识：
  - 坏境 → 环境（17 处）
  - 贼市 → 城市（5 处）
  - 改著 → 改善（4 处）
  - 政计 → 设计（1 处）

中文里这 4 个错字都没有合法搭配，可以批量替换。

用法：
    python -m scripts.fix_chunks_ocr --dry-run     # 预演（默认）
    python -m scripts.fix_chunks_ocr --apply       # 实际写入

写入后必须重 ingest：
    python -m scripts.ingest_chunks_to_qdrant      # 重建向量

每次跑会在 chunk metadata 加 ocr_fixed_v1=True 标记，便于 audit。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
CHUNKS_DIR = _BACKEND / "data" / "chunks"

# W5 D5 沉淀的修复字典（每条都人工 review 过上下文，100% 无歧义）
FIX_MAP = {
    "坏境": "环境",
    "贼市": "城市",
    "改著": "改善",
    "政计": "设计",
}


def fix_text(text: str) -> tuple[str, int]:
    """对单个 chunk text 应用所有修复，返回 (new_text, n_replacements)。"""
    new_text = text
    total = 0
    for err, fix in FIX_MAP.items():
        if err in new_text:
            count = new_text.count(err)
            new_text = new_text.replace(err, fix)
            total += count
    return new_text, total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="实际写入 chunks 文件（默认仅 dry-run）")
    parser.add_argument("--chunks-dir", type=Path, default=CHUNKS_DIR)
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n🔧 OCR 修复模式：{mode}\n")
    print(f"   修复字典: {FIX_MAP}")
    print(f"   chunks 目录: {args.chunks_dir}\n")

    total_files = 0
    total_chunks_changed = 0
    total_replacements = 0
    file_summary = []

    for jf in sorted(args.chunks_dir.glob("*.json")):
        if jf.name.startswith("_"):
            continue
        data = json.loads(jf.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            continue

        file_changed = 0
        file_repl = 0
        for ck in data:
            if not isinstance(ck, dict):
                continue
            text = ck.get("text", "")
            if not text:
                continue
            new_text, n_repl = fix_text(text)
            if n_repl > 0:
                file_changed += 1
                file_repl += n_repl
                if args.apply:
                    ck["text"] = new_text
                    ck["ocr_fixed_v1"] = True

        if file_changed:
            total_files += 1
            total_chunks_changed += file_changed
            total_replacements += file_repl
            file_summary.append((jf.name, file_changed, file_repl))
            if args.apply:
                jf.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

    print(f"📊 影响文件：{total_files} 个")
    print(f"📊 影响 chunks：{total_chunks_changed} 条")
    print(f"📊 总替换数：{total_replacements} 处\n")

    print(f"{'文件':<32} | chunks | 替换数")
    print("-" * 60)
    for name, n_ck, n_repl in file_summary:
        print(f"{name:<32} | {n_ck:>6} | {n_repl:>6}")

    if not args.apply:
        print(f"\n💡 dry-run 完成。如确认无误，加 --apply 实际写入。")
        print(f"   后续：python -m scripts.ingest_chunks_to_qdrant  # 重建向量")
    else:
        print(f"\n✅ 已写入 chunks 文件 + 加 ocr_fixed_v1=True 标记")
        print(f"   ⚠️  必须重 ingest 到 Qdrant 才能让 RAG 检索到修复后的内容")


if __name__ == "__main__":
    main()
